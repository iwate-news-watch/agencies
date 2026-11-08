# NAMBU 岩手県市町村新着情報

岩手県内33市町村の新着行政情報を集めて、GitHub Pages に日ごとの一覧として公開する仕組みです。

- 取得: RSS/Atom フィード（30市町村）と、RSSのない3町（紫波町・矢巾町・軽米町）のスクレイピング
- 実行: 定期実行はしません。公開ページの「今すぐ更新」ボタンか、GitHub の Actions 画面からの手動実行で取得し、結果をこのリポジトリにコミット
- 表示: 取得した日ごとに自治体別の一覧。スマホで読みやすいレイアウト、ダークモード対応、前後の日への移動と過去30日分のアーカイブ付き

```
.
├── sources.yaml               # 取得元の一覧（ここを編集する）
├── scripts/build.py           # 取得・新着判定・HTML生成
├── requirements.txt
├── state/
│   ├── seen.json              # 既出記事のURL（90日より古い記録は自動削除）
│   └── daily/YYYY-MM-DD.json  # 日ごとの一覧データ（直近30日分）
├── docs/
│   ├── index.html             # 公開ページ（最新の日の一覧）
│   ├── config.json            # 更新ボタンの設定（中継サーバーのURL）
│   ├── search.json            # 過去30日分の記事タイトル検索用データ（自動生成）
│   └── archive/YYYY-MM-DD.html  # 日別アーカイブ（直近30日分）
├── worker/worker.js           # 更新ボタン用の中継サーバー（Cloudflare Workers）
└── .github/workflows/daily.yml  # 取得・ページ生成のワークフロー（手動実行のみ）
```

## 新着の判定と日ごとの一覧

- 取得した記事のURLを `state/seen.json` と照合し、未登録のものを「新着」として表示します。
- 初回の取得では記録だけを行い、ページに「初回のため記録のみ」と表示します。あとから取得元を追加した場合も、その取得元の初回は記録だけになります（既存記事がまとめて新着扱いになるのを防ぐため）。
- 前回の取得から増えた記事は、すべて**取得した日**の一覧に入ります。記事の掲載日では振り分けません（掲載日は各記事の上に表示します）。
- 同じ日に何回取得しても、その日の一覧に追加していきます。一覧は自治体ごとにまとまっていて、各自治体の中では新しく取得した記事ほど上に並びます。
- トップページはいちばん新しい日の一覧です。見出しは「2026年10月15日の更新」、その下にその日の最後の取得時刻（「最終取得 16:05」）を表示します。
- トップページの一番上には「最新の取得で増えた記事」の枠があり、直近1回の取得で新しく見つかった記事だけを取得時刻・件数とともに自治体ごとに表示します。増えた記事がなければ「前回から新しい記事はありません」と表示します。その下に、その日のそれ以外の記事を自治体ごとに表示します（最新の取得分とは重複しません）。アーカイブの過去の日のページは1つの一覧のままです。
- 各ページに自治体の「並び替え・絞り込み」パネルがあります（PCでは画面左に常に表示、スマホでは「並び替え・絞り込み」ボタンで開閉）。並び替えは地域順（県央・県南・沿岸・県北、初期値）・新着件数順・五十音順、絞り込みは自治体ごとのチェックと地域ごとの「すべて選択／解除」です。選んだ設定はブラウザに保存され、次回も同じ状態で表示されます。地域区分と読みは `scripts/build.py` の `REGIONS` にあります。
- パネルの一番上には記事タイトルの検索窓があります。入力するとその場で記事を絞り込み、一致部分をハイライトします（スペース区切りはAND検索、全角半角・大文字小文字は区別しません）。自治体の絞り込みと組み合わせて使えます。「過去30日分も検索」をオンにすると、アーカイブを含めた結果を日付・自治体名つきで一覧表示します（新しい順に最大200件）。検索用データは取得のたびに `docs/search.json` に出力されます。検索語は保存しません。
- 記事一覧の自治体名の見出しと、「更新なし」などに並ぶ自治体名は、その自治体の公式ホームページへのリンクです（別タブで開きます）。URLは `sources.yaml` の最初の取得元URLのドメインのトップ（`https://ドメイン/`）で、自治体ごとに `homepage:` を書くと上書きできます。
- 各ページの上部に前の日・次の日へのリンク（取得のあった日どうしをつなぎます）、下部に過去30日分のアーカイブへのリンクがあります。
- 取得に失敗した自治体は、その日の最後の取得で失敗していれば一覧の先頭に赤く「取得エラー」と表示されます。ほかの自治体の処理は続行します。

## 取得元の追加・変更方法

`sources.yaml` を編集して main ブランチにコミットするだけです。次回の取得から反映されます。

**RSS / Atom フィードの場合**

