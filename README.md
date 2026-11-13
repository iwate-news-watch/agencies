# GINGA 岩手県 国の機関・大学 新着情報

岩手県内の国の出先機関・大学・研究機関の新着情報を集めて、GitHub Pages に日ごとの一覧として公開する仕組みです。

- 公開URL: https://iwate-news-watch.github.io/agencies/
- 取得: RSS/Atom フィードと、RSSのないサイトのスクレイピング（取得元は `sources.yaml` に設定。現在は未設定）
- 実行: 定期実行はしません。GitHub の Actions 画面からの手動実行（中継サーバーを用意すれば公開ページの「今すぐ更新」ボタンも）で取得し、結果をこのリポジトリにコミット
- 表示: 取得した日ごとに機関別の一覧。スマホで読みやすいレイアウト、ダークモード対応、前後の日への移動と過去30日分のアーカイブ付き
- 調査: 取得元を決めるための調査用ワークフロー（手動実行のみ）で、各サイトの RSS/Atom と新着一覧ページの候補を探し、`reports/survey_agencies.csv` に保存

> このリポジトリは岩手県市町村の新着一覧（iwate-news-watch/test）をひな形にしています。

## 現在の状況と今後の手順

次の順に進めています（1・2は完了）。

1. ✅ **取得元を調査する** … 「Survey agencies」ワークフローを実行し、`reports/survey_agencies.csv` で各サイトのフィードと新着一覧ページを確認します（下記「取得元の調査」）。
2. ✅ **取得元を設定する** … 調査結果をもとに `sources.yaml` に取得元を書きます（下記「取得元の追加・変更方法」）。
3. **取得する** … 「Iwate agencies news」ワークフローを実行します。初回は記録のみで、2回目以降に増えた記事が新着として表示されます。
4. ✅ 更新ボタン用の中継サーバー（`https://ginga-trigger.iwate-news.workers.dev`）を用意し、`docs/config.json` の `trigger_url` に設定しました。
5. ✅ ロゴ（`docs/ginga-logo-v2.svg`）を `scripts/build.py` の `LOGO_FILE` に設定しました。

## 対象の機関

分類は公開ページの並び替え・絞り込みパネルの区分です（`scripts/build.py` の `CATEGORIES`）。URLは各機関のトップです。取得方法は `sources.yaml` を見てください。

- 取得中: 盛岡地方気象台・岩手労働局・岩手河川国道事務所・北上川ダム統合管理事務所・三陸国道事務所・南三陸沿岸国道事務所・東北農政局（東北6県）・盛岡財務事務所・日本銀行盛岡事務所・岩手大学・岩手県立大学（Worker 経由）・岩手医科大学・盛岡大学・いわて富士大学・国立天文台 水沢VLBI観測所・東京大学 国際沿岸海洋研究センター・いわてアグリベンチャーネット・岩手県水産技術センター
- 準備中: なし（新しく機関を追加して取得方法が決まるまでは、`preparing: true` でページ下部にホームページへのリンクだけ表示できます）
- 岩手県立大学は GitHub Actions からの直接の取得が HTTP 403（CloudFront で遮断）のため、Cloudflare Worker の `/proxy` 経由で新着情報一覧（`/news`）を取得しています。
- 東北農政局は東北6県まとめての発表にも岩手の情報が含まれるため、キーワードで絞らずに報道発表をすべて拾います。


