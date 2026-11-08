#!/usr/bin/env python3
"""岩手県内の国の出先機関・大学の新着情報を取得し、GitHub Pages 用の HTML を生成する。

    python scripts/build.py                # 取得してページを作る
    python scripts/build.py --render-only  # 取得せず、保存済みのデータからページだけ作り直す

- sources.yaml の取得元を巡回し、記事URLを state/seen.json と照合して新着を判定
- その日の結果を state/daily/YYYY-MM-DD.json に保存（同日の再実行は追記マージ）
- docs/index.html と docs/archive/YYYY-MM-DD.html（直近30日分）を生成
- 過去30日分の記事タイトル検索用データ docs/search.json を生成
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import unicodedata
from functools import cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urldefrag, urlsplit

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup, Comment, NavigableString, Tag, UnicodeDammit

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.yaml"
STATE_DIR = ROOT / "state"
SEEN_FILE = STATE_DIR / "seen.json"
DAILY_DIR = STATE_DIR / "daily"
DOCS_DIR = ROOT / "docs"
ARCHIVE_DIR = DOCS_DIR / "archive"
SEARCH_FILE = DOCS_DIR / "search.json"

JST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (compatible; iwate-agencies-news/1.0; "
    "+https://github.com/iwate-news-watch/agencies)"
)
TIMEOUT = 20
RETRY_WAIT = 3
SITE_INTERVAL = 1
SEEN_RETENTION_DAYS = 90
ARCHIVE_DAYS = 30
SITE_NAME = "GINGA 岩手県 国の機関・大学 新着情報"
# docs/ に置くロゴのファイル名。空文字にするとロゴを表示しない
LOGO_FILE = "ginga-logo-v2.svg"
LOGO_ALT = "GINGA"


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_last_request = 0.0


def fetch(url: str) -> requests.Response:
    """URLを取得する。サイト間は1秒空け、失敗時は1回だけリトライする。"""
    global _last_request
    for attempt in range(2):
        wait = SITE_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = _session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == 1:
                raise
            time.sleep(RETRY_WAIT)
        finally:
            _last_request = time.monotonic()
    raise AssertionError("unreachable")


@cache
def proxy_base() -> str:
    """Worker（中継サーバー）のURL。環境変数 PROXY_BASE があればそれを、なければ docs/config.json の trigger_url を使う。"""
    import os
    base = os.environ.get("PROXY_BASE") or ""
    if not base:
        try:
            base = json.loads((DOCS_DIR / "config.json").read_text(encoding="utf-8")).get("trigger_url") or ""
        except (OSError, ValueError):
            base = ""
    return base.strip().rstrip("/")


def fetch_url(source: dict) -> str:
    """実際に取得するURL。via_proxy: true なら Worker の /proxy を経由する（大学側が海外IPを遮断している場合など）。"""
    url = source["url"]
    if not source.get("via_proxy"):
        return url
    base = proxy_base()
    if not base:
        raise ValueError("via_proxy には docs/config.json の trigger_url（Worker のURL）の設定が必要です")
    return f"{base}/proxy?url={quote(url, safe='')}"


def normalize_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def parse_feed(content: bytes, base_url: str) -> list[dict]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"フィードを解析できません: {feed.get('bozo_exception')}")
    items = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        day = ""
        if stamp:
            dt = datetime(*stamp[:6], tzinfo=timezone.utc).astimezone(JST)
            day = dt.date().isoformat()
        title = " ".join((entry.get("title") or "").split()) or link
        items.append({"title": title, "url": normalize_url(urljoin(base_url, link)), "date": day})
    return items


# --- スクレイピング --------------------------------------------------------

DATE_PATTERNS = {
    # 2026.10.15
    "dotted": re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})"),
    # 2026/10/16
    "slash": re.compile(r"(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})"),
    # 2026年11月5日 / 2026年 11月 5日
    "kanji": re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    # 令和8年 10月15日 / 令和 8年10月 15日 / 令和元年...
    "reiwa": re.compile(r"令和\s*(\d{1,2}|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    # R8.11.6 / R08.11.06 / R8/11/6（令和の略記）
    "reiwa_short": re.compile(r"(?<![A-Za-z])R\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{1,2})(?!\d)"),
    # 11月4日（年なし。年は取得日から推定する。タイトル中の日付と区別するため date_position: after と組み合わせる）
    "monthday": re.compile(r"(?<!\d)()(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
}


def to_iso_date(fmt: str, m: re.Match) -> str:
    """日付パターンのマッチを YYYY-MM-DD にする。読めなければ空文字。"""
    try:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if fmt == "reiwa":
            year = 2018 + (1 if y == "元" else int(y))
        elif fmt == "reiwa_short":
            year = 2018 + int(y)
        elif fmt == "monthday":
            # 年の書かれていない日付は、取得日から見て未来になりすぎない年にする（12月に1月の日付を見たら前年…ではなく
            # 1月に12月の日付を見たら前年）
            today = datetime.now(JST).date()
            year = today.year
            if date(year, mo, d) > today + timedelta(days=31):
                year -= 1
        else:
            year = int(y)
        return date(year, mo, d).isoformat()
    except ValueError:
        return ""


def _usable_link(a: Tag) -> str | None:
    href = (a.get("href") or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    return href


def decode_html(content: bytes, http_charset: str | None = None) -> str:
    """HTTPヘッダ → metaタグ → UTF-8/Shift_JIS/EUC-JP の順で文字コードを判定する。"""
    dammit = UnicodeDammit(content, known_definite_encodings=[http_charset] if http_charset else [],
                           user_encodings=["utf-8", "cp932", "euc-jp"])
    return dammit.unicode_markup or content.decode("utf-8", "replace")


TITLE_MAX = 120
_TRAILING_NEW = re.compile(r"\s*(NEW|New|new|新着)!?$")


def clean_title(text: str, pattern: re.Pattern) -> str:
    """日付と末尾の「NEW」などの印を除き、空白をまとめる。"""
    title = " ".join(pattern.sub("", text).split())
    return _TRAILING_NEW.sub("", title).strip()


def scrape_dated_links(content: bytes | str, base_url: str, date_format: str,
                       selector: str | None = None, date_position: str = "before",
                       title_from: str = "link") -> list[dict]:
    """ページ内の日付とリンクを組にして記事とする。

    - date_position: before … 日付の直後に出てくる最初のリンクを記事とする（既定）
                     after  … リンクの直後に出てくる日付をそのリンクの日付とする（日付がタイトルの後ろにあるサイト）
    - title_from: link … リンクの文字をタイトルにする（既定）
                  text … 日付から次の日付までの文章をタイトルにし、その中の最初のリンクを記事のURLにする
                         （「詳細はこちら」のように本文中にリンクがあるサイト）。リンクがなければ取得元のページを指す
    - selector を指定すると、その範囲ごとに走査する（範囲をまたいで日付とリンクを組にしない）
    日付が実在しない値などで読めなくても、記事は日付空欄で拾う。
    """
    pattern = DATE_PATTERNS[date_format]
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()  # HTMLのコメント（取り下げた記事が残っていることがある）は読まない
    roots = soup.select(selector) if selector else [soup]

    items: list[dict] = []
    seen: set[str] = set()

    def add_item(url: str, title: str, day: str) -> None:
        if url in seen:
            return
        seen.add(url)
        if len(title) > TITLE_MAX:
            title = title[:TITLE_MAX - 1] + "…"
        items.append({"title": title or url, "url": url, "date": day})

    def add(a: Tag, day: str) -> None:
        href = _usable_link(a)
        if not href:
            return
        text = unicodedata.normalize("NFKC", a.get_text(" ", strip=True))
        add_item(normalize_url(urljoin(base_url, href)), clean_title(text, pattern), day)

    def dates_in(node: NavigableString) -> list[re.Match]:
        return list(pattern.finditer(unicodedata.normalize("NFKC", str(node))))

    for root in roots:
        if title_from == "text":
            current: dict | None = None  # {"day", "parts", "link"}

            def flush() -> None:
                if not current:
                    return
                title = clean_title("".join(current["parts"]), pattern)
                if current["link"]:
                    url = current["link"]
                else:  # リンクのない記事は取得元のページを指す（URLの重複を避けるため印を付ける）
                    key = hashlib.sha1(f"{current['day']} {title}".encode()).hexdigest()[:10]
                    url = f"{base_url}#{key}"
                if title:
                    add_item(url, title, current["day"])

            for node in root.descendants:
                if isinstance(node, NavigableString):
                    matches = dates_in(node)
                    if matches:
                        flush()
                        current = {"day": to_iso_date(date_format, matches[-1]), "parts": [], "link": None}
                        rest = unicodedata.normalize("NFKC", str(node))[matches[-1].end():]
                        if rest.strip():
                            current["parts"].append(rest)
                    elif current is not None:
                        current["parts"].append(unicodedata.normalize("NFKC", str(node)))
                elif isinstance(node, Tag) and node.name == "a" and current is not None and not current["link"]:
                    href = _usable_link(node)
                    if href:
                        current["link"] = normalize_url(urljoin(base_url, href))
            flush()
            continue

        if date_position == "after":
            last_a: Tag | None = None  # 直前に見つけたリンク（日付未割り当て）
            for node in root.descendants:
                if isinstance(node, Tag) and node.name == "a" and _usable_link(node):
                    if last_a is not None:
                        add(last_a, "")  # 日付が見つからないまま次のリンクが来た
                    last_a = node
                elif isinstance(node, NavigableString) and last_a is not None:
                    if node.find_parent("a") is last_a:
                        continue
                    matches = dates_in(node)
                    if matches:
                        add(last_a, to_iso_date(date_format, matches[0]))
                        last_a = None
            if last_a is not None:
                add(last_a, "")
            continue

        pending: str | None = None  # 直前に見つけた日付（未使用）
        for node in root.descendants:
            if isinstance(node, NavigableString):
                matches = dates_in(node)
                if not matches:
                    continue
                day = to_iso_date(date_format, matches[-1])
                parent_a = node.find_parent("a")
                if parent_a is not None and _usable_link(parent_a):
                    # <a><span>2026.10.15</span>タイトル</a> のように日付がリンク内にある場合
                    add(parent_a, day)
                    pending = None
                else:
                    pending = day
            elif isinstance(node, Tag) and node.name == "a" and pending is not None:
                if _usable_link(node):
                    add(node, pending)
                    pending = None
    return items


def keyword_filter(items: list[dict], keywords) -> list[dict]:
    """include_keywords のどれかをタイトルに含む記事だけを残す（全角半角・大文字小文字は区別しない）。"""
    if not keywords:
        return items
    if isinstance(keywords, str):
        keywords = [keywords]
    words = [unicodedata.normalize("NFKC", str(k)).lower() for k in keywords if str(k).strip()]
    return [i for i in items
            if any(w in unicodedata.normalize("NFKC", i["title"]).lower() for w in words)]


def collect(source: dict) -> list[dict]:
    """取得元から記事を集める。include_keywords があれば、タイトルにどれかを含む記事だけを返す。"""
    return keyword_filter(_collect(source), source.get("include_keywords"))


def _collect(source: dict) -> list[dict]:
    url = source["url"]
    resp = fetch(fetch_url(source))
    kind = source.get("type", "rss")
    if kind == "rss":
        return parse_feed(resp.content, url)
    if kind == "scrape":
        charset = requests.utils.get_encoding_from_headers(resp.headers)
        if charset == "ISO-8859-1":  # requests の text/* 既定値。宣言なしとみなす
            charset = None
        fmt = source.get("date_format", "dotted")
        if fmt not in DATE_PATTERNS:
            raise ValueError(f"不明な date_format: {fmt}（{', '.join(DATE_PATTERNS)} のいずれか）")
        position = source.get("date_position", "before")
        title_from = source.get("title_from", "link")
        if position not in ("before", "after") or title_from not in ("link", "text"):
            raise ValueError("date_position は before/after、title_from は link/text のいずれか")
        return scrape_dated_links(decode_html(resp.content, charset), url, fmt, source.get("selector"),
                                  position, title_from)
    raise ValueError(f"不明な type: {kind}")


# ---------------------------------------------------------------------------
# 状態
# ---------------------------------------------------------------------------

def load_json(path: Path, default):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def load_seen() -> dict:
    seen = load_json(SEEN_FILE, {})
    # articles: 記事URL -> 最後に見かけた日 / sources: 取得元URL -> 初回取得日
    seen.setdefault("articles", {})
    seen.setdefault("sources", {})
    return seen


def prune_seen(seen: dict, today: date) -> None:
    cutoff = (today - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    seen["articles"] = {u: d for u, d in seen["articles"].items() if d >= cutoff}


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------

def title_key(title: str) -> str:
    """タイトルの重複判定用の鍵（全角半角・大文字小文字・空白の有無を無視）。"""
    return "".join(unicodedata.normalize("NFKC", title or "").lower().split())


def run(now: datetime) -> dict:
    config = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    seen = load_seen()
    first_run = not seen["sources"]
    today = now.date().isoformat()
    results = []

    for muni in config.get("organizations") or []:
        name = muni["name"]
        sources = muni.get("sources") or []
        result = {"name": name, "status": "ok", "errors": [], "new": [], "record_only": False}
        if muni.get("preparing"):  # 準備中。取得せず、ページ下部にホームページへのリンクだけ出す
            result["status"] = "preparing"
            results.append(result)
            continue
        if not sources:
            result["status"] = "unconfigured"
            results.append(result)
            continue

        items: dict[str, dict] = {}
        fresh_sources = []
        for source in sources:
            url = source["url"]
            try:
                fetched = collect(source)
            except Exception as e:  # 1つの失敗で全体を止めない
                print(f"[ERROR] {name} {url}: {e}", file=sys.stderr)
                result["errors"].append(f"{url}: {type(e).__name__}: {e}"[:300])
                continue
            print(f"[OK] {name} {url}: {len(fetched)}件", file=sys.stderr)
            is_fresh = url not in seen["sources"]
            if is_fresh:
                fresh_sources.append(url)
            for item in fetched:
                # 同じ機関の複数フィードはURLで重複を除く
                existing = items.get(item["url"])
                if existing is None:
                    items[item["url"]] = {**item, "_record_only": is_fresh}
                elif not is_fresh:
                    existing["_record_only"] = False
                    existing["date"] = existing["date"] or item["date"]

        if result["errors"]:
            result["status"] = "error"
        for url in fresh_sources:
            seen["sources"][url] = today
        result["record_only"] = bool(fresh_sources)

        titles: set[str] = set()  # 同じ機関で同じタイトルの記事は、先に見つけたほうだけ載せる
        for url, item in items.items():
            record_only = item.pop("_record_only")
            if url not in seen["articles"] and not record_only:
                key = title_key(item["title"])
                if key not in titles:
                    titles.add(key)
                    result["new"].append(item)
            seen["articles"][url] = today
        result["new"].sort(key=lambda i: i["date"], reverse=True)
        results.append(result)

    prune_seen(seen, now.date())
    save_json(SEEN_FILE, seen)
    return {"fetched_at": now.strftime("%H:%M"), "first_run": first_run, "organizations": results}


def empty_day(day: str) -> dict:
    return {"date": day, "last_fetched": "", "first_run": False, "organizations": []}


def load_daily(path: Path, day: str) -> dict:
    """その日の一覧を読む。以前の形式（実行ごとに分かれたもの）は1つの一覧にまとめ直す。"""
    data = load_json(path, None)
    if not data:
        return empty_day(day)
    if "runs" in data:  # 実行ごとに区切っていた形式
        merged = empty_day(data["date"])
        for r in sorted(data["runs"], key=lambda r: r.get("updated_at", "")):
            add_fetch(merged, {"fetched_at": r.get("updated_at", ""), "first_run": r.get("first_run", False),
                               "organizations": r["organizations"]})
        return merged
    if "last_fetched" not in data:  # 1日1回だった頃の形式
        merged = empty_day(data["date"])
        add_fetch(merged, {"fetched_at": data.get("updated_at", ""), "first_run": data.get("first_run", False),
                           "organizations": data["organizations"]})
        return merged
    return data


def add_fetch(daily: dict, fetch_result: dict) -> dict:
    """今回の取得で増えた記事を、その日の一覧に機関ごとに追加する。

    新しく取得したものほど上に並ぶ。取得エラー・初回記録のみの表示は今回の取得結果に合わせる。
    各記事には見つけた取得の時刻（fetched_at）を付け、最新の取得分を区別できるようにする。
    """
    prev_by_name = {m["name"]: m for m in daily["organizations"]}
    merged = []
    for muni in fetch_result["organizations"]:
        prev = prev_by_name.pop(muni["name"], None)
        items = [{**i, "fetched_at": fetch_result["fetched_at"]} for i in muni["new"]]
        if prev:
            # その日の一覧にすでに同じタイトルの記事があれば、先に見つけたほう（一覧にあるほう）を残す
            prev_titles = {title_key(i["title"]) for i in prev["new"]}
            items = [i for i in items if title_key(i["title"]) not in prev_titles]
            urls = {i["url"] for i in items}
            items += [i for i in prev["new"] if i["url"] not in urls]
        merged.append({**muni, "new": items})
    # sources.yaml から外れた機関も、その日にすでに載せた記事は残す
    merged += [m for m in prev_by_name.values() if m["new"]]
    daily["organizations"] = merged
    daily["last_fetched"] = fetch_result["fetched_at"]
    daily["first_run"] = daily.get("first_run", False) or fetch_result["first_run"]
    return daily


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;
--accent:#0a6bc2;--err-bg:#fdecec;--err-fg:#b3261e;--err-line:#f2b8b5;--chip:#eef4fb}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--card:#1c1c1f;--fg:#ececee;
--muted:#9a9aa2;--line:#2e2e33;--accent:#6cb4ff;--err-bg:#3a1416;--err-fg:#ffb4ab;
--err-line:#7a2a2a;--chip:#1f2a38}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
-webkit-text-size-adjust:100%}
main{max-width:760px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.35rem;line-height:1.4;margin:0 0 4px}
.sub{color:var(--muted);font-size:.85rem;margin:0 0 20px}
h1{font-size:1.25rem}
.site{font-size:.85rem;color:var(--muted);margin:0 0 6px}
.daynav{display:flex;justify-content:space-between;gap:8px;margin:0 0 16px;font-size:.88rem}
.daynav a{display:inline-block;padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.daynav .next{margin-left:auto}
.card h3{font-size:1.05rem;margin:0 0 8px;display:flex;align-items:center;gap:8px;color:inherit}
.count{font-size:.75rem;font-weight:600;background:var(--chip);color:var(--accent);
padding:1px 8px;border-radius:999px}
section.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:0 0 12px}
section.err{background:var(--err-bg);border-color:var(--err-line)}
section.err h3,.err .msg{color:var(--err-fg)}
ul.items{list-style:none;margin:0;padding:0}
ul.items li{padding:8px 0;border-top:1px solid var(--line)}
ul.items li:first-child{border-top:0;padding-top:0}
.date{display:block;color:var(--muted);font-size:.78rem}
a{color:var(--accent);text-decoration:none;word-break:break-word}
a:hover{text-decoration:underline}
.msg{margin:0;font-size:.9rem;color:var(--muted)}
.errlist{margin:6px 0 0;padding-left:18px;font-size:.78rem;word-break:break-all}
.latest{border:2px solid var(--accent);border-radius:14px;padding:12px 12px 2px;margin:0 0 24px}
.latest .card{margin-bottom:10px}
.latest .msg{margin:0 4px 12px}
h2{font-size:1.05rem;margin:0 0 10px}
h2 .meta{margin-left:8px;font-size:.8rem;font-weight:400;color:var(--muted)}
.latest h2{margin:0 4px 10px}
.notice{background:var(--chip);border-radius:12px;padding:12px 16px;margin:0 0 16px}
h4{font-size:.95rem;margin:20px 0 6px;color:var(--muted)}
h3.foot{font-size:.95rem;margin:36px 0 8px;color:var(--muted)}
.names{margin:0;font-size:.9rem;color:var(--muted)}
.archive{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:0}
.archive a{display:inline-block;padding:4px 10px;border:1px solid var(--line);
border-radius:8px;background:var(--card);font-size:.85rem}
footer{margin-top:32px;font-size:.78rem;color:var(--muted)}
.bar{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 20px}
.bar p{margin:0;font-size:.9rem}
.bar .state{color:var(--muted);font-size:.85rem}
.bar .state.busy{color:var(--accent)}
.bar .state.fail{color:var(--err-fg)}
.bar button{margin-top:10px;font:inherit;font-weight:600;padding:8px 18px;border-radius:999px;
border:0;background:var(--accent);color:var(--bg);cursor:pointer}
.bar button:disabled{opacity:.5;cursor:default}
.bar .rmsg{margin-top:8px;font-size:.88rem}
.bar .rmsg:empty{display:none}
[hidden]{display:none!important}
.layout{max-width:760px;margin:0 auto}
.ptoggle{font:inherit;font-size:.9rem;font-weight:600;padding:7px 16px;margin:0 0 16px;border-radius:999px;
border:1px solid var(--line);background:var(--card);color:var(--accent);cursor:pointer}
.panel{position:fixed;top:0;left:0;bottom:0;z-index:20;width:min(320px,86vw);overflow-y:auto;
background:var(--card);border-right:1px solid var(--line);padding:16px 16px 32px;
transform:translateX(-105%);transition:transform .2s;visibility:hidden}
.panel-open .panel{transform:none;visibility:visible}
.panel:focus{outline:none}
.backdrop{position:fixed;inset:0;z-index:15;background:rgba(0,0,0,.4)}
.phead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 8px}
.phead h2{margin:0;font-size:1rem}
.pclose,.pbtns button{font:inherit;font-size:.78rem;padding:3px 10px;border-radius:8px;
border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.panel fieldset{border:0;margin:0 0 12px;padding:0}
.panel legend,.plabel{font-size:.82rem;font-weight:600;color:var(--muted);padding:0;margin:0 0 4px}
.psort{border-bottom:1px solid var(--line)!important;padding-bottom:10px!important}
.panel label{display:flex;align-items:center;gap:6px;font-size:.9rem;padding:3px 0;cursor:pointer}
.panel input[type=checkbox],.panel input[type=radio]{margin:0;accent-color:var(--accent);width:1.05em;height:1.05em}
.pregion legend{color:var(--fg)}
.pbtns{display:flex;gap:6px;margin:0 0 4px}
.fmsg{margin:0 4px 12px}
.card h3 a.mlink{color:inherit}
.card h3 a.mlink::after{content:"↗";margin-left:3px;font-size:.75em;font-weight:400;color:var(--muted)}
.card h3 a.mlink:hover{color:var(--accent)}
.pbtns button{white-space:nowrap}
.pall{margin:0 0 12px;padding:0 0 10px;border-bottom:1px dashed var(--line)}
.pall button{font-weight:600}
.psearch{margin:0 0 12px;padding:0 0 10px;border-bottom:1px solid var(--line)}
.qbox{position:relative}
.qbox input{width:100%;font:inherit;font-size:1rem;padding:7px 34px 7px 10px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg)}
.qbox input:focus{outline:2px solid var(--accent);outline-offset:-1px}
.qbox input::-webkit-search-cancel-button{display:none}
#q-clear{position:absolute;right:4px;top:50%;transform:translateY(-50%);width:28px;height:28px;border:0;
border-radius:50%;background:transparent;color:var(--muted);font-size:1.1rem;line-height:1;cursor:pointer}
#q-clear:hover{background:var(--line)}
.panel label.qall{font-size:.85rem;margin-top:6px}
.qcount{margin:4px 0 0;font-size:.85rem;font-weight:600;color:var(--accent)}
.qcount:empty{display:none}
mark{background:#ffe58a;color:inherit;border-radius:2px;padding:0 1px}
@media (prefers-color-scheme:dark){mark{background:#7a5d00}}
ul.items li.first{border-top:0;padding-top:0}
.sresults{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:0 0 16px}
.sresults .date a{color:inherit}
.masthead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 4px}
.masthead .mtext{min-width:0}
.masthead h1{margin:0}
.logo-sm{flex:none;display:block;width:auto;height:auto;max-height:44px;max-width:96px}
.logo-side{display:none}
@media (min-width:1400px){
.logo-sm{display:none}
.logo-side{--gutter:calc((100vw - 1060px) / 2);--w:min(180px,calc(var(--gutter) - 48px));
display:block;position:fixed;top:24px;right:calc((var(--gutter) - var(--w)) / 2);
width:var(--w);height:auto;max-height:calc(100vh - 48px);object-fit:contain}
}
@media (min-width:1000px){
.has-panel .layout{max-width:1060px;display:grid;grid-template-columns:240px minmax(0,1fr);gap:8px;align-items:start}
.has-panel .panel{position:sticky;top:0;bottom:auto;width:auto;max-height:100vh;transform:none;visibility:visible;
z-index:auto;border:0;border-right:1px solid var(--line);background:transparent;padding:20px 16px 24px}
.ptoggle,.pclose,.backdrop{display:none!important}
}
"""


