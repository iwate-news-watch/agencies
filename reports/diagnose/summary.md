# ページの診断

実行環境の接続元: 40.65.58.132（US / AS8075 Microsoft Corporation）

| ページ | 取得方法 | 結果 | サーバー | 本文 | 日付の書式 | 手がかり |
|---|---|---|---|---|---|---|
| https://www.iwate-pu.ac.jp/ | 本番のUser-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |
| https://www.iwate-pu.ac.jp/ | ブラウザ風User-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |
| https://www.iwate-pu.ac.jp/ | Worker経由 | ✅ 200（転送先 https://ginga-trigger.iwate-news.workers.dev/proxy?url=https%3A%2F%2Fwww.iwate-pu.ac.jp%2F） | cloudflare | 397290 バイト | kanji:8, monthday:8 | ボット対策・WAF、Cloudflare のヘッダーあり |

失敗したときのヘッダーと本文は `reports/diagnose/*.txt`、取得できたページは `reports/diagnose/*.html` にあります。

判定の目安: ブラウザ風だけ成功 → User-Agent で判定するボット対策 ／ どちらも 403 で本文に海外・国外の文言 → 海外 IP の遮断 ／ Cloudflare などのヘッダーや captcha・challenge の文言 → WAF のボット対策
