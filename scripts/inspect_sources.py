#!/usr/bin/env python3
"""取得元の確認用。state は更新しない。

    python scripts/inspect_sources.py [--html]                    # sources.yaml の全取得元
    python scripts/inspect_sources.py --urls URL [URL ...] [--html] [--proxy]   # 指定したページだけ診断

sources.yaml の全取得元（既定）
- reports/inspect_sources.csv に 機関・取得元・タイトル・URL・日付・リンクの場所（親要素の並び）を書き出す
- --html を付けると、scrape の取得元のページを reports/html/ に保存する（selector を決める参考）

指定したページの診断（--urls）
- 本番の User-Agent と、一般的なブラウザに近い User-Agent の2通りで取得する（--proxy なら Worker 経由も）
- 結果は reports/diagnose/ に保存する
    summary.md            … 取得ごとの HTTP ステータス・サーバー・本文の長さ・日付の書式の数・判定の手がかり
    <ページ>-<方法>.txt   … 失敗（4xx/5xx）したときのレスポンスのヘッダーと本文（先頭 8000 文字）
    <ページ>.html         … 取得できたページ（--html のとき）
- 実行した環境の接続元 IP と国も記録する（海外 IP の遮断かどうかの判断材料）

どちらも GITHUB_STEP_SUMMARY があれば、Actions の実行結果画面に要約を書き出す。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

REPORTS = build.ROOT / "reports"
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
    "Accept-Language": "ja",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# 本文にこれらの語があれば判定の手がかりとして記録する
CLUES = {
    "海外・国外からの遮断": re.compile(r"(海外|国外|日本国内から|outside (of )?japan|foreign|country|region)", re.I),
    "ボット対策・WAF": re.compile(r"(captcha|challenge|just a moment|attention required|cf-ray|cloudflare|"
                                  r"akamai|incapsula|imperva|waf|bot|robot|不正なアクセス|セキュリティ)", re.I),
    "アクセス拒否": re.compile(r"(access denied|forbidden|アクセスが拒否|閲覧できません|権限がありません)", re.I),
}
WAF_HEADERS = ("server", "cf-ray", "cf-mitigated", "x-amz-cf-id", "x-amz-cf-pop", "x-cache", "via",
               "x-akamai-transformed", "akamai-grn", "x-iinfo", "x-cdn", "x-sucuri-id", "set-cookie")


def where(a) -> str:
    """リンクの親要素を外側へ4つまで「tag#id.class」で並べる。"""
    out = []
    for p in a.parents:
        if p.name in (None, "[document]", "html", "body"):
            break
        s = p.name
        if p.get("id"):
            s += "#" + p["id"]
        if p.get("class"):
            s += "." + ".".join(p["class"])
        out.append(s)
        if len(out) == 4:
            break
    return " < ".join(out)


def write_summary(lines: list[str]) -> None:
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# --- sources.yaml の全取得元 ----------------------------------------------------

def inspect_all(save_html: bool) -> None:
    config = yaml.safe_load(build.SOURCES_FILE.read_text(encoding="utf-8")) or {}
    rows, summary = [], ["# 取得元の確認", "", "| 機関 | 取得元 | 件数 | タイトルの例 |", "|---|---|---|---|"]
    if save_html:
        (REPORTS / "html").mkdir(parents=True, exist_ok=True)
    for i, org in enumerate(config.get("organizations") or []):
        for j, src in enumerate(org.get("sources") or []):
            url = src["url"]
            try:
                items = build.collect(src)
                err = ""
            except Exception as e:
                items, err = [], f"{type(e).__name__}: {e}"[:200]
            locs = {}
            if src.get("type") == "scrape" and not err:
                resp = build.fetch(build.fetch_url(src))
                text = build.decode_html(resp.content, None)
                if save_html:
                    (REPORTS / "html" / f"{i:02d}-{j}.html").write_text(text, encoding="utf-8")
                soup = BeautifulSoup(text, "html.parser")
                for a in soup.find_all("a", href=True):
                    u = build.normalize_url(urljoin(url, a["href"].strip()))
                    locs.setdefault(u, where(a))
            for it in items:
                rows.append({"org": org["name"], "source": url, "type": src.get("type", "rss"),
                             "date": it["date"], "title": it["title"], "url": it["url"],
                             "where": locs.get(it["url"], ""), "error": ""})
            if err:
                rows.append({"org": org["name"], "source": url, "type": src.get("type", "rss"),
                             "date": "", "title": "", "url": "", "where": "", "error": err})
            ex = " / ".join(re.sub(r"[|\n]", " ", it["title"])[:30] for it in items[:3])
            summary.append(f"| {org['name']} | {url} | {len(items) if not err else '❌ ' + err} | {ex} |")
            print(f"{org['name']} {url}: {len(items)}件 {err}", file=sys.stderr)
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS / "inspect_sources.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["org", "source", "type", "date", "title", "url", "where", "error"])
        w.writeheader()
        w.writerows(rows)
    write_summary(summary)