```yaml
  - name: 盛岡市
    sources:
      - type: rss
        url: https://www.city.morioka.iwate.jp/news.rss
```

- Atom フィードも `type: rss` で読めます。
- 1つの自治体に複数のフィードを並べられます。同じ記事が複数のフィードにあっても、URLが同じなら1件にまとめます。

```yaml
  - name: 釜石市
    sources:
      - type: rss
        url: https://www.city.kamaishi.iwate.jp/category/kubun/news/index.rss
      - type: rss
        url: https://www.city.kamaishi.iwate.jp/category/kubun/event/index.atom
```

**RSS のないサイト（スクレイピング）の場合**

ページ内で日付を見つけ、その直後に出てくる最初のリンクを記事のタイトルとURLとして扱います。

```yaml
  - name: 紫波町
    sources:
      - type: scrape
        url: https://www.town.shiwa.iwate.jp/news/
        date_format: dotted       # 「2026.10.15」形式
        # selector: "#news-list"  # （任意）記事一覧部分だけを対象にするCSSセレクタ
```

| `date_format` | 日付の書式 | 例 |
|---|---|---|
| `dotted` | 西暦をドットで区切る | `2026.10.15` |
| `reiwa` | 令和（令和N年 = 西暦 2018+N 年） | `令和8年 10月15日`（空白入り・全角数字も可） |

- メニューやバナーのリンクまで拾ってしまう場合は、`selector` で記事一覧の部分を指定してください。
- 日付が読めない記事も取りこぼさず、日付欄を空にして表示します。

**取得元をやめる・一時的に止める場合**

その自治体の `sources:` を `sources: []` にすると、ページに「取得元未設定」と表示されます。

**ローカルで試す場合**

```bash
pip install -r requirements.txt
python scripts/build.py
```

`state/` と `docs/` が更新されます。試した結果をコミットしたくない場合は `git checkout -- state docs` で元に戻してください。

## GitHub Pages の有効化手順

1. この仕組みのファイルを **main ブランチにマージ**します（ワークフローの実行や更新ボタンは main ブランチを対象にします）。
2. GitHub のリポジトリ画面で **Settings → Pages** を開きます。
3. 「Build and deployment」の **Source** で「**Deploy from a branch**」を選びます。
4. **Branch** で「`main`」と「`/docs`」を選び、**Save** を押します。
5. 1〜2分ほどで、画面上部に公開URL（`https://<ユーザー名>.github.io/<リポジトリ名>/`）が表示されます。
6. **Settings → Actions → General** の「Workflow permissions」が「Read and write permissions」になっているか確認します（ワークフロー側でも `contents: write` を指定していますが、組織の設定で制限されている場合はここを変更してください）。

> 補足: 無料プランでは、GitHub Pages を使えるのは公開（Public）リポジトリのみです。また main ブランチに保護ルール（直接 push の禁止など）があると、ワークフローの自動コミットが失敗します。

## 手動で実行する方法

1. リポジトリ画面の **Actions** タブを開きます。
2. 左の一覧から「**Iwate municipal news**」を選びます。
3. 右側の「**Run workflow**」を押し、ブランチが `main` になっていることを確認して、緑の「**Run workflow**」を押します。
4. 数分で完了し、`state/` と `docs/` の更新が自動でコミットされます。その後1〜2分で公開ページに反映されます。

失敗した場合は、実行結果の「Build pages」ステップのログに、取得元ごとの `[OK]` / `[ERROR]` が出力されています。

## 同時に実行されたときの扱い

- 取得は手動実行（更新ボタン・Actions 画面）だけですが、Actions 画面からの実行は更新ボタンの制限を通らないため、重なることがあります。
- ワークフローは `concurrency`（グループ `daily-news`）で、同時に1つだけ動きます。実行中に次の実行が来た場合はキャンセルせず、前の実行が終わるまで待ちます。
- 待っていた実行も、その時点の最新の main から始めます（前の実行の結果を取り込んだ状態で新着を判定します）。
- push の前に `git pull --rebase` で最新の main を取り込みます。失敗した場合は間隔をあけて最大5回までやり直します。
- 注意: GitHub の仕様で、待機できるのは1件だけです。待機中の実行がある状態でさらに別の実行が来ると、古いほうの待機中の実行は GitHub によってキャンセルされます（新しいほうが実行されるので、取得自体は行われます）。更新ボタンは実行中・待機中には受け付けないため、通常はこの状況になりません。

## 公開ページの「今すぐ更新」ボタン

公開ページの上部に、誰でもログインなしで押せる更新ボタンを付けられます。ボタンを押すと、中継サーバー（Cloudflare Workers）が GitHub Actions のワークフローを実行します。GitHub のトークンは中継サーバーだけが持ち、公開ページには含まれません。

