# ページの診断

実行環境の接続元: 20.168.98.32（US / AS8075 Microsoft Corporation）

| ページ | 取得方法 | 結果 | サーバー | 本文 | 日付の書式 | 手がかり |
|---|---|---|---|---|---|---|
| https://www.iwate-pu.ac.jp/news | 本番のUser-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |
| https://www.iwate-pu.ac.jp/news | ブラウザ風User-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |
| https://www.iwate-pu.ac.jp/news | Worker経由 | ✅ 200（転送先 https://ginga-trigger.iwate-news.workers.dev/proxy?url=https%3A%2F%2Fwww.iwate-pu.ac.jp%2Fnews） | cloudflare | 328770 バイト | kanji:21, reiwa_short:3, monthday:24 | ボット対策・WAF、Cloudflare のヘッダーあり |

失敗したときのヘッダーと本文は `reports/diagnose/*.txt`にあります（取得できたページの保存分は確認後に削除しました）。

判定の目安: ブラウザ風だけ成功 → User-Agent で判定するボット対策 ／ どちらも 403 で本文に海外・国外の文言 → 海外 IP の遮断 ／ Cloudflare などのヘッダーや captcha・challenge の文言 → WAF のボット対策