| 分類 | 名称 | URL |
|---|---|---|
| 国の機関 | 盛岡地方気象台 | https://www.data.jma.go.jp/morioka/ |
| 国の機関 | 岩手労働局 | https://jsite.mhlw.go.jp/iwate-roudoukyoku/ |
| 国の機関 | 岩手河川国道事務所 | https://www.thr.mlit.go.jp/iwate/ |
| 国の機関 | 三陸国道事務所 | https://www.thr.mlit.go.jp/sanriku/ |
| 国の機関 | 南三陸沿岸国道事務所 | https://www.thr.mlit.go.jp/minamisanriku/ |
| 国の機関 | 北上川ダム統合管理事務所 | https://www.thr.mlit.go.jp/kitakato/ |
| 国の機関 | 盛岡財務事務所 | https://lfb.mof.go.jp/tohoku/morioka/ |
| 国の機関 | 日本銀行盛岡事務所 | https://www3.boj.or.jp/morioka/ |
| 国の機関 | 東北農政局（東北6県） | https://www.maff.go.jp/tohoku/ |
| 大学・研究機関 | 岩手大学 | https://www.iwate-u.ac.jp/ |
| 大学・研究機関 | 岩手県立大学 | https://www.iwate-pu.ac.jp/ |
| 大学・研究機関 | 岩手医科大学 | https://www.iwate-med.ac.jp/ |
| 大学・研究機関 | 盛岡大学 | https://morioka-u.ac.jp/ |
| 大学・研究機関 | いわて富士大学 | https://www.fuji-u.ac.jp/ |
| 大学・研究機関 | 国立天文台 水沢VLBI観測所 | https://www.miz.nao.ac.jp/ |
| 大学・研究機関 | 東京大学 国際沿岸海洋研究センター | https://www.icrc.aori.u-tokyo.ac.jp/ |
| 県の試験研究・普及機関 | いわてアグリベンチャーネット | https://www.pref.iwate.jp/agri/i-agri/ |
| 県の試験研究・普及機関 | 岩手県水産技術センター | https://www2.suigi.pref.iwate.jp/ |

```
.
├── sources.yaml               # 取得元の一覧（ここを編集する）
├── survey_targets.yaml        # 調査用ワークフローの調査対象
├── scripts/build.py           # 取得・新着判定・HTML生成
├── scripts/survey.py          # 取得元の調査
├── scripts/inspect_sources.py # 取得元ごとに拾える記事の確認
├── requirements.txt
├── reports/survey_agencies.csv  # 1回目の調査結果（20サイト）
├── reports/survey_agencies_2.csv  # 2回目の調査結果（準備中の機関の再調査）
├── reports/survey_agencies_3.csv  # 3回目の調査結果（岩手県立大学を Worker 経由で）
├── reports/survey_agencies_4.csv  # 4回目の調査結果（県の試験研究・普及機関の2機関）
├── reports/diagnose/          # ページの診断結果（Inspect sources の URL 指定）
├── reports/inspect_sources.csv  # 取得元の確認結果（確認用ワークフローが更新）
├── state/
│   ├── seen.json              # 既出記事のURL（90日より古い記録は自動削除）
│   └── daily/YYYY-MM-DD.json  # 日ごとの一覧データ（直近30日分）
├── docs/
│   ├── index.html             # 公開ページ（最新の日の一覧。未取得のあいだは案内のみ）
│   ├── config.json            # 更新ボタンの設定（中継サーバーのURL）
│   ├── search.json            # 過去30日分の記事タイトル検索用データ（自動生成）
│   └── archive/YYYY-MM-DD.html  # 日別アーカイブ（直近30日分）
├── worker/worker.js           # 更新ボタン用の中継サーバー（Cloudflare Workers）
└── .github/workflows/
    ├── daily.yml              # 取得・ページ生成のワークフロー（手動実行のみ）
    ├── survey.yml             # 取得元の調査ワークフロー（手動実行のみ）
    └── inspect.yml            # 取得元の確認ワークフロー（手動実行のみ）
```

ページ内のリンク（アーカイブ・前後の日・検索用データ・設定ファイル）はすべて相対パスなので、`/agencies/` 配下でもそのまま動きます。

## 取得元の調査（Survey agencies）

調査対象は `survey_targets.yaml` に書きます。結果の保存先も同じファイルの `output:` で決めます（現在は `reports/survey_agencies_2.csv`。調査のたびに変えれば、前回の結果を残せます）。

```yaml
output: reports/survey_agencies_2.csv
targets:
  - category: 国の機関
    name: 東北農政局
    urls: ["https://www.maff.go.jp/tohoku/stinfo/index.html", "https://www.maff.go.jp/tohoku/press/houdou.html"]
    hints: ["https://www.maff.go.jp/tohoku/xxxx/"]   # （任意）一覧ページがありそうな場所
    keywords: [岩手]                                 # （任意）絞り込みのキーワード
```

**実行方法**

