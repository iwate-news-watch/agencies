#!/usr/bin/env python3
"""調査対象の各サイトについて、RSS/Atom フィードと新着一覧ページの候補を探す。

    python scripts/survey.py [--targets survey_targets.yaml] [--out CSV]

- 対象は survey_targets.yaml（保存先は同ファイルの output。--out で上書き可）
- 調べるページ（urls）ごとに、次の3通りでフィードの候補を集め、実際に読めて記事があるものを記録する
    1. <link rel="alternate" type="application/rss+xml"> など
    2. ページ内のリンクのうち、URL や文字が RSS / Atom / feed らしいもの
    3. よくあるパス（/rss.xml, /feed/, /news.rss など。そのページのディレクトリとドメインのトップの両方）
- 一覧ページの候補は次の順に集める
    1. urls と hints に書いたページそのもの
    2. それらのページにある「記者発表」「報道発表」「お知らせ」「新着」などのリンク（hints の下にあるリンクを優先）
    3. 2 のページをさらに1段たどった先にある同様のリンク
  候補ごとにページを取得し、日付の書式を判定して記事を拾い、件数・タイトル例・キーワードで絞った件数を記録する
- 1行に1候補の CSV に保存し、GITHUB_STEP_SUMMARY があれば Actions の実行結果画面に要約を書き出す
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402  日付の読み取り・キーワード絞り込みは本番と同じ処理を使う

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
# 一般的なブラウザに近い User-Agent（ボット向けに別のページを返すサイトや、拒否するサイトがあるため）
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 15
HOST_INTERVAL = 1.0   # 同じホストへのリクエスト間隔（秒）
FOLLOW_LINKS = 6      # 調べるページ1つにつき、1段目としてたどるリンクの数
MAX_LIST_PAGES = 14   # 1サイトで中身まで確認する一覧ページの候補の上限（urls・hints を除く）
SAMPLES = 5           # 記録するタイトル例の数

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml",
              "application/xml", "text/xml", "application/feed+json")
FEED_HREF = re.compile(r"(rss|atom|feed|\.rdf$|\.xml$)", re.I)
FEED_TEXT = re.compile(r"(rss|atom|フィード)", re.I)
COMMON_FEED_PATHS = [
    "rss.xml", "rss", "rss/", "feed", "feed/", "atom.xml", "index.rdf", "index.xml", "index.rss",
    "news.rss", "news/rss.xml", "news/index.rss", "news/feed/", "feed.xml", "rss/news.xml",
    "cgi-bin/feed.php?siteNew=1",
]
NEWS_TEXT = re.compile(r"(記者発表|報道発表|プレスリリース|お知らせ|新着|ニュース|NEWS|News|トピックス|TOPICS|"
                       r"更新情報|イベント|一覧)")
NEWS_HREF = re.compile(r"(news|topics|info|press|kisha|houdou|whatsnew|oshirase|release|shinchaku|event)", re.I)
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|pptx?|zip|csv|mp4)$", re.I)
SURVEY_DATE_FORMATS = ("dotted", "slash", "kanji", "reiwa", "reiwa_short")  # scripts/build.py で読める書式

COLUMNS = [
    "category", "name", "kind", "url", "found_via", "link_text", "status", "http_status",
    "date_format", "items", "keyword_items", "latest", "sample_titles", "keyword_samples", "error",
]

_session = requests.Session()
_session.headers.update(HEADERS)
_last_by_host: dict[str, float] = {}
_via_proxy = False  # 調査中のサイトを Worker（/proxy）経由で取得するか（survey_targets.yaml の via_proxy）


def get(url: str) -> requests.Response:
    """同じホストには間隔を空けて取得する（失敗しても例外はそのまま返す）。

    via_proxy のサイトは Worker 経由で取得し、resp.url は Worker ではなく取得先の最終URLにする。
    """
    real = build.fetch_url({"url": url, "via_proxy": _via_proxy})
    host = urlsplit(url).netloc
    wait = HOST_INTERVAL - (time.monotonic() - _last_by_host.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    try:
        resp = _session.get(real, timeout=TIMEOUT + (15 if _via_proxy else 0), allow_redirects=True)
    finally:
        _last_by_host[host] = time.monotonic()
    if _via_proxy:
        resp.url = resp.headers.get("X-Proxy-Final-Url") or url
    return resp


def clean(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").split())


def page_text(resp: requests.Response) -> str:
    charset = requests.utils.get_encoding_from_headers(resp.headers)
    if charset == "ISO-8859-1":  # requests の text/* 既定値。宣言なしとみなす
        charset = None
    return build.decode_html(resp.content, charset)


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


def empty_row(target: dict, **kw) -> dict:
    row = {c: "" for c in COLUMNS}
    row.update(category=target.get("category", ""), name=target["name"])
    row.update(kw)
    return row


def fmt_samples(items: list[dict]) -> str:
    return " ／ ".join(f'{i["date"] or "日付なし"} {i["title"][:50]}' for i in items[:SAMPLES])


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
        parts = urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        if FEED_HREF.search(path) or FEED_TEXT.search(text):
            add(url, "page_link")

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


def check_feed(url: str, keywords) -> dict | None:
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
    try:
        items = build.parse_feed(resp.content, resp.url)
    except ValueError:
        return None
    hits = build.keyword_filter(items, keywords)
    dates = sorted((i["date"] for i in items if i["date"]), reverse=True)
    return {"url": resp.url, "http_status": resp.status_code, "date_format": feed.version or "feed",
            "items": len(items), "keyword_items": len(hits) if keywords else "",
            "latest": dates[0] if dates else "", "sample_titles": fmt_samples(items),
            "keyword_samples": fmt_samples(hits) if keywords else ""}


# --- 一覧ページ ----------------------------------------------------------------

def news_links(soup: BeautifulSoup, page_url: str, hints: list[str]) -> list[tuple[str, str, int]]:
    """(URL, リンク文字, スコア) の一覧（スコアの高い順）。同じサイト内のリンクだけ。"""
    scored: dict[str, tuple[str, int]] = {}
    for a in soup.find_all("a", href=True):
        url = norm_url(page_url, a["href"])
        if not url or not same_site(url, page_url) or url.rstrip("/") == page_url.rstrip("/"):
            continue
        if SKIP_EXT.search(urlsplit(url).path):
            continue
        text = clean(a.get_text(" ") or " ".join(i.get("alt", "") for i in a.find_all("img")))[:40]
        score = 0
        if NEWS_TEXT.search(text):
            score += 2
        if re.search(r"(記者発表|報道発表|プレスリリース)", text):
            score += 1
        if re.search(r"(一覧|もっと見る|more|過去|バックナンバー)", text, re.I):
            score += 1
        if NEWS_HREF.search(urlsplit(url).path):
            score += 1
        if any(url.startswith(h) for h in hints):
            score += 3
        if score >= 2 and score > scored.get(url, ("", 0))[1]:
            scored[url] = (text, score)
    return sorted(((u, t, s) for u, (t, s) in scored.items()), key=lambda x: -x[2])


def evaluate_list(url: str, text: str, keywords) -> dict:
    """ページ内の日付の書式を判定し、本番と同じ読み取りで記事を拾う。"""
    plain = unicodedata.normalize("NFKC", BeautifulSoup(text, "html.parser").get_text(" "))
    counts = {f: len(build.DATE_PATTERNS[f].findall(plain)) for f in SURVEY_DATE_FORMATS}
    fmt = max(counts, key=lambda f: counts[f])
    if not counts[fmt]:
        return {"date_format": "日付なし", "items": 0, "keyword_items": 0 if keywords else ""}
    items = [i for i in build.scrape_dated_links(text, url, fmt) if i["date"]]
    hits = build.keyword_filter(items, keywords)
    dates = sorted((i["date"] for i in items), reverse=True)
    others = ",".join(f"{f}:{n}" for f, n in counts.items() if n and f != fmt)
    return {"date_format": fmt + (f"（ほか {others}）" if others else ""), "items": len(items),
            "keyword_items": len(hits) if keywords else "", "latest": dates[0] if dates else "",
            "sample_titles": fmt_samples(items), "keyword_samples": fmt_samples(hits) if keywords else ""}


def fetch_page(url: str) -> tuple[requests.Response | None, str, str]:
    """(レスポンス, 本文, エラー)。"""
    try:
        resp = get(url)
    except requests.RequestException as e:
        return None, "", f"{type(e).__name__}: {e}"[:300]
    if resp.status_code >= 400:
        return resp, "", f"HTTP {resp.status_code}"
    return resp, page_text(resp), ""


# --- 1サイト分 ----------------------------------------------------------------

def survey(target: dict) -> list[dict]:
    global _via_proxy
    _via_proxy = bool(target.get("via_proxy"))
    keywords = target.get("keywords") or []
    hints = target.get("hints") or []
    rows: list[dict] = []
    seen_feeds: set[str] = set()
    done: set[str] = set()      # 一覧ページとして確認済みのURL
    queue: list[tuple[str, str, str]] = []  # (URL, 見つけ方, リンク文字)

    def list_row(url: str, how: str, link_text: str, resp, text: str, err: str) -> dict:
        row = empty_row(target, kind="list", url=resp.url if resp is not None else url,
                        found_via=how, link_text=link_text)
        if resp is not None:
            row["http_status"] = resp.status_code
        if err:
            row.update(status="error", error=err)
        else:
            row.update(status="ok", **evaluate_list(resp.url, text, keywords))
        return row

    # 1. urls と hints に書いたページ
    level1: list[tuple[str, str, str]] = []
    for kind, url in [("start", u) for u in target.get("urls") or []] + [("hint", h) for h in hints]:
        resp, text, err = fetch_page(url)
        done.add(url)
        if kind == "start":
            site = empty_row(target, kind="site", url=url, found_via="start")
            if resp is not None:
                site.update(http_status=resp.status_code)
                if resp.url != url:
                    site["link_text"] = f"転送先: {resp.url}"
            if err:
                site.update(status="error", error=err)
                rows.append(site)
                continue
            soup = BeautifulSoup(text, "html.parser")
            site.update(status="ok", link_text=(site["link_text"] + " " if site["link_text"] else "")
                        + clean(soup.title.get_text() if soup.title else "")[:60])
            if not same_site(resp.url, url):
                site["error"] = f"別のサイトに転送されました: {resp.url}"
            rows.append(site)
            for furl, how in feed_candidates(soup, resp.url, url):
                info = check_feed(furl, keywords)
                if info and info["url"] not in seen_feeds:
                    seen_feeds.add(info["url"])
                    rows.append(empty_row(target, kind="feed", found_via=how, status="ok", **info))
        rows.append(list_row(url, kind, "", resp, text, err))
        if not err:
            soup = BeautifulSoup(text, "html.parser")
            level1 += [(u, "top_link", t) for u, t, _ in news_links(soup, resp.url, hints)[:FOLLOW_LINKS]]

    # 2. 1段目のリンク先を確認し、その先の候補（2段目）も集める
    level2: list[tuple[str, str, str]] = []
    checked = 0
    for url, how, link_text in level1:
        if url in done or checked >= MAX_LIST_PAGES:
            continue
        done.add(url)
        checked += 1
        resp, text, err = fetch_page(url)
        rows.append(list_row(url, how, link_text, resp, text, err))
        if not err:
            soup = BeautifulSoup(text, "html.parser")
            level2 += [(u, "level2_link", t) for u, t, _ in news_links(soup, resp.url, hints)[:FOLLOW_LINKS]]
    for url, how, link_text in level2:
        if url in done or checked >= MAX_LIST_PAGES:
            continue
        done.add(url)
        checked += 1
        resp, text, err = fetch_page(url)
        rows.append(list_row(url, how, link_text, resp, text, err))
    return rows


# --- 出力 ---------------------------------------------------------------------

def md_cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_summary(rows: list[dict], targets: list[dict], out: Path, path: str) -> None:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    rel = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    lines = [f"# 取得元調査（{now} 日本時間）", "", f"詳細はリポジトリの `{rel}` を見てください。", ""]
    for t in targets:
        mine = [r for r in rows if r["name"] == t["name"]]
        kw = t.get("keywords") or []
        lines.append(f"## {t['category']} ・ {t['name']}" + (f"（キーワード: {'、'.join(kw)}）" if kw else ""))
        for s in (r for r in mine if r["kind"] == "site"):
            state = f"❌ {s['error']}" if s["status"] == "error" else f"✅ {s['http_status']} {s['link_text']}"
            lines.append(f"- {s['url']} … {md_cell(state)}" + (f"（{s['error']}）" if s["status"] == "ok" and s["error"] else ""))
        cands = [r for r in mine if r["kind"] in ("feed", "list") and r["status"] == "ok" and r["items"]]
        key = (lambda r: (int(r["keyword_items"] or 0), r["kind"] == "feed", int(r["items"]))) if kw else \
              (lambda r: (r["kind"] == "feed", int(r["items"])))
        cands.sort(key=key, reverse=True)
        errors = [r for r in mine if r["kind"] == "list" and r["status"] == "error"]
        if not cands:
            lines.append("- 記事を拾える候補は見つかりませんでした")
        else:
            lines += ["", "| 種類 | URL | 見つけ方 | 書式 | 件数 | 絞込後 | 最新 | タイトル例 |",
                      "|---|---|---|---|---|---|---|---|"]
            for r in cands[:6]:
                ex = r["keyword_samples"] if kw and r["keyword_samples"] else r["sample_titles"]
                lines.append("| " + " | ".join(md_cell(x) for x in (
                    "フィード" if r["kind"] == "feed" else "一覧", r["url"],
                    r["found_via"] + (f"「{r['link_text']}」" if r["link_text"] and r["kind"] == "list" else ""),
                    r["date_format"], r["items"], r["keyword_items"] if kw else "—", r["latest"],
                    " ／ ".join(ex.split(" ／ ")[:3]))) + " |")
        if errors:
            lines.append("")
            lines.append("取得できなかった候補: " + "、".join(f"{r['url']}（{r['error']}）" for r in errors[:5]))
        lines.append("")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(ROOT / "survey_targets.yaml"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conf = yaml.safe_load(Path(args.targets).read_text(encoding="utf-8")) or {}
    targets = conf.get("targets") or []
    out = Path(args.out or ROOT / conf.get("output", "reports/survey_agencies.csv")).resolve()
    rows: list[dict] = []
    for t in targets:
        if "url" in t and "urls" not in t:  # 1回目の調査の書き方（url: 1つ）も読めるようにする
            t["urls"] = [t["url"]]
        try:
            mine = survey(t)
        except Exception as e:  # 1サイトの想定外の失敗で全体を止めない
            mine = [empty_row(t, kind="site", url=(t.get("urls") or [""])[0], status="error",
                              error=f"{type(e).__name__}: {e}"[:300])]
        ok = [r for r in mine if r["kind"] in ("feed", "list") and r["status"] == "ok" and r["items"]]
        print(f"[{t['name']}] 候補 {len(ok)} 件（確認 {len(mine)} ページ）", file=sys.stderr)
        rows += mine

    out.parent.mkdir(parents=True, exist_ok=True)
    # Excel で開いても文字化けしないよう BOM 付き UTF-8
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"保存しました: {out}", file=sys.stderr)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        write_summary(rows, targets, out, summary)


if __name__ == "__main__":
    main()