# 並び替え・絞り込みパネル用の分類（並び順＝分類順）と読み（五十音順用）。
# sources.yaml に機関を追加したら、ここにも分類と読みを追加する（ない機関は「その他」に入る）
CATEGORIES = [
    ("国の機関", [
        ("盛岡地方気象台", "もりおかちほうきしょうだい"),
        ("岩手労働局", "いわてろうどうきょく"),
        ("岩手河川国道事務所", "いわてかせんこくどうじむしょ"),
        ("三陸国道事務所", "さんりくこくどうじむしょ"),
        ("南三陸沿岸国道事務所", "みなみさんりくえんがんこくどうじむしょ"),
        ("北上川ダム統合管理事務所", "きたかみがわだむとうごうかんりじむしょ"),
        ("盛岡財務事務所", "もりおかざいむじむしょ"),
        ("日本銀行盛岡事務所", "にっぽんぎんこうもりおかじむしょ"),
        ("東北農政局（東北6県）", "とうほくのうせいきょく"),
    ]),
    ("大学・研究機関", [
        ("岩手大学", "いわてだいがく"),
        ("岩手県立大学", "いわてけんりつだいがく"),
        ("岩手医科大学", "いわていかだいがく"),
        ("盛岡大学", "もりおかだいがく"),
        ("いわて富士大学", "いわてふじだいがく"),
        ("国立天文台 水沢VLBI観測所", "こくりつてんもんだい みずさわぶいえるびーあいかんそくじょ"),
        ("東京大学 国際沿岸海洋研究センター", "とうきょうだいがく こくさいえんがんかいようけんきゅうせんたー"),
    ]),
]
OTHER_REGION = "その他"
MUNI_INFO = {name: (region, order, kana)
             for order, (region, name, kana) in enumerate(
                 (r, n, k) for r, ms in CATEGORIES for n, k in ms)}