1. リポジトリ画面の **Actions** タブ → 左の一覧の「**Survey agencies**」→「**Run workflow**」（ブランチは `main`）を押します。
2. 10〜20分ほどで終わります。結果は `output:` の CSV に保存してコミットされます。実行結果画面（Summary）にも、機関ごとに記事を拾えた候補の上位が表で出ます。

**調べる内容**

- アクセスは一般的なブラウザに近い User-Agent と `Accept-Language: ja` で行います（ボット向けに別のページを返すサイトがあるため）。
- フィード: `urls` の各ページについて、`<link rel="alternate">`・ページ内の RSS / Atom らしいリンク・よくあるパス（`rss.xml`・`feed/`・`index.rdf` など）を試し、実際に読めて記事があるものを記録します。
- 一覧ページ: 次の順に候補を集め、1サイトにつき最大14ページまで確認します。
  1. `urls` と `hints` に書いたページそのもの
  2. それらのページにある「記者発表」「報道発表」「お知らせ」「新着」「ニュース」「トピックス」などのリンク（`hints` の下にあるリンクを優先）
  3. 2 のページをさらに1段たどった先にある同様のリンク
- 候補ごとに、ページ内の日付の書式（`dotted`・`slash`・`kanji`・`reiwa`）を判定し、本番と同じ読み取りで記事を拾って、件数・最新の日付・タイトル例（5件）を記録します。`keywords` があれば、絞り込んだ場合の件数とタイトル例も記録します。
- URLが誤っている・取得できないページは `status` が `error` になり、`error` 列に理由（HTTP 404、接続エラーなど）が入ります。

CSV は1行に1候補で、主な列は `kind`（`site`=調べたページ、`feed`=フィード、`list`=一覧ページの候補）、`url`、`found_via`（見つけ方: `start`・`hint`・`top_link`=1段目、`level2_link`=2段目、`link_alternate`・`page_link`・`common_path`=フィード）、`link_text`（リンクの文字）、`date_format`、`items`、`keyword_items`、`latest`、`sample_titles`、`keyword_samples`、`error` です。Excel で開けるよう BOM 付き UTF-8 です。

調査結果を見て取得元を `sources.yaml` に書き、`scripts/build.py` の `CATEGORIES` に分類と読みを追加してください（下記）。

## 新着の判定と日ごとの一覧

- 取得した記事のURLを `state/seen.json` と照合し、未登録のものを「新着」として表示します。
- 初回の取得では記録だけを行い、ページに「初回のため記録のみ」と表示します。あとから取得元を追加した場合も、その取得元の初回は記録だけになります（既存記事がまとめて新着扱いになるのを防ぐため）。
- 前回の取得から増えた記事は、すべて**取得した日**の一覧に入ります。記事の掲載日では振り分けません（掲載日は各記事の上に表示します）。
- 同じ日に何回取得しても、その日の一覧に追加していきます。一覧は機関ごとにまとまっていて、各機関の中では新しく取得した記事ほど上に並びます。
- トップページはいちばん新しい日の一覧です。見出しは「2026年10月15日の更新」、その下にその日の最後の取得時刻（「最終取得 16:05」）を表示します。
- トップページの一番上には「最新の取得で増えた記事」の枠があり、直近1回の取得で新しく見つかった記事だけを取得時刻・件数とともに機関ごとに表示します。増えた記事がなければ「前回から新しい記事はありません」と表示します。その下に、その日のそれ以外の記事を機関ごとに表示します（最新の取得分とは重複しません）。アーカイブの過去の日のページは1つの一覧のままです。
- 各ページに機関の「並び替え・絞り込み」パネルがあります（PCでは画面左に常に表示、スマホでは「検索・並び替え・絞り込み」ボタンで開閉）。並び替えは分類順（国の機関・大学・研究機関・県の試験研究・普及機関、初期値）・新着件数順・五十音順、絞り込みは機関ごとのチェックと分類ごとの「すべて選択／解除」です。パネルには `sources.yaml` に載っている機関（とその日の一覧にある機関）だけが分類ごとにまとまって並びます。選んだ設定はブラウザに保存され、次回も同じ状態で表示されます。
- 分類と読みは `scripts/build.py` の `CATEGORIES` にあります。`sources.yaml` に機関を追加するときは、同じ名前でここにも追加してください（ない機関は「その他」に入ります）。
- パネルの一番上には記事タイトルの検索窓があります。入力するとその場で記事を絞り込み、一致部分をハイライトします（スペース区切りはAND検索、全角半角・大文字小文字は区別しません）。機関の絞り込みと組み合わせて使えます。「過去30日分も検索」をオンにすると、アーカイブを含めた結果を日付・機関名つきで一覧表示します（新しい順に最大200件）。検索用データは取得のたびに `docs/search.json` に出力されます。検索語は保存しません。
- 記事一覧の機関名の見出しと、「更新なし」などに並ぶ機関名は、その機関の公式ホームページへのリンクです（別タブで開きます）。URLは `sources.yaml` の最初の取得元URLのドメインのトップ（`https://ドメイン/`）で、機関ごとに `homepage:` を書くと上書きできます。出先機関はドメインのトップが本省のサイトになることが多いので、`homepage:` の指定をおすすめします。
- 各ページの上部に前の日・次の日へのリンク（取得のあった日どうしをつなぎます）、下部に過去30日分のアーカイブへのリンクがあります。
- 同じ機関の中で、その日の一覧に同じタイトルの記事が複数あるときは、先に見つけたほうだけを表示します（全角半角・大文字小文字・空白の有無は無視します）。同じ記事が複数の一覧に別のURLで載るサイト（水沢VLBIのトピックスとお知らせなど）の重複を防ぐためです。別の日に同じタイトルで出た記事は、定期的な更新のお知らせ（「入札公告を更新しました」など）を見落とさないよう、まとめずに表示します。
- 取得に失敗した機関は、その日の最後の取得で失敗していれば一覧の先頭に赤く「取得エラー」と表示されます。ほかの機関の処理は続行します。

