#!/usr/bin/env python3
"""調査対象の各サイトについて、RSS/Atom フィードと新着一覧ページの候補を探す。

    python scripts/survey.py [--targets survey_targets.yaml] [--out reports/survey_agencies.csv]

- トップページを取得し（失敗したらエラーとして記録して次へ）、次の3通りでフィードの候補を集める
    1. <link rel="alternate" type="application/rss+xml"> など
    2. ページ内のリンクのうち、URL や文字が RSS / Atom / feed らしいもの
    3. よくあるパス（/rss.xml, /feed/, /news.rss など。サイトのトップとサブディレクトリの両方）
- 候補は実際に取得し、フィードとして読めて記事があるものだけを「有効」とする
- 新着一覧ページの候補は、リンク文字（新着・お知らせ・ニュースなど）や URL（news, topics など）で探し、
  上位の候補を取得して、ページ内の日付の数と日付の書式を数える（スクレイピング設定の参考）
- 結果を CSV に保存し、GITHUB_STEP_SUMMARY があれば Actions の実行結果画面に要約を書き出す
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlsplit

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (compatible; iwate-agencies-news-survey/1.0; "
    "+https://github.com/iwate-news-watch/agencies)"
)
TIMEOUT = 15
HOST_INTERVAL = 1.0  # 同じホストへのリクエスト間隔（秒）
MAX_NEWS_PAGES = 3   # 中身まで確認する新着一覧ページの候補数

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml",
              "application/xml", "text/xml", "application/feed+json")
FEED_HREF = re.compile(r"(rss|atom|feed|\.rdf$|\.xml$)", re.I)
FEED_TEXT = re.compile(r"(rss|atom|フィード)", re.I)
COMMON_FEED_PATHS = [
    "rss.xml", "rss", "rss/", "feed", "feed/", "atom.xml", "index.rdf", "index.xml", "index.rss",
    "news.rss", "news/rss.xml", "news/index.rss", "news/feed/", "feed.xml", "rss/news.xml",
    "cgi-bin/feed.php?siteNew=1",
]
NEWS_TEXT = re.compile(r"(新着|お知らせ|ニュース|NEWS|News|トピックス|TOPICS|報道発表|プレスリリース|"
                       r"記者発表|更新情報|一覧)")
NEWS_HREF = re.compile(r"(news|topics|info|press|whatsnew|oshirase|kisha|houdou|release|shinchaku)", re.I)
DATE_FORMATS = {
    "dotted": re.compile(r"\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}"),         # 2026.10.15
    "slash": re.compile(r"\d{4}\s*/\s*\d{1,2}\s*/\s*\d{1,2}"),            # 2026/10/15
    "kanji": re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"),      # 2026年10月15日
    "reiwa": re.compile(r"令和\s*(\d{1,2}|元)\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"),  # 令和8年10月15日
    "hyphen": re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),                       # 2026-10-15
}

COLUMNS = [
    "category", "name", "url", "status", "http_status", "final_url", "page_title",
    "feed_count", "feeds", "feed_candidates_checked", "news_page_candidates", "news_pages_checked",
    "error",
]

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"})
_last_by_host: dict[str, float] = {}


def get(url: str) -> requests.Response:
    """同じホストには間隔を空けて取得する（失敗しても例外はそのまま返す）。"""
    host = urlsplit(url).netloc
    wait = HOST_INTERVAL - (time.monotonic() - _last_by_host.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    try:
        return _session.get(url, timeout=TIMEOUT, allow_redirects=True)
    finally:
        _last_by_host[host] = time.monotonic()


def clean(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").split())


def soup_of(resp: requests.Response) -> BeautifulSoup:
    return BeautifulSoup(resp.content, "html.parser")


def norm_url(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    url = urldefrag(urljoin(base, href))[0]
    return url if url.startswith(("http://", "https://")) else None


def same_site(url: str, base: str) -> bool:
    """同じホスト（www. の有無は同一視）か。"""
    a, b = urlsplit(url).netloc.lower(), urlsplit(base).netloc.lower()
    return a.removeprefix("www.") == b.removeprefix("www.")


# --- フィード ----------------------------------------------------------------

def feed_candidates(soup: BeautifulSoup, page_url: str, start_url: str) -> list[tuple[str, str]]:
    """(URL, 見つけ方) の一覧。重複は最初の見つけ方を残す。"""
    found: dict[str, str] = {}

    def add(url: str | None, how: str) -> None:
        if url and url not in found:
            found[url] = how

    for link in soup.find_all("link", href=True):
        rel = [r.lower() for r in (link.get("rel") or [])]
        typ = (link.get("type") or "").lower()
        if "alternate" in rel and (typ in FEED_TYPES or FEED_HREF.search(link["href"])):
            add(norm_url(page_url, link["href"]), "link_alternate")

    for a in soup.find_all("a", href=True):
        url = norm_url(page_url, a["href"])
        if not url:
            continue
        text = clean(a.get_text(" ")) + " " + " ".join(clean(i.get("alt", "")) for i in a.find_all("img"))
        path = urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else "")
        if FEED_HREF.search(path) or FEED_TEXT.search(text):
            add(url, "page_link")

    # よくあるパス。指定URLのディレクトリ（例: /morioka/）と、ドメインのトップの両方で試す
    bases = []
    for b in (start_url, page_url):
        parts = urlsplit(b)
        d = parts.path if parts.path.endswith("/") else parts.path.rsplit("/", 1)[0] + "/"
        bases.append(f"{parts.scheme}://{parts.netloc}{d}")
        bases.append(f"{parts.scheme}://{parts.netloc}/")
    for b in dict.fromkeys(bases):
        for p in COMMON_FEED_PATHS:
            add(urljoin(b, p), "common_path")
    return list(found.items())


def check_feed(url: str) -> dict | None:
    """フィードとして読めて記事が1件以上あれば情報を返す。"""
    try:
        resp = get(url)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    ctype = resp.headers.get("Content-Type", "").lower()
    head = resp.content[:600].lstrip().lower()
    if "html" in ctype and not head.startswith(b"<?xml") and b"<rss" not in head and b"<feed" not in head:
        return None  # HTMLのページ（存在しないパスのトップページへの転送など）
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        return None
    latest = ""
    stamps = [e.get("published_parsed") or e.get("updated_parsed") for e in feed.entries]
    stamps = [s for s in stamps if s]
    if stamps:
        latest = datetime(*max(stamps)[:6], tzinfo=timezone.utc).astimezone(JST).date().isoformat()
    return {"url": resp.url, "version": feed.version or "unknown", "entries": len(feed.entries),
            "latest": latest, "title": clean(feed.feed.get("title", ""))[:40]}


# --- 新着一覧ページ ------------------------------------------------------------

def news_candidates(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str, int]]:
    """(URL, リンク文字, スコア) の一覧（スコアの高い順）。同じサイト内のリンクだけ。"""
    scored: dict[str, tuple[str, int]] = {}
    for a in soup.find_all("a", href=True):
        url = norm_url(page_url, a["href"])
        if not url or not same_site(url, page_url) or url.rstrip("/") == page_url.rstrip("/"):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|zip)$", urlsplit(url).path, re.I):
            continue
        text = clean(a.get_text(" "))[:40]
        score = 0
        if NEWS_TEXT.search(text):
            score += 2
        if re.search(r"(一覧|もっと見る|more|過去)", text, re.I):
            score += 1
        if NEWS_HREF.search(urlsplit(url).path):
            score += 1
        if score >= 2 and score > scored.get(url, ("", 0))[1]:
            scored[url] = (text, score)
    return sorted(((u, t, s) for u, (t, s) in scored.items()), key=lambda x: -x[2])


def date_profile(soup: BeautifulSoup) -> dict[str, int]:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = unicodedata.normalize("NFKC", soup.get_text(" "))
    counts = {k: len(p.findall(text)) for k, p in DATE_FORMATS.items()}
    # 「令和8年10月15日」は kanji には当たらないが、念のため重複を避ける
    return {k: v for k, v in counts.items() if v}


def fmt_dates(counts: dict[str, int]) -> str:
    return ",".join(f"{k}:{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])) or "日付なし"


# --- 1サイト分 ----------------------------------------------------------------

def survey(target: dict) -> dict:
    row = {c: "" for c in COLUMNS}
    row.update(category=target.get("category", ""), name=target["name"], url=target["url"])
    try:
        resp = get(target["url"])
    except requests.RequestException as e:
        row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
        return row
    row.update(http_status=resp.status_code, final_url=resp.url)
    if resp.status_code >= 400:
        row.update(status="error", error=f"HTTP {resp.status_code}")
        return row
    soup = soup_of(resp)
    row["page_title"] = clean(soup.title.get_text() if soup.title else "")[:80]
    row["status"] = "ok"
    if not same_site(resp.url, target["url"]):
        row["error"] = f"別のサイトに転送されました: {resp.url}"

    # フィード
    feeds, checked = [], 0
    seen_final: set[str] = set()
    for url, how in feed_candidates(soup, resp.url, target["url"]):
        checked += 1
        info = check_feed(url)
        if info and info["url"] not in seen_final:
            seen_final.add(info["url"])
            feeds.append({**info, "how": how})
    row["feed_count"] = len(feeds)
    row["feeds"] = " ; ".join(
        f'{f["url"]} [{f["how"]}, {f["version"]}, {f["entries"]}件, 最新{f["latest"] or "日付なし"}]'
        for f in feeds)
    row["feed_candidates_checked"] = checked

    # 新着一覧ページ（トップページ自身の日付も数える）
    news = news_candidates(soup, resp.url)
    row["news_page_candidates"] = " ; ".join(f"{u} [{t}]" for u, t, _ in news[:8])
    checked_pages = [f"(トップ) {resp.url} [{fmt_dates(date_profile(soup_of(resp)))}]"]
    for url, text, _ in news[:MAX_NEWS_PAGES]:
        try:
            r = get(url)
            if r.status_code >= 400:
                checked_pages.append(f"{url} [HTTP {r.status_code}]")
                continue
            checked_pages.append(f"{url} [{text}; {fmt_dates(date_profile(soup_of(r)))}]")
        except requests.RequestException as e:
            checked_pages.append(f"{url} [{type(e).__name__}]")
    row["news_pages_checked"] = " ; ".join(checked_pages)
    return row


# --- 出力 ---------------------------------------------------------------------

def md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_summary(rows: list[dict], out: Path, path: str) -> None:
    ok = sum(r["status"] == "ok" for r in rows)
    with_feed = sum(bool(r["feed_count"]) for r in rows)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 国の機関・大学 取得元調査",
        "",
        f"{now}（日本時間） ・ 対象 {len(rows)} サイト ・ 取得成功 {ok} ・ "
        f"フィードあり {with_feed} ・ エラー {len(rows) - ok}",
        "",
        f"詳細はリポジトリの `{out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}` を見てください。",
        "",
        "| 分類 | 名称 | 状態 | フィード | 新着一覧ページの候補 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if r["status"] != "ok":
            state = f"❌ {r['error'] or 'エラー'}"
        else:
            state = f"✅ {r['http_status']}" + (f"（{r['error']}）" if r["error"] else "")
        feed = r["feeds"].split(" ; ")[0] if r["feeds"] else "なし"
        if r["feed_count"] and int(r["feed_count"]) > 1:
            feed += f" ほか{int(r['feed_count']) - 1}件"
        checked = r["news_pages_checked"].split(" ; ")
        news = checked[1] if len(checked) > 1 else (checked[0] if checked[0] else "")
        lines.append("| " + " | ".join(md_cell(x) for x in
                                         (r["category"], r["name"], state, feed, news or "—")) + " |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(ROOT / "survey_targets.yaml"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "survey_agencies.csv"))
    args = ap.parse_args()

    targets = (yaml.safe_load(Path(args.targets).read_text(encoding="utf-8")) or {}).get("targets") or []
    rows = []
    for t in targets:
        try:
            row = survey(t)
        except Exception as e:  # 1サイトの想定外の失敗で全体を止めない
            row = {c: "" for c in COLUMNS}
            row.update(category=t.get("category", ""), name=t["name"], url=t["url"], status="error",
                       error=f"{type(e).__name__}: {e}"[:300])
        print(f"[{row['status'].upper()}] {row['name']} {row['url']}: フィード {row['feed_count'] or 0}件"
              + (f" / {row['error']}" if row["error"] else ""), file=sys.stderr)
        rows.append(row)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Excel で開いても文字化けしないよう BOM 付き UTF-8
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"保存しました: {out}", file=sys.stderr)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        write_summary(rows, out, summary)


if __name__ == "__main__":
    main()
