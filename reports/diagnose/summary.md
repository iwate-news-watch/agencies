# ページの診断

実行環境の接続元: 20.99.245.113（US / AS8075 Microsoft Corporation）

| ページ | 取得方法 | 結果 | サーバー | 本文 | 日付の書式 | 手がかり |
|---|---|---|---|---|---|---|
| https://www2.suigi.pref.iwate.jp/info | 本番のUser-Agent | ✅ 200 | Apache | 84206 バイト | kanji:2, reiwa:54, monthday:65 | ボット対策・WAF |
| https://www2.suigi.pref.iwate.jp/info | ブラウザ風User-Agent | ✅ 200 | Apache | 84206 バイト | kanji:2, reiwa:54, monthday:65 | ボット対策・WAF |
| https://www2.suigi.pref.iwate.jp/info_log/news | 本番のUser-Agent | ✅ 200 | Apache | 86904 バイト | reiwa:71, monthday:87 | ボット対策・WAF |
| https://www2.suigi.pref.iwate.jp/info_log/news | ブラウザ風User-Agent | ✅ 200 | Apache | 86904 バイト | reiwa:71, monthday:87 | ボット対策・WAF |
| https://www2.suigi.pref.iwate.jp/info_log/news/feed/ | 本番のUser-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/info_log/news/feed） | Apache | 36957 バイト | slash:102, reiwa:41, monthday:47 |  |
| https://www2.suigi.pref.iwate.jp/info_log/news/feed/ | ブラウザ風User-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/info_log/news/feed） | Apache | 36957 バイト | slash:102, reiwa:41, monthday:47 |  |
| https://www2.suigi.pref.iwate.jp/info/feed/ | 本番のUser-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/info/feed） | Apache | 80168 バイト | slash:225, kanji:1, reiwa:20, monthday:26 |  |
| https://www2.suigi.pref.iwate.jp/info/feed/ | ブラウザ風User-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/info/feed） | Apache | 80168 バイト | slash:225, kanji:1, reiwa:20, monthday:26 |  |
| https://www2.suigi.pref.iwate.jp/category/top_news/feed/ | 本番のUser-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/category/top_news/feed） | Apache | 22306 バイト | slash:15, kanji:3, reiwa:12, monthday:20 | ボット対策・WAF |
| https://www2.suigi.pref.iwate.jp/category/top_news/feed/ | ブラウザ風User-Agent | ✅ 200（転送先 https://www2.suigi.pref.iwate.jp/category/top_news/feed） | Apache | 22306 バイト | slash:15, kanji:3, reiwa:12, monthday:20 | ボット対策・WAF |
| https://www.pref.iwate.jp/agri/i-agri/feed | 本番のUser-Agent | ✅ 200 | openresty | 10234 バイト | reiwa:6, monthday:10 |  |
| https://www.pref.iwate.jp/agri/i-agri/feed | ブラウザ風User-Agent | ✅ 200 | openresty | 10234 バイト | reiwa:6, monthday:10 |  |

失敗したときのヘッダーと本文は `reports/diagnose/*.txt`にあります（取得できたページの保存分は確認後に削除しました）。

判定の目安: ブラウザ風だけ成功 → User-Agent で判定するボット対策 ／ どちらも 403 で本文に海外・国外の文言 → 海外 IP の遮断 ／ Cloudflare などのヘッダーや captcha・challenge の文言 → WAF のボット対策