## 取得元の追加・変更方法

`sources.yaml` を編集して main ブランチにコミットするだけです。次回の取得から反映されます。

**RSS / Atom フィードの場合**

次のように機関を並べます（URLは例です）。

```yaml
  - name: 岩手大学
    homepage: https://www.iwate-u.ac.jp/
    sources:
      - type: rss
        url: https://www.iwate-u.ac.jp/xxxx/feed.xml
```

- Atom フィードも `type: rss` で読めます。
- 1つの機関に複数のフィードを並べられます。同じ記事が複数のフィードにあっても、URLが同じなら1件にまとめます。

**RSS のないサイト（スクレイピング）の場合**

ページ内で日付を見つけ、その直後に出てくる最初のリンクを記事のタイトルとURLとして扱います。

```yaml
  - name: 盛岡地方気象台
    homepage: https://www.data.jma.go.jp/morioka/
    sources:
      - type: scrape
        url: https://www.data.jma.go.jp/morioka/xxxx/
        date_format: dotted       # 「2026.10.15」形式
        # selector: "#news-list"  # （任意）記事一覧部分だけを対象にするCSSセレクタ
```

| `date_format` | 日付の書式 | 例 |
|---|---|---|
| `dotted` | 西暦をドットで区切る | `2026.10.15` |
| `slash` | 西暦をスラッシュで区切る | `2026/10/16` |
| `kanji` | 西暦を年月日で書く | `2026年11月5日`（空白入り・全角数字も可） |
| `reiwa` | 令和（令和N年 = 西暦 2018+N 年） | `令和8年 10月15日`（空白入り・全角数字も可） |
| `reiwa_short` | 令和の略記 | `R8.11.6`・`R08.11.06`・`R8/11/6` |
| `monthday` | 年なしの月日。年は取得日から推定（取得日より1か月以上先になる日付は前年とみなす）。タイトル中の日付と区別するため `date_position: after` と組み合わせます | `11月4日`・`［11月4日］` |

全角数字は半角に直してから読みます。HTML のコメント（`<!-- -->`）の中は読みません（取り下げた記事が残っていることがあるため）。

- メニューやバナーのリンクまで拾ってしまう場合は、`selector` で記事一覧の部分を指定してください。複数の範囲に当たる場合は範囲ごとに読み、範囲をまたいで日付とリンクを組にしません（1記事ずつの枠を指定すると確実です）。
- 日付がタイトルの**後ろ**にあるサイトは `date_position: after` を付けます（リンクの後に出てくる日付をその記事の日付にします）。
- 「詳細は**こちら**」のように本文の中にリンクがあるサイトは `title_from: text` を付けます。日付から次の日付までの文章をタイトルにし（120字まで）、その中の最初のリンクを記事のURLにします。リンクのない記事は取得元のページへのリンクになります。
- タイトル末尾の「NEW」「新着」の印は自動で取り除きます。