def muni_info(name: str) -> tuple[str, int, str]:
    """(分類, 分類順の順位, 読み)。分類にない機関は「その他」として最後に並べる。"""
    return MUNI_INFO.get(name, (OTHER_REGION, len(MUNI_INFO), name))


@cache
def configured_names() -> list[str]:
    """sources.yaml に載っている機関名。"""
    config = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    return [o["name"] for o in config.get("organizations") or []]


@cache
def preparing_names() -> list[str]:
    """sources.yaml で preparing: true の機関名（パネルには並べない）。"""
    config = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    return [o["name"] for o in config.get("organizations") or [] if o.get("preparing")]


@cache
def homepages() -> dict[str, str]:
    """機関名 → 公式ホームページのURL。

    sources.yaml の homepage を優先し、なければ最初の取得元URLのドメインのトップ（https://ドメイン/）。
    """
    config = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    out = {}
    for muni in config.get("organizations") or []:
        url = str(muni.get("homepage") or "").strip()
        if not url:
            for source in muni.get("sources") or []:
                host = urlsplit(source.get("url", "")).netloc
                if host:
                    url = f"https://{host}/"
                    break
        if url.startswith(("https://", "http://")):
            out[muni["name"]] = url
    return out


def muni_link(name: str) -> str:
    """機関名。ホームページがわかればそこへのリンク（別タブ）にする。"""
    url = homepages().get(name)
    if not url:
        return esc(name)
    return (f'<a class="mlink" href="{esc(url)}" target="_blank" rel="noopener" '
            f'title="{esc(name)}の公式ホームページ（別タブで開きます）">{esc(name)}</a>')


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def jp_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def render_items(items: list[dict]) -> str:
    rows = []
    for i in items:
        day = f'<span class="date">{esc(jp_date(i["date"]))}</span>' if i["date"] else ""
        rows.append(f'<li>{day}<a href="{esc(i["url"])}" target="_blank" '
                    f'rel="noopener">{esc(i["title"])}</a></li>')
    return '<ul class="items">' + "".join(rows) + "</ul>"