# --- 指定したページの診断 --------------------------------------------------------

def slug(url: str) -> str:
    p = urlsplit(url)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (p.netloc + p.path).strip("/"))[:80] or "page"


def date_counts(text: str) -> str:
    plain = unicodedata.normalize("NFKC", BeautifulSoup(text, "html.parser").get_text(" "))
    counts = {f: len(p.findall(plain)) for f, p in build.DATE_PATTERNS.items()}
    return ", ".join(f"{f}:{n}" for f, n in counts.items() if n) or "日付なし"


def runner_ip() -> str:
    """実行環境の接続元 IP と国（海外 IP として遮断されているかの判断材料）。"""
    try:
        d = requests.get("https://ipinfo.io/json", timeout=10).json()
        return f"{d.get('ip', '?')}（{d.get('country', '?')} / {d.get('org', '?')}）"
    except Exception as e:
        return f"不明（{type(e).__name__}）"


def diagnose(urls: list[str], save_html: bool, use_proxy: bool) -> None:
    out = REPORTS / "diagnose"
    out.mkdir(parents=True, exist_ok=True)
    ip = runner_ip()
    lines = ["# ページの診断", "", f"実行環境の接続元: {ip}", "",
             "| ページ | 取得方法 | 結果 | サーバー | 本文 | 日付の書式 | 手がかり |", "|---|---|---|---|---|---|---|"]
    methods = [("bot", "本番のUser-Agent", {"User-Agent": build.USER_AGENT}),
               ("browser", "ブラウザ風User-Agent", BROWSER_HEADERS)]
    for url in urls:
        attempts = [(k, label, lambda h=h: requests.get(url, headers=h, timeout=build.TIMEOUT))
                    for k, label, h in methods]
        if use_proxy:
            attempts.append(("proxy", "Worker経由", lambda: requests.get(
                build.fetch_url({"url": url, "via_proxy": True}), timeout=build.TIMEOUT + 10)))
        saved_html = False
        for key, label, do in attempts:
            try:
                r = do()
            except Exception as e:
                lines.append(f"| {url} | {label} | ❌ {type(e).__name__} | | | | |")
                continue
            text = build.decode_html(r.content, None)
            server = r.headers.get("server", "")
            clues = [name for name, pat in CLUES.items() if pat.search(text[:20000])]
            if r.headers.get("cf-mitigated") or r.headers.get("cf-ray"):
                clues.append("Cloudflare のヘッダーあり")
            status = f"✅ {r.status_code}" if r.ok else f"❌ {r.status_code}"
            if r.url != url:
                status += f"（転送先 {r.url}）"
            lines.append(f"| {url} | {label} | {status} | {server} | {len(r.content)} バイト | "
                         f"{date_counts(text) if r.ok else ''} | {'、'.join(clues)} |")
            print(f"{url} [{label}] {r.status_code} {server} {len(r.content)}B", file=sys.stderr)
            if not r.ok:
                head = "\n".join(f"{k}: {v}" for k, v in r.headers.items())
                (out / f"{slug(url)}-{key}.txt").write_text(
                    f"URL: {url}\n取得方法: {label}\n接続元: {ip}\nHTTP {r.status_code} {r.reason}\n\n"
                    f"--- ヘッダー ---\n{head}\n\n--- 本文（先頭8000文字）---\n{text[:8000]}\n", encoding="utf-8")
            elif save_html and not saved_html:
                (out / f"{slug(url)}.html").write_text(text, encoding="utf-8")
                saved_html = True
    lines += ["", "失敗したときのヘッダーと本文は `reports/diagnose/*.txt`、取得できたページは "
              "`reports/diagnose/*.html` にあります。",
              "", "判定の目安: ブラウザ風だけ成功 → User-Agent で判定するボット対策 ／ "
              "どちらも 403 で本文に海外・国外の文言 → 海外 IP の遮断 ／ "
              "Cloudflare などのヘッダーや captcha・challenge の文言 → WAF のボット対策"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_summary(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--proxy", action="store_true", help="--urls のとき Worker 経由の取得も試す")
    args = ap.parse_args()
    urls = [u for u in " ".join(args.urls).split() if u.startswith(("http://", "https://"))]
    if urls:
        diagnose(urls, args.html, args.proxy)
    else:
        inspect_all(args.html)


if __name__ == "__main__":
    main()