**キーワードで絞り込む場合（rss・scrape 共通）**

広い範囲（東北全体など）の一覧から岩手県に関係する記事だけを拾うときは、取得元ごとに `include_keywords` を書きます。タイトルにどれかの語を含む記事だけを拾います（全角半角・大文字小文字は区別しません）。

```yaml
      - type: scrape
        url: https://www.maff.go.jp/tohoku/press/houdou.html
        date_format: reiwa
        include_keywords: [岩手]
```

```yaml
      - type: scrape
        url: https://www.miz.nao.ac.jp/content/news/topics.html
        date_format: dotted
        selector: "div.views-row"   # 記事1件ずつの枠
        date_position: after        # 日付がタイトルの後ろ
```

**設定を変えたら確認する（Inspect sources）**

Actions の「**Inspect sources**」を実行すると、各取得元からいま拾える記事（タイトル・URL・日付・リンクのある場所）を `reports/inspect_sources.csv` に書き出し、実行結果画面に取得元ごとの件数とタイトルの例を表示します。新着の記録（`state/`）は変えません。「save_html」をオンにすると、scrape の取得元のページを `reports/html/` に保存します（`selector` を決める参考。確認が済んだら削除してください）。

「urls」に URL を空白区切りで入れると、そのページだけを**診断**します（結果は `reports/diagnose/`）。

- 本番の User-Agent と、一般的なブラウザに近い User-Agent の2通りで取得し、HTTP ステータス・サーバー・本文の長さ・日付の書式の数・遮断の手がかり（海外からの遮断・WAF などの文言）を `summary.md` と実行結果画面に表示します。
- 失敗（4xx/5xx）したときは、レスポンスのヘッダーと本文（先頭8000文字）を `<ページ>-<方法>.txt` に保存します。実行環境の接続元 IP と国も記録します。
- 「via_proxy」をオンにすると、Worker の `/proxy` 経由の取得も試します。
- 「save_html」をオンにすると、取得できたページを保存します（確認が済んだら削除してください）。

**GitHub Actions から取得できないサイト（`via_proxy`）**

海外の IP やデータセンターからのアクセスを遮断しているサイトは、取得元に `via_proxy: true` を書くと Cloudflare Worker（`docs/config.json` の `trigger_url`）の `/proxy` 経由で取得します。Worker 側で許可したホスト（既定は `www.iwate-pu.ac.jp` だけ）しか取得できません。Worker の設定は下の「Worker の /proxy」を見てください。

```yaml
      - type: scrape
        url: https://www.iwate-pu.ac.jp/xxxx/
        date_format: dotted
        via_proxy: true
```

**読み方を変えたときの注意**

`selector`・`date_position`・`title_from` を変えると、拾う記事のURLが変わることがあります。古い記事がまとめて新着扱いになるのを防ぐには、`state/seen.json` の `sources` からその取得元のURLの行を消してください。次回の取得でその取得元は「初回のため記録のみ」になります。
- 日付が読めない記事も取りこぼさず、日付欄を空にして表示します。

**取得元をやめる・一時的に止める場合**

その機関に `preparing: true` を書くと、取得せずにページ下部の「準備中」にホームページへのリンクだけを表示します（パネルにも並びません）。

```yaml
  - name: 岩手県立大学
    homepage: https://www.iwate-pu.ac.jp/
    preparing: true
```

`sources: []`（`preparing` なし）にすると、ページに「取得元未設定」と表示されます。

**機関を対象から外す場合**

`sources.yaml` から削除し、`scripts/build.py` の `CATEGORIES` と `survey_targets.yaml` からも削除します。

**ローカルで試す場合**

```bash
pip install -r requirements.txt
python scripts/build.py
```

`state/` と `docs/` が更新されます。取得せずにページの見た目だけを作り直すときは `python scripts/build.py --render-only` を使います。試した結果をコミットしたくない場合は `git checkout -- state docs` で元に戻してください。