def is_latest(item: dict, day: dict) -> bool:
    return bool(day.get("last_fetched")) and item.get("fetched_at") == day["last_fetched"]


def card_attrs(name: str, count: int) -> str:
    region, order, kana = muni_info(name)
    return (f'data-muni="{esc(name)}" data-region="{esc(region)}" data-order="{order}" '
            f'data-kana="{esc(kana)}" data-count="{count}"')


def render_mlist(cards: list[str], empty_msg: bool = True) -> str:
    """並び替え・絞り込みの対象になるカードのまとまり。絞り込みで全部隠れたときの案内を添える。"""
    if not cards:
        return ""
    out = '<div class="mlist">' + "\n".join(cards) + "</div>"
    if empty_msg:
        out += '<p class="msg fmsg" hidden>選択中の機関の記事はありません</p>'
    return out


def by_region(munis: list[dict]) -> list[dict]:
    return sorted(munis, key=lambda m: muni_info(m["name"])[1])


def render_muni_cards(munis: list[dict]) -> list[str]:
    return [f'<section class="card" {card_attrs(m["name"], len(m["new"]))}><h3>{muni_link(m["name"])}'
            f'<span class="count">{len(m["new"])}件</span></h3>'
            f'{render_items(m["new"])}</section>' for m in by_region(munis) if m["new"]]