- 前回の実行開始から15分以内、または実行中・待機中は受け付けず、「次に更新できるのは◯時◯分です」と表示します。
- 受け付けると「受け付けました。5分ほどで反映されます」と表示します。完了すると再読み込みを促す表示が出ます。
- ページ上部の「最終取得」の下に、ワークフローの実行状態（実行待ち・実行中・成功・失敗）を表示します。
- 中継サーバーのURLを設定しないうちは、ボタンと実行状態は表示されません（取得は Actions 画面からの手動実行だけになります）。

設定は次の3ステップです。すべてスマホのブラウザでできます。

### 1. GitHub のトークンを作る

1. GitHub にログインし、右上のアイコン → **Settings** を開きます。
2. 左メニュー（スマホでは下のほう）の **Developer settings** → **Personal access tokens** → **Fine-grained tokens** を開き、**Generate new token** を押します。
3. 次のように入力します。
   - **Token name**: 分かりやすい名前（例: `iwate-news-button`）
   - **Expiration**: 有効期限（期限が切れたら作り直して、手順2の `GITHUB_TOKEN` を入れ替えます）
   - **Resource owner**: 自分のアカウント
   - **Repository access**: **Only select repositories** を選び、このリポジトリだけを選択
   - **Permissions** → **Repository permissions** → **Actions** を **Read and write** に変更（Metadata の Read-only は自動で付きます。ほかは変更不要）
4. **Generate token** を押し、表示された `github_pat_...` で始まる文字列をコピーします。**この画面を閉じると二度と表示されない**ので、次の手順まで控えておいてください。

> トークンはこのリポジトリのワークフローの実行・状態確認だけができる権限です。コードの書き換えはできません。リポジトリのファイルやチャットなどには絶対に貼り付けないでください。

### 2. Cloudflare Workers に中継サーバーを作る

1. スマホのブラウザで https://dash.cloudflare.com/ を開き、Cloudflare アカウントでログインします（無料プランで使えます）。
2. メニューから **Workers & Pages**（「Compute (Workers)」と表示される場合もあります）を開き、**Create**（作成）→ **Worker** の **Start with Hello World!** を選びます。
3. Worker の名前を入力（例: `iwate-news`）して **Deploy** を押します。
4. 作成後の画面で **Edit code**（コードを編集）を押します。
5. 別のタブでこのリポジトリの [`worker/worker.js`](worker/worker.js) を開き、**Raw** 表示にして全文をコピーします。
6. Worker のエディタに最初から入っているコードをすべて消して、コピーした内容を貼り付け、**Deploy** を押します。
7. Worker の画面に戻り、**Settings**（設定）→ **Variables and Secrets**（変数とシークレット）→ **Add**（追加）で、次の5つを登録します。

   | 名前 | 種類 | 値の例 |
   |---|---|---|
   | `GITHUB_OWNER` | Text（テキスト） | `nowakinowaki` |
   | `GITHUB_REPO` | Text | `test` |
   | `WORKFLOW_FILE` | Text | `daily.yml` |
   | `ALLOWED_ORIGIN` | Text | `https://nowakinowaki.github.io` |
   | `GITHUB_TOKEN` | **Secret（シークレット）** | 手順1でコピーしたトークン |

   - `ALLOWED_ORIGIN` は公開ページのURLの「`https://〜.github.io`」の部分だけです（末尾の `/` やリポジトリ名は付けません）。ここに書いたページからしかボタンが使えません。
   - `GITHUB_TOKEN` は必ず **Secret** を選んでください（保存後は値が見えなくなります）。
8. 保存（**Deploy**）します。
9. Worker のURL（`https://iwate-news.<あなたのサブドメイン>.workers.dev` のような形）をコピーします。
10. 動作確認として、ブラウザでそのURLの末尾に `/status` を付けて開きます（例: `https://iwate-news.xxxx.workers.dev/status`）。`"latest"` に前回の実行の情報が出ていれば成功です。`upstream_error` と出る場合はトークンや変数の値を見直してください。

> 管理画面の項目名は Cloudflare 側の変更で多少変わることがあります。見つからない場合は「Workers」「変数」などで画面内を探してください。

### 3. 中継サーバーのURLを設定ファイルに書く

1. GitHub でこのリポジトリの [`docs/config.json`](docs/config.json) を開き、鉛筆アイコン（Edit）を押します。
2. `trigger_url` に手順2でコピーした Worker のURLを書きます（末尾の `/status` は付けません）。

   ```json
   {
     "trigger_url": "https://iwate-news.xxxx.workers.dev"
   }
   ```

3. **Commit changes** で main ブランチにコミットします。1〜2分で公開ページにボタンが表示されます。

ボタンを外したいときは `trigger_url` を `""`（空）に戻します。完全に止めるときは、Cloudflare で Worker を削除し、GitHub でトークンを削除（Developer settings → Fine-grained tokens → 対象のトークン → Delete）してください。