## GitHub Pages の有効化手順

1. この仕組みのファイルを **main ブランチにマージ**します（ワークフローの実行や更新ボタンは main ブランチを対象にします）。
2. GitHub のリポジトリ画面で **Settings → Pages** を開きます。
3. 「Build and deployment」の **Source** で「**Deploy from a branch**」を選びます。
4. **Branch** で「`main`」と「`/docs`」を選び、**Save** を押します。
5. 1〜2分ほどで、画面上部に公開URL（https://iwate-news-watch.github.io/agencies/ ）が表示されます。
6. **Settings → Actions → General** の「Workflow permissions」が「Read and write permissions」になっているか確認します（ワークフロー側でも `contents: write` を指定していますが、組織の設定で制限されている場合はここを変更してください）。

> 補足: 無料プランでは、GitHub Pages を使えるのは公開（Public）リポジトリのみです。また main ブランチに保護ルール（直接 push の禁止など）があると、ワークフローの自動コミットが失敗します。

## 手動で実行する方法

1. リポジトリ画面の **Actions** タブを開きます。
2. 左の一覧から「**Iwate agencies news**」を選びます。
3. 右側の「**Run workflow**」を押し、ブランチが `main` になっていることを確認して、緑の「**Run workflow**」を押します。
4. 数分で完了し、`state/` と `docs/` の更新が自動でコミットされます。その後1〜2分で公開ページに反映されます。

失敗した場合は、実行結果の「Build pages」ステップのログに、取得元ごとの `[OK]` / `[ERROR]` が出力されています。

## 同時に実行されたときの扱い

- 取得は手動実行（更新ボタン・Actions 画面）だけですが、Actions 画面からの実行は更新ボタンの制限を通らないため、重なることがあります。
- ワークフローは `concurrency`（グループ `agencies-news`）で、同時に1つだけ動きます。実行中に次の実行が来た場合はキャンセルせず、前の実行が終わるまで待ちます。
- 待っていた実行も、その時点の最新の main から始めます（前の実行の結果を取り込んだ状態で新着を判定します）。
- push の前に `git pull --rebase` で最新の main を取り込みます。失敗した場合は間隔をあけて最大5回までやり直します。
- 注意: GitHub の仕様で、待機できるのは1件だけです。待機中の実行がある状態でさらに別の実行が来ると、古いほうの待機中の実行は GitHub によってキャンセルされます（新しいほうが実行されるので、取得自体は行われます）。更新ボタンは実行中・待機中には受け付けないため、通常はこの状況になりません。

## 公開ページの「今すぐ更新」ボタン

公開ページの上部に、誰でもログインなしで押せる更新ボタンを付けられます。現在の中継サーバーは `https://ginga-trigger.iwate-news.workers.dev` です（`docs/config.json` の `trigger_url` に設定済み）。ボタンを押すと、中継サーバー（Cloudflare Workers）が GitHub Actions のワークフローを実行します。GitHub のトークンは中継サーバーだけが持ち、公開ページには含まれません。

- 前回の実行開始から15分以内、または実行中・待機中は受け付けず、「次に更新できるのは◯時◯分です」と表示します。
- 受け付けると「受け付けました。5分ほどで反映されます」と表示します。完了すると再読み込みを促す表示が出ます。
- ページ上部の「最終取得」の下に、ワークフローの実行状態（実行待ち・実行中・成功・失敗）を表示します。
- 中継サーバーのURLを設定しないうちは、ボタンと実行状態は表示されません（取得は Actions 画面からの手動実行だけになります）。

設定は次の3ステップです。すべてスマホのブラウザでできます。

### 1. GitHub のトークンを作る

1. GitHub にログインし、右上のアイコン → **Settings** を開きます。
2. 左メニュー（スマホでは下のほう）の **Developer settings** → **Personal access tokens** → **Fine-grained tokens** を開き、**Generate new token** を押します。
3. 次のように入力します。
   - **Token name**: 分かりやすい名前（例: `iwate-agencies-button`）
   - **Expiration**: 有効期限（期限が切れたら作り直して、手順2の `GITHUB_TOKEN` を入れ替えます）
   - **Resource owner**: 自分のアカウント
   - **Repository access**: **Only select repositories** を選び、このリポジトリだけを選択
   - **Permissions** → **Repository permissions** → **Actions** を **Read and write** に変更（Metadata の Read-only は自動で付きます。ほかは変更不要）
