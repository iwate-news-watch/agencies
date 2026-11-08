# ページの診断

実行環境の接続元: 4.155.63.144（US / AS8075 Microsoft Corporation）

| ページ | 取得方法 | 結果 | サーバー | 本文 | 日付の書式 | 手がかり |
|---|---|---|---|---|---|---|
| https://www.thr.mlit.go.jp/minamisanriku/kisha/index.html | 本番のUser-Agent | ✅ 200 | openresty | 7007 バイト | 日付なし |  |
| https://www.thr.mlit.go.jp/minamisanriku/kisha/index.html | ブラウザ風User-Agent | ✅ 200 | openresty | 7007 バイト | 日付なし |  |
| https://www.maff.go.jp/tohoku/press/houdou.html | 本番のUser-Agent | ✅ 200 | AmazonS3 | 35103 バイト | 日付なし | ボット対策・WAF |
| https://www.maff.go.jp/tohoku/press/houdou.html | ブラウザ風User-Agent | ✅ 200 | AmazonS3 | 35103 バイト | 日付なし | ボット対策・WAF |
| https://www.iwate-pu.ac.jp/ | 本番のUser-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |
| https://www.iwate-pu.ac.jp/ | ブラウザ風User-Agent | ❌ 403 | CloudFront | 919 バイト |  |  |

失敗したときのヘッダーと本文は `reports/diagnose/*.txt`にあります（取得できたページの保存分は確認後に削除しました）。

判定の目安: ブラウザ風だけ成功 → User-Agent で判定するボット対策 ／ どちらも 403 で本文に海外・国外の文言 → 海外 IP の遮断 ／ Cloudflare などのヘッダーや captcha・challenge の文言 → WAF のボット対策