def render_latest(day: dict) -> str:
    """直近1回の取得で新しく見つかった記事を機関ごとにまとめた枠。"""
    munis = [{**m, "new": [i for i in m["new"] if is_latest(i, day)]} for m in day["organizations"]]
    count = sum(len(m["new"]) for m in munis)
    parts = ['<div class="latest">',
             f'<h2>最新の取得で増えた記事<span class="meta">{esc(day.get("last_fetched", ""))} 取得 ・ '
             f'{count}件<span class="shown"></span></span></h2>']
    if count:
        parts.append(render_mlist(render_muni_cards(munis)))
    else:
        parts.append('<p class="msg">前回から新しい記事はありません</p>')
    parts.append("</div>")
    return "\n".join(parts)


def render_day(day: dict, split_latest: bool = False) -> str:
    """その日の一覧。split_latest なら最新の取得分を先頭の枠に分け、残りを下に並べる。"""
    munis = day["organizations"]
    errors = [m for m in munis if m["status"] == "error"]
    with_new = [m for m in munis if m["new"] and m["status"] != "error"]
    record_only = [m for m in munis if m["record_only"] and not m["new"] and m["status"] != "error"]
    no_update = [m for m in munis if m["status"] == "ok" and not m["new"] and not m["record_only"]]
    unconfigured = [m for m in munis if m["status"] == "unconfigured"]
    preparing = [m for m in munis if m["status"] == "preparing"]

    body = []
    if day.get("first_run") and not any(m["new"] for m in munis):
        body.append('<p class="notice">初回の取得は記録のみ行いました。次回の取得から増えた記事を表示します。</p>')
    elif split_latest:
        body.append(render_latest(day))

    def rest(m: dict) -> list[dict]:
        return [i for i in m["new"] if not is_latest(i, day)] if split_latest else m["new"]

    # 取得エラーは目立つように先頭へ
    err_cards = []
    for m in by_region(errors):
        parts = [f'<section class="card err" {card_attrs(m["name"], len(rest(m)))}><h3>⚠ {muni_link(m["name"])} — 取得エラー</h3>']
        parts.append('<p class="msg">最新の取得で、一部または全部の取得元から取得できませんでした。</p>')
        parts.append('<ul class="errlist">' + "".join(f"<li>{esc(e)}</li>" for e in m["errors"]) + "</ul>")
        if rest(m):
            parts.append(render_items(rest(m)))
        parts.append("</section>")
        err_cards.append("".join(parts))
    body.append(render_mlist(err_cards, empty_msg=False))

    others = render_muni_cards([{**m, "new": rest(m)} for m in with_new])
    if split_latest and others:
        body.append("<h2>今日のそのほかの記事</h2>")
    body.append(render_mlist(others))

    for label, group in (("初回のため記録のみ", record_only), ("更新なし", no_update),
                         ("取得元未設定", unconfigured), ("準備中", preparing)):
        if group:
            group = by_region(group)
            body.append(f"<h4>{label}</h4>")
            body.append(f'<p class="names">{"、".join(muni_link(m["name"]) for m in group)}</p>')
    return "\n".join(body)


def render_panel(day: dict, prefix: str) -> str:
    """記事検索と機関の並び替え・絞り込みのパネル。JavaScript が使えるときだけ表示する。"""
    # 分類ごとにまとめる。sources.yaml に載っている機関と、その日の一覧にある機関だけを並べる
    present = (set(configured_names()) | {m["name"] for m in day["organizations"]
                                          if m["status"] != "preparing"}) - set(preparing_names())
    groups = [(r, [n for n, _ in ms if n in present]) for r, ms in CATEGORIES]
    groups = [(r, names) for r, names in groups if names]
    extra = sorted(present - set(MUNI_INFO))
    if extra:
        groups.append((OTHER_REGION, extra))
    sorts = (("region", "分類順"), ("count", "新着件数順"), ("kana", "五十音順"))
    parts = [f'<aside class="panel" id="panel" aria-label="検索・並び替え・絞り込み" data-base="{esc(prefix)}" hidden>',
             '<div class="phead"><h2>検索・並び替え・絞り込み</h2>'
             '<button type="button" class="pclose" id="panel-close">閉じる</button></div>',
             '<div class="psearch" role="search">'
             '<label class="plabel" for="q">記事タイトルを検索</label>'
             '<div class="qbox"><input type="search" id="q" autocomplete="off" enterkeyhint="search" '
             'placeholder="例：入札 募集">'
             '<button type="button" id="q-clear" aria-label="検索語を消す" hidden>×</button></div>'
             '<label class="qall"><input type="checkbox" id="q-all"> 過去30日分も検索</label>'
             '<p class="qcount" id="q-count" role="status" aria-live="polite"></p></div>',
             '<fieldset class="psort"><legend>並び替え</legend>']
    parts += [f'<label><input type="radio" name="sort" value="{v}"{" checked" if v == "region" else ""}> {t}</label>'
              for v, t in sorts]
    parts.append('</fieldset><div class="pfilter"><p class="plabel">絞り込み</p>'
                 '<div class="pbtns pall" role="group" aria-label="全機関">'
                 '<button type="button" data-act="on">すべて選択</button>'
                 '<button type="button" data-act="off">すべて解除</button></div>')
    for region, names in groups:
        parts.append(f'<fieldset class="pregion" data-region="{esc(region)}"><legend>{esc(region)}</legend>'
                     '<div class="pbtns"><button type="button" data-act="on">すべて選択</button>'
                     '<button type="button" data-act="off">すべて解除</button></div>')
        for n in names:
            _, order, kana = muni_info(n)
            parts.append(f'<label><input type="checkbox" name="muni" value="{esc(n)}" '
                         f'data-order="{order}" data-kana="{esc(kana)}" checked> {esc(n)}</label>')
        parts.append("</fieldset>")
    parts.append('</div></aside><div class="backdrop" id="panel-backdrop" hidden></div>')
    return "".join(parts)