4. **Generate token** を押し、表示された `github_pat_...` で始まる文字列をコピーします。**この画面を閉じると二度と表示されない**ので、次の手順まで控えておいてください。

> トークンはこのリポジトリのワークフローの実行・状態確認だけができる権限です。コードの書き換えはできません。リポジトリのファイルやチャットなどには絶対に貼り付けないでください。

### 2. Cloudflare Workers に中継サーバーを作る

1. スマホのブラウザで https://dash.cloudflare.com/ を開き、Cloudflare アカウントでログインします（無料プランで使えます）。
2. メニューから **Workers & Pages**（「Compute (Workers)」と表示される場合もあります）を開き、**Create**（作成）→ **Worker** の **Start with Hello World!** を選びます。
3. Worker の名前を入力（例: `iwate-agencies`）して **Deploy** を押します。
4. 作成後の画面で **Edit code**（コードを編集）を押します。
5. 別のタブでこのリポジトリの [`worker/worker.js`](worker/worker.js) を開き、**Raw** 表示にして全文をコピーします。
6. Worker のエディタに最初から入っているコードをすべて消して、コピーした内容を貼り付け、**Deploy** を押します。
7. Worker の画面に戻り、**Settings**（設定）→ **Variables and Secrets**（変数とシークレット）→ **Add**（追加）で、次の5つを登録します。

   | 名前 | 種類 | 値の例 |
   |---|---|---|
   | `GITHUB_OWNER` | Text（テキスト） | `iwate-news-watch` |
   | `GITHUB_REPO` | Text | `agencies` |
   | `WORKFLOW_FILE` | Text | `daily.yml` |
   | `ALLOWED_ORIGIN` | Text | `https://iwate-news-watch.github.io` |
   | `GITHUB_TOKEN` | **Secret（シークレット）** | 手順1でコピーしたトークン |

   - `ALLOWED_ORIGIN` は公開ページのURLの「`https://〜.github.io`」の部分だけです（末尾の `/` やリポジトリ名は付けません）。ここに書いたページからしかボタンが使えません（同じ `iwate-news-watch.github.io` 上の別サイトからも呼べる点に注意してください）。
   - `GITHUB_TOKEN` は必ず **Secret** を選んでください（保存後は値が見えなくなります）。
8. 保存（**Deploy**）します。
9. Worker のURL（`https://iwate-agencies.<あなたのサブドメイン>.workers.dev` のような形）をコピーします。
10. 動作確認として、ブラウザでそのURLの末尾に `/status` を付けて開きます（例: `https://iwate-agencies.xxxx.workers.dev/status`）。`"latest"` に前回の実行の情報が出ていれば成功です。`upstream_error` と出る場合はトークンや変数の値を見直してください。

> 管理画面の項目名は Cloudflare 側の変更で多少変わることがあります。見つからない場合は「Workers」「変数」などで画面内を探してください。

### 3. 中継サーバーのURLを設定ファイルに書く

1. GitHub でこのリポジトリの [`docs/config.json`](docs/config.json) を開き、鉛筆アイコン（Edit）を押します。
2. `trigger_url` に手順2でコピーした Worker のURLを書きます（末尾の `/status` は付けません）。

   ```json
   {
     "trigger_url": "https://iwate-agencies.xxxx.workers.dev"
   }
   ```

3. **Commit changes** で main ブランチにコミットします。1〜2分で公開ページにボタンが表示されます。

ボタンを外したいときは `trigger_url` を `""`（空）に戻します（`via_proxy` の取得元も使えなくなります）。完全に止めるときは、Cloudflare で Worker を削除し、GitHub でトークンを削除（Developer settings → Fine-grained tokens → 対象のトークン → Delete）してください。

## 兄弟サイトへのナビ

各ページ（トップページ・アーカイブ）の一番上に細い帯のナビがあります。

