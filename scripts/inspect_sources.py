#!/usr/bin/env python3
"""sources.yaml の各取得元から、いま拾える記事を一覧にする（state は更新しない）。

    python scripts/inspect_sources.py [--html]

- reports/inspect_sources.csv に 機関・取得元・タイトル・URL・日付・リンクの場所（親要素の並び）を書き出す
- --html を付けると、scrape の取得元のページを reports/html/ に保存する（selector を決める参考）
- GITHUB_STEP_SUMMARY があれば、取得元ごとの件数とタイトルの例を書き出す
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

REPORTS = build.ROOT / "reports"


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    config = yaml.safe_load(build.SOURCES_FILE.read_text(encoding="utf-8")) or {}
    rows, summary = [], ["# 取得元の確認", "", "| 機関 | 取得元 | 件数 | タイトルの例 |", "|---|---|---|---|"]
    if args.html:
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
                resp = build.fetch(url)
                text = build.decode_html(resp.content, None)
                if args.html:
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
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