# 記事検索と並び替え・絞り込み。並び替え・絞り込みの設定は localStorage に保存（使えない環境では保存せずに動く）
PANEL_JS = """
(function () {
  var KEY = "iwate-agencies-panel";  // 同じ github.io の別サイトと設定が混ざらないよう固有の名前にする
  var LIMIT = 200;
  var panel = document.getElementById("panel");
  var toggle = document.getElementById("panel-toggle");
  var backdrop = document.getElementById("panel-backdrop");
  if (!panel || !toggle) return;
  var q = document.getElementById("q");
  var qClear = document.getElementById("q-clear");
  var qAll = document.getElementById("q-all");
  var qCount = document.getElementById("q-count");
  var dayView = document.getElementById("day-view");
  var results = document.getElementById("search-results");
  var base = panel.getAttribute("data-base") || "";
  var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };
  var boxes = Array.prototype.slice.call(panel.querySelectorAll('input[name="muni"]'));
  var radios = Array.prototype.slice.call(panel.querySelectorAll('input[name="sort"]'));
  var muniMeta = {};
  boxes.forEach(function (b) { muniMeta[b.value] = {order: Number(b.dataset.order), kana: b.dataset.kana}; });

  // 保存するのは並び替えと機関の絞り込みだけ（検索語は保存しない）
  var state = {sort: "region", off: []};
  try {
    var saved = JSON.parse(window.localStorage.getItem(KEY) || "null");
    if (saved && typeof saved === "object") {
      if (["region", "count", "kana"].indexOf(saved.sort) >= 0) state.sort = saved.sort;
      if (Array.isArray(saved.off)) state.off = saved.off.filter(function (x) { return typeof x === "string"; });
    }
  } catch (e) {}
  function save() {
    try { window.localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  }

  // 全角半角・大文字小文字を同一視する。元の文字位置への対応表も作り、ハイライトに使う
  function norm(s) {
    var text = "", map = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charAt(i);
      var code = s.charCodeAt(i);
      if (code >= 0xD800 && code <= 0xDBFF && i + 1 < s.length) c += s.charAt(i + 1);
      var n = c.normalize("NFKC").toLowerCase();
      if (/^[\\u3099\\u309a]/.test(n) && map.length) {  // 半角の濁点・半濁点は前の文字と合成
        var last = text.charAt(text.length - 1), merged = (last + n).normalize("NFC");
        if (merged.length === 1) {
          text = text.slice(0, -1) + merged;
          map[map.length - 1][1] = i + c.length;
          i += c.length - 1;
          continue;
        }
      }
      for (var k = 0; k < n.length; k++) map.push([i, i + c.length]);
      text += n;
      i += c.length - 1;
    }
    return {text: text, map: map};
  }
  function terms() {
    return norm(q.value).text.split(/\\s+/).filter(Boolean);
  }
  // すべての語を含めば一致。一致した元の文字範囲を返す（不一致は null）
  function match(n, ts) {
    var ranges = [];
    for (var j = 0; j < ts.length; j++) {
      var t = ts[j], at = n.text.indexOf(t);
      if (at < 0) return null;
      while (at >= 0) {
        ranges.push([n.map[at][0], n.map[at + t.length - 1][1]]);
        at = n.text.indexOf(t, at + t.length);
      }
    }
    ranges.sort(function (a, b) { return a[0] - b[0]; });
    var out = [];
    ranges.forEach(function (r) {
      var prev = out[out.length - 1];
      if (prev && r[0] <= prev[1]) prev[1] = Math.max(prev[1], r[1]);
      else out.push([r[0], r[1]]);
    });
    return out;
  }
  function highlight(el, title, ranges) {
    el.textContent = "";
    var pos = 0;
    ranges.forEach(function (r) {
      if (r[0] > pos) el.appendChild(document.createTextNode(title.slice(pos, r[0])));
      var m = document.createElement("mark");
      m.textContent = title.slice(r[0], r[1]);
      el.appendChild(m);
      pos = r[1];
    });
    if (pos < title.length) el.appendChild(document.createTextNode(title.slice(pos)));
  }

  // このページの記事
  var cards = [];
  each(document.querySelectorAll(".mlist .card"), function (card) {
    var items = [];
    each(card.querySelectorAll("ul.items li"), function (li) {
      var a = li.querySelector("a");
      if (a) items.push({li: li, a: a, title: a.textContent, n: norm(a.textContent), marked: false});
    });
    cards.push({el: card, items: items, badge: card.querySelector(".count")});
  });

  // 過去30日分（search.json）は必要になったときに1回だけ読み込む
  var arch = null, archState = "idle";
  function loadArchive() {
    if (archState !== "idle") return;
    archState = "loading";
    fetch(base + "search.json", {cache: "no-cache"}).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (data) {
      arch = (data.items || []).map(function (e) { return {d: e.d, m: e.m, t: e.t, u: e.u, n: norm(e.t)}; });
      archState = "ok";
      apply();
    }).catch(function () { archState = "error"; apply(); });
  }

  function muniCmp(a, b) {
    var x = muniMeta[a] || {order: 9999, kana: a}, y = muniMeta[b] || {order: 9999, kana: b};
    if (state.sort === "kana") return x.kana.localeCompare(y.kana, "ja") || x.order - y.order;
    return x.order - y.order;
  }
  function cardCmp(a, b) {
    var d = 0;
    if (state.sort === "count") d = Number(b.dataset.count) - Number(a.dataset.count);
    else if (state.sort === "kana") d = a.dataset.kana.localeCompare(b.dataset.kana, "ja");
    return d || Number(a.dataset.order) - Number(b.dataset.order);
  }
  function mdText(iso) {
    var p = iso.split("-");
    return Number(p[1]) + "月" + Number(p[2]) + "日";
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function applyDay(ts) {
    var hits = 0;
    each(document.querySelectorAll(".mlist"), function (list) {
      var listCards = cards.filter(function (c) { return c.el.parentNode === list; });
      var shown = 0, count = 0;
      listCards.sort(function (a, b) { return cardCmp(a.el, b.el); }).forEach(function (c) {
        var on = state.off.indexOf(c.el.dataset.muni) < 0, matched = 0, first = true;
        c.items.forEach(function (it) {
          var r = ts.length ? match(it.n, ts) : [];
          it.li.hidden = !r;
          if (r && (r.length || it.marked)) { highlight(it.a, it.title, r); it.marked = r.length > 0; }
          it.li.classList.toggle("first", !!r && first);
          if (r) { matched++; first = false; }
        });
        c.el.hidden = !on || (ts.length > 0 && matched === 0);
        if (c.badge) c.badge.textContent = ts.length ? matched + "/" + c.items.length + "件" : c.items.length + "件";
        if (!c.el.hidden) { shown++; count += matched; }
        list.appendChild(c.el);
      });
      hits += count;
      var msg = list.nextElementSibling;
      if (msg && msg.classList.contains("fmsg")) {
        msg.hidden = shown > 0;
        msg.textContent = ts.length ? "検索語に一致する記事はありません" : "選択中の機関の記事はありません";
      }
      var meta = list.parentNode.querySelector(".shown");
      if (meta) meta.textContent = state.off.length || ts.length ? "（表示中 " + count + "件）" : "";
    });
    return hits;
  }

  function applyArchive(ts) {
    results.textContent = "";
    if (archState !== "ok") {
      results.appendChild(el("p", "msg", archState === "error"
        ? "過去30日分のデータを読み込めませんでした。時間をおいてもう一度お試しください"
        : "過去30日分のデータを読み込んでいます…"));
      return null;
    }
    var found = [];
    arch.forEach(function (e) {
      if (state.off.indexOf(e.m) >= 0) return;
      var r = match(e.n, ts);
      if (r) found.push({e: e, r: r});
    });
    found.sort(function (a, b) {
      return a.e.d < b.e.d ? 1 : a.e.d > b.e.d ? -1 : muniCmp(a.e.m, b.e.m);
    });
    var head = el("h2", null, "過去30日分の検索結果");
    head.appendChild(el("span", "meta", found.length + "件" +
      (found.length > LIMIT ? "（新しい順に" + LIMIT + "件を表示）" : "")));
    results.appendChild(head);
    if (!found.length) {
      results.appendChild(el("p", "msg", "検索語に一致する記事はありません"));
      return 0;
    }
    var ul = el("ul", "items");
    found.slice(0, LIMIT).forEach(function (f) {
      var li = el("li"), meta = el("span", "date"), day = el("a", null, mdText(f.e.d));
      day.href = base + "archive/" + f.e.d + ".html";
      meta.appendChild(day);
      meta.appendChild(document.createTextNode(" ・ " + f.e.m));
      var a = el("a");
      a.href = f.e.u;
      a.target = "_blank";
      a.rel = "noopener";
      highlight(a, f.e.t, f.r);
      li.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    results.appendChild(ul);
    return found.length;
  }

  function apply() {
    radios.forEach(function (r) { r.checked = r.value === state.sort; });
    boxes.forEach(function (b) { b.checked = state.off.indexOf(b.value) < 0; });
    var ts = terms();
    var dayHits = applyDay(ts);
    var archive = qAll.checked && ts.length > 0;
    if (archive) loadArchive();
    var hits = archive ? applyArchive(ts) : dayHits;
    results.hidden = !archive;
    dayView.hidden = archive;
    qClear.hidden = !q.value;
    qCount.textContent = !ts.length ? "" : hits == null ? "検索中…"
      : (archive ? "過去30日分の検索結果 " : "検索結果 ") + hits + "件";
    var total = boxes.length, on = boxes.filter(function (b) { return b.checked; }).length;
    toggle.textContent = "検索・並び替え・絞り込み" +
      (on < total ? "（" + on + "/" + total + "）" : "") + (ts.length ? "（検索中）" : "");
  }
  function setOpen(open) {
    document.body.classList.toggle("panel-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    backdrop.hidden = !open;
    if (open) panel.focus();
  }

  q.addEventListener("input", apply);
  q.addEventListener("keydown", function (e) {
    if (e.key === "Enter") q.blur();  // スマホでキーボードを閉じる
  });
  qClear.addEventListener("click", function () { q.value = ""; apply(); q.focus(); });
  qAll.addEventListener("change", apply);
  radios.forEach(function (r) {
    r.addEventListener("change", function () { state.sort = r.value; save(); apply(); });
  });
  boxes.forEach(function (b) {
    b.addEventListener("change", function () {
      state.off = state.off.filter(function (x) { return x !== b.value; });
      if (!b.checked) state.off.push(b.value);
      save(); apply();
    });
  });
  // 「すべて選択／解除」。分類のボタンはその分類、絞り込み欄の先頭のボタンは全機関が対象
  each(panel.querySelectorAll("button[data-act]"), function (btn) {
    btn.addEventListener("click", function () {
      var scope = btn.closest(".pregion") || panel;
      var names = Array.prototype.map.call(scope.querySelectorAll('input[name="muni"]'), function (b) { return b.value; });
      state.off = state.off.filter(function (x) { return names.indexOf(x) < 0; });
      if (btn.dataset.act === "off") state.off = state.off.concat(names);
      save(); apply();
    });
  });
  toggle.addEventListener("click", function () { setOpen(!document.body.classList.contains("panel-open")); });
  document.getElementById("panel-close").addEventListener("click", function () { setOpen(false); toggle.focus(); });
  backdrop.addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("panel-open")) { setOpen(false); toggle.focus(); }
  });

  // 戻る操作などでブラウザが入力欄を復元しても、検索語は引き継がない
  q.value = "";
  qAll.checked = false;
  panel.tabIndex = -1;
  panel.hidden = false;
  toggle.hidden = false;
  document.body.classList.add("has-panel");
  apply();
})();
"""