- 左の「IWATE NEWS WATCH トップへ」は `https://iwate-news-watch.github.io/`（`/`）へのリンクです。
- 右には、同じドメインの `/sites.json` に載っている兄弟サイトへのボタン（ロゴの縮小表示＋名前）が並びます。このサイトのボタンは、sites.json の `color` で強調します（このサイトの `id` は `ginga`。`scripts/build.py` の `SITE_ID`）。
- sites.json は `[{...}, ...]` でも `{"sites": [{...}, ...]}` でも読めます。各サイトの項目は `id`・`name`・`url`・`logo`・`color` です。`url`・`logo` は `/test/` のような同じドメイン内のパスか http(s) の URL、`color` は `#1b2a6b` のような色の指定だけを使い、それ以外は無視します。
- sites.json を読めないときは「トップへ」のリンクだけを表示します。
- スマホ幅ではボタンの列が2段目に回り、入りきらない分は横にスクロールします（ページ全体は横にはみ出しません）。

## ロゴ

ロゴは `docs/ginga-logo-v2.svg` です（`scripts/build.py` の `LOGO_FILE`）。幅の広い画面（1400px以上）では右の余白に固定表示し、狭い画面では見出しの横に小さく表示します。ファイルが読めないときは表示しません。ロゴを差し替えるときは `docs/` に置き、`LOGO_FILE` にファイル名を書いてください。空文字（`""`）にするとロゴを表示しません。

## Worker の /proxy（GitHub Actions から取得できないサイト用）

`worker/worker.js` には、更新ボタン用の `/trigger`・`/status` のほかに `GET /proxy?url=…` があります。GitHub Actions から直接は遮断されるサイトのページを、Worker が代わりに取得して返します。

- 取得してよいのは許可したホストだけです（既定は `www.iwate-pu.ac.jp`）。それ以外の URL、ユーザー情報やポート番号つきの URL、許可外のホストへの転送（リダイレクト）は拒否します（踏み台に使われないようにするため）。
- 取得結果（HTTP 200 のもの）は5分間キャッシュし、同じページに短時間に何度もアクセスしないようにします。
- 応答には `X-Proxy-Cache`（HIT/MISS）・`X-Proxy-Final-Url`（転送後の URL）・`X-Proxy-Upstream-Status`・`X-Proxy-Upstream-Server` が付きます。
- 許可するホストを増やすときは、Worker の変数 `PROXY_ALLOWED_HOSTS` にカンマ区切りで書きます。**この変数を設定すると既定の `www.iwate-pu.ac.jp` は含まれなくなる**ので、必ず一緒に書いてください。コードの貼り直しは不要です。
  - 県の試験研究・普及機関（いわてアグリベンチャーネット・岩手県水産技術センター）が GitHub Actions から 403 になった場合は、次の値にします。

    ```
    www.iwate-pu.ac.jp,www.pref.iwate.jp,www2.suigi.pref.iwate.jp
    ```

  - 設定のしかた: Cloudflare のダッシュボードで Worker を開き、**Settings → Variables and Secrets → Add**、種類は **Text**、名前は `PROXY_ALLOWED_HOSTS`、値は上の文字列にして **Deploy** を押します。
  - そのあと、`sources.yaml`（または `survey_targets.yaml`）のその機関に `via_proxy: true` を付けます。
  - `www.pref.iwate.jp` は岩手県庁のサイト全体です。許可するのは必要になったときだけにしてください。

**`worker.js` を変更したとき**は、Cloudflare のダッシュボードで Worker の **Edit code** を開き、このリポジトリの `worker/worker.js` の全文を貼り直して **Deploy** を押してください（変数とシークレットはそのまま残ります）。

確認は、ブラウザで `https://ginga-trigger.iwate-news.workers.dev/proxy?url=https%3A%2F%2Fwww.iwate-pu.ac.jp%2F` を開きます。大学のトップページが表示されれば成功です。`url_not_allowed` と出たら、URL かホストの許可を見直してください。

> 注意: Worker が相手のサイトにアクセスするときの接続元は Cloudflare のデータセンターです。どのデータセンターで動くかは呼び出し元に近い場所で決まるため、GitHub Actions（米国）から呼ぶと米国のデータセンターになることがあります。相手のサイトが海外からのアクセスを遮断している場合は、Worker 経由でも 403 になる可能性があります（その場合は Inspect sources の診断で `Worker経由` が 403 になります）。