# 更新ボタン。docs/config.json の trigger_url（中継サーバーのURL）が空ならボタンも状態も出さない
REFRESH_JS = """
(function () {
  var stateEl = document.getElementById("run-state");
  var btn = document.getElementById("refresh");
  var msg = document.getElementById("refresh-msg");
  var base = "", wasBusy = false, timer = null;

  function hm(iso) {
    var p = {};
    new Intl.DateTimeFormat("ja-JP", {timeZone: "Asia/Tokyo", hour: "numeric", minute: "numeric", hour12: false})
      .formatToParts(new Date(iso)).forEach(function (x) { p[x.type] = x.value; });
    return Number(p.hour) + "時" + Number(p.minute) + "分";
  }
  function clock(iso) {
    return new Intl.DateTimeFormat("ja-JP", {timeZone: "Asia/Tokyo", month: "numeric", day: "numeric",
      hour: "2-digit", minute: "2-digit"}).format(new Date(iso));
  }
  function describe(run) {
    if (!run) return ["", ""];
    var s = run.status, c = run.conclusion;
    if (s === "in_progress") return ["実行中（" + clock(run.startedAt) + " 開始）", "busy"];
    if (s !== "completed") return ["実行待ち（" + clock(run.createdAt) + " 受付）", "busy"];
    if (c === "success") return ["前回の実行: 成功（" + clock(run.updatedAt) + "）", ""];
    if (c === "cancelled") return ["前回の実行: 中止（" + clock(run.updatedAt) + "）", ""];
    return ["前回の実行: 失敗（" + clock(run.updatedAt) + "）", "fail"];
  }
  function show(st) {
    var d = describe(st.latest);
    stateEl.textContent = d[0];
    stateEl.className = "state " + d[1];
    if (wasBusy && !st.busy && st.latest && st.latest.conclusion === "success") {
      msg.innerHTML = "更新が完了しました。1〜2分後に<a href=\\"\\" onclick=\\"location.reload();return false\\">再読み込み</a>すると反映されます。";
    }
    wasBusy = st.busy;
    clearTimeout(timer);
    if (st.busy) timer = setTimeout(refreshStatus, 20000);
  }
  function refreshStatus() {
    return fetch(base + "/status", {cache: "no-store"})
      .then(function (r) { return r.json(); }).then(show).catch(function () {});
  }

  fetch("config.json", {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (cfg) {
    base = String(cfg.trigger_url || "").trim().replace(/\\/+$/, "");
    if (!base) return;
    btn.hidden = false;
    refreshStatus();
    btn.addEventListener("click", function () {
      btn.disabled = true;
      msg.textContent = "送信中…";
      fetch(base + "/trigger", {method: "POST"}).then(function (r) {
        return r.json().then(function (body) { return {status: r.status, body: body}; });
      }).then(function (res) {
        if (res.status === 202) {
          msg.textContent = "受け付けました。5分ほどで反映されます";
          wasBusy = true;
          setTimeout(refreshStatus, 5000);
        } else if (res.status === 429 && res.body.nextAvailableAt) {
          msg.textContent = (res.body.reason === "busy" ? "ただいま更新中です。" : "") +
            "次に更新できるのは" + hm(res.body.nextAvailableAt) + "です";
        } else {
          msg.textContent = "受け付けられませんでした。時間をおいてもう一度お試しください";
        }
      }).catch(function () {
        msg.textContent = "通信に失敗しました。時間をおいてもう一度お試しください";
      }).then(function () { btn.disabled = false; });
    });
  }).catch(function () {});
})();
"""


def render_bar() -> str:
    return (
        '<div class="bar">'
        '<p class="state" id="run-state"></p>'
        '<button type="button" id="refresh" hidden>今すぐ更新</button>'
        '<p class="rmsg" id="refresh-msg" role="status" aria-live="polite"></p>'
        '</div>'
    )


def render_daynav(d: str, days: list[str], prefix: str) -> str:
    """前の日・次の日へのリンク（データのある日どうしをつなぐ）。days は新しい順。"""
    i = days.index(d)
    links = []
    if i + 1 < len(days):
        p = days[i + 1]
        links.append(f'<a class="prev" href="{prefix}archive/{p}.html">← 前の日（{esc(md(p))}）</a>')
    if i > 0:
        n = days[i - 1]
        href = f"{prefix}index.html" if i - 1 == 0 else f"{prefix}archive/{n}.html"
        links.append(f'<a class="next" href="{href}">次の日（{esc(md(n))}） →</a>')
    return f'<nav class="daynav">{"".join(links)}</nav>' if links else ""


def md(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.month}月{d.day}日"


def render_page(day: dict, archive_dates: list[str], prefix: str, is_index: bool) -> str:
    total = sum(len(m["new"]) for m in day["organizations"])

    # ロゴは幅の広い画面では右の余白に固定表示、狭い画面では見出しの横に小さく出す。
    # ファイルが読めないときは枠ごと隠す
    # LOGO_FILE が空ならロゴは出さない
    logo = f'{prefix}{LOGO_FILE}' if LOGO_FILE else ""
    logo_sm = (f'<img class="logo-sm" src="{esc(logo)}" alt="{esc(LOGO_ALT)}" onerror="this.hidden=true">'
               if logo else "")
    body = ['<header class="masthead"><div class="mtext">'
            f'<p class="site">{esc(SITE_NAME)}</p>'
            f"<h1>{esc(jp_date(day['date']))}の更新</h1></div>"
            f'{logo_sm}</header>']
    body.append(f'<p class="sub">最終取得 {esc(day.get("last_fetched", ""))}（日本時間） ・ 新着 {total} 件</p>')
    body.append(render_daynav(day["date"], archive_dates, prefix))
    if is_index:
        body.append(render_bar())
    body.append('<button type="button" class="ptoggle" id="panel-toggle" aria-controls="panel" '
                'aria-expanded="false" hidden>検索・並び替え・絞り込み</button>')
    body.append('<section class="sresults" id="search-results" aria-live="polite" hidden></section>')
    body.append(f'<div id="day-view">{render_day(day, split_latest=is_index)}</div>')

    body.append('<h3 class="foot">過去30日のアーカイブ</h3>')
    if not is_index:
        body.append(f'<p><a href="{prefix}index.html">← 最新の一覧へ</a></p>')
    links = "".join(
        f'<li><a href="{prefix}archive/{d}.html">{esc(jp_date(d))}</a></li>' for d in archive_dates
    )
    body.append(f'<ul class="archive">{links}</ul>')
    body.append("<footer>各記事の内容は各機関の公式サイトでご確認ください。</footer>")

    title = f"{jp_date(day['date'])}の更新"
    return (
        "<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"light dark\">"
        f"<title>{esc(title)} | {esc(SITE_NAME)}</title>"
        f"<style>{CSS}</style></head><body><div class=\"layout\">"
        + render_panel(day, prefix)
        + "<main>\n"
        + "\n".join(body)
        + "\n</main></div>"
        + (f'<img class="logo-side" src="{esc(logo)}" alt="" aria-hidden="true" onerror="this.hidden=true">'
           if logo else "")
        + f"<script>{PANEL_JS}</script>"
        + (f"<script>{REFRESH_JS}</script>" if is_index else "")
        + "</body></html>\n"
    )


def render_empty_page() -> str:
    """まだ一度も取得していないときのトップページ。"""
    return (
        "<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"light dark\">"
        f"<title>{esc(SITE_NAME)}</title>"
        f"<style>{CSS}</style></head><body><main>\n"
        f'<header class="masthead"><div class="mtext"><h1>{esc(SITE_NAME)}</h1></div></header>\n'
        '<p class="sub">岩手県内の国の出先機関・大学の新着情報を日ごとにまとめます。</p>\n'
        + render_bar() +
        '\n<p class="notice">まだ取得していません。取得元を設定して取得すると、ここに新着の一覧が表示されます。</p>\n'
        "<footer>各記事の内容は各機関の公式サイトでご確認ください。</footer>\n"
        f"</main><script>{REFRESH_JS}</script></body></html>\n"
    )


def write_search_index(days: list[str]) -> None:
    """過去30日分の記事タイトル検索用データを1ファイルにまとめる（新しい日から順）。"""
    items = []
    for d in days:
        for m in load_daily(DAILY_DIR / f"{d}.json", d)["organizations"]:
            items += [{"d": d, "m": m["name"], "t": i["title"], "u": i["url"]} for i in m["new"]]
    with SEARCH_FILE.open("w", encoding="utf-8") as f:
        json.dump({"days": days, "items": items}, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def write_pages(today: date) -> None:
    cutoff = today - timedelta(days=ARCHIVE_DAYS - 1)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 30日より古い日次データとアーカイブを削除
    for path in list(DAILY_DIR.glob("*.json")) + list(ARCHIVE_DIR.glob("*.html")):
        try:
            if date.fromisoformat(path.stem) < cutoff:
                path.unlink()
        except ValueError:
            pass

    days = sorted((p.stem for p in DAILY_DIR.glob("*.json")), reverse=True)
    write_search_index(days)
    (DOCS_DIR / ".nojekyll").touch()
    if not days:  # まだ一度も取得していない
        (DOCS_DIR / "index.html").write_text(render_empty_page(), encoding="utf-8")
        return
    for d in days:
        data = load_daily(DAILY_DIR / f"{d}.json", d)
        (ARCHIVE_DIR / f"{d}.html").write_text(
            render_page(data, days, "../", is_index=False), encoding="utf-8")
    latest = load_daily(DAILY_DIR / f"{days[0]}.json", days[0])
    (DOCS_DIR / "index.html").write_text(render_page(latest, days, "", is_index=True), encoding="utf-8")


def main() -> None:
    now = datetime.now(JST)
    if "--render-only" in sys.argv[1:]:  # 取得せず、保存済みのデータからページだけ作り直す
        write_pages(now.date())
        print("ページを作り直しました（取得はしていません）", file=sys.stderr)
        return
    result = run(now)
    today = now.date().isoformat()
    daily_path = DAILY_DIR / f"{today}.json"
    save_json(daily_path, add_fetch(load_daily(daily_path, today), result))
    write_pages(now.date())
    total = sum(len(m["new"]) for m in result["organizations"])
    print(f"完了: {result['fetched_at']} 取得 新着 {total} 件", file=sys.stderr)


if __name__ == "__main__":
    main()
