# CP3000 波形ビューワー 配布パッケージ 設計計画書

Nov 5, 2026 · @Takahiro Hirano

## 1. 目的と範囲

Python を入れていない Windows PC でも、zip を展開して bat をダブルクリックするだけで CP3000 波形ビューワーを使えるようにします。Python 本体とライブラリを同梱した配布 zip を作り、社内の共有フォルダで配ります。

**対象**

- 配布 zip を作るビルドスクリプト(開発者が実行)
- 利用者用の起動 bat と更新 bat
- 配布と更新の手順、利用者向けの説明書

**対象外**

- アプリの機能(波形計算・画面)の変更
- 64 ビット以外の Windows、macOS
- 社内サーバーでの運用(必要になれば別途検討)

## 2. 前提と制約

現行のアプリは「Python が PATH にある」ことを前提にしています。アプリ本体はそのまま使えるため、変えるのは起動部分と配布の仕組みだけです。

| 項目 | 現状 | 配布への影響 |
| --- | --- | --- |
| アプリ形式 | Streamlit(`app.py` + `cp3000/`)。ブラウザで http://localhost:8510 を開く | そのまま使える |
| ライブラリ | streamlit・plotly・numpy・pandas(`requirements.txt`、下限のみ指定) | 配布用に版を固定する |
| 起動 | `run_viewer.bat` が初回に `.venv` を作り pip で導入 | Python もネット接続も不要な起動 bat を別に用意する |
| 設定の保存 | `settings.json` を `app.py` と同じフォルダに書く(親フォルダなど) | 更新で消えないようにする |
| デモデータ | 起動時に `demo_data/` がなければ作る | zip に作成済みを入れるか、初回に作る |
| バージョン表示 | 画面に `cp3000 v0.1.0` を表示済み(`cp3000/__init__.py`) | 更新の確認に使える |
| 開発 PC の Python | 3.14 | 配布用は 3.12 系に固定して互換性を優先 |

**利用者 PC の想定**

- Windows 10 / 11(64 ビット)。管理者権限はないものとする
- Python・git は入っていない
- インターネットには出られない前提で設計する(社内の共有フォルダには入れる)
- ブラウザは Edge または Chrome

## 3. 方式の選定

採用するのは「Windows 用 embeddable Python を同梱した zip」です。今の機能をすべて残せて、インストールもネット接続も不要だからです。

| 方式 | 利用者の操作 | フォルダ直接読込 | ネット接続 | 判定 |
| --- | --- | --- | --- | --- |
| embeddable Python 同梱 zip | 展開して bat | できる | 不要 | **採用** |
| exe 化(PyInstaller) | exe を起動 | できる | 不要 | 不採用:Streamlit と相性が悪く、ウイルス対策ソフトの誤検知が多い |
| 初回自動セットアップ(uv) | bat(初回数分) | できる | 初回必要 | 不採用:社内プロキシで止まる恐れ |
| 社内サーバー | URL を開く | 共有フォルダのみ | 社内 LAN | 将来の候補:サーバー管理者が必要 |
| ブラウザ内実行(stlite) | HTML を開く | 基本はできない | 初回必要な場合あり | 不採用:動作検証が大きい |

embeddable Python は python.org が配布する公式の「展開するだけで動く Python」です。レジストリや PATH を変更しないので、他のソフトに影響しません。

## 4. パッケージ構成

配布 zip は「ほぼ変わらない `runtime/`」と「更新する `app/`」と「利用者の設定 `user/`」の 3 つに分けます。こう分けると、更新のときに `app/` だけを差し替えられ、設定も消えません。

```
CP3000Viewer/
  start_viewer.bat        起動(利用者がダブルクリック)
  update_viewer.bat       更新(共有フォルダから最新版を取り込む)
  README.txt              利用者向けの使い方
  VERSION.txt             例: app=0.2.0 runtime=py3.12.10-r1
  runtime/                embeddable Python + ライブラリ(約 150〜250MB)
    python.exe
    python312._pth        読み込む場所の指定(下記)
    Lib/site-packages/    streamlit, plotly, numpy, pandas など
  app/                    アプリ本体(数百 KB)
    app.py
    cp3000/
    .streamlit/config.toml
    demo_data/            合成デモデータ(作成済み)
  user/                   利用者ごとの設定(更新で触らない)
    settings.json
```

| フォルダ | 中身 | 更新されるとき |
| --- | --- | --- |
| `runtime/` | Python 本体とライブラリ | Python やライブラリを上げるときだけ(zip を配り直す) |
| `app/` | アプリのコードとデモデータ | アプリを直したとき(更新 bat で差し替え) |
| `user/` | 親フォルダなどの設定 | 更新では触らない |

**`python312._pth` の中身**:embeddable Python はこのファイルに書いた場所だけからライブラリを読みます。`python312.zip`、`.`、`Lib\site-packages`、`..\app` の 4 行と `import site` を書きます。

**設定の保存先(要判断)**:現在の `app.py` は `settings.json` を `app/` に書きます。次のどちらかにします。

1. **推奨**:`app.py` を 2 行ほど直し、環境変数 `CP3000_SETTINGS` があればそのパスに保存する。起動 bat が `user\settings.json` を指定する。開発時の動きは変わらない
2. コードを直さず、更新 bat が `app\settings.json` を退避してから戻す

## 5. ビルド手順の設計

開発者が `tools/build_dist.py` を 1 回実行すると、`dist/` に配布 zip が 2 つできます。ビルドはネットにつながる開発 PC で行い、利用者 PC では何もダウンロードしません。

```
python tools\build_dist.py
```

**処理の流れ**

1. `cp3000/__init__.py` からアプリのバージョンを読む
2. python.org から `python-3.12.x-embed-amd64.zip` を取得する(`build/cache/` に保存して次回は再利用)。公開されている SHA-256 と照合し、合わなければ止める
3. `runtime/` に展開し、`python312._pth` を書き換える
4. ライブラリを `runtime/Lib/site-packages/` に入れる。開発 PC の pip で Windows 64 ビット・ Python 3.12 用の wheel だけを指定して入れるので、runtime 側に pip は入れない
   - `pip install --target runtime\Lib\site-packages --python-version 3.12 --platform win_amd64 --only-binary=:all: -r requirements-lock.txt`
5. 不要なもの(ライブラリ同梱のテストなど)を削り、`compileall` で事前にコンパイルして初回起動を速くする
6. `app.py`・`cp3000/`・`.streamlit/config.toml` を `app/` にコピーし、runtime の Python で `demo_data/` を作る
7. 起動 bat・更新 bat・`README.txt`・`VERSION.txt` を置く
8. 自動の動作確認:runtime の Python で全ライブラリを import し、Streamlit を置き場で起動して `/_stcore/health` が応答することを確かめて止める
9. zip を 2 つ作る

| 成果物 | 中身 | 用途 | 目安サイズ |
| --- | --- | --- | --- |
| `CP3000Viewer_<版>_full.zip` | フォルダ一式 | 初回配布、runtime 更新時 | 60〜90MB(展開後 150〜250MB) |
| `CP3000Viewer_app_<版>.zip` | `app/` と bat 類 | 更新 bat が取り込む | 1MB 未満 |

**リポジトリに追加するもの**

- `tools/build_dist.py`:ビルドスクリプト
- `requirements-lock.txt`:配布用に版を固定したライブラリ一覧(Python 3.12 の付き添い環境で `pip freeze` して作る)
- `dist_files/`:配布用の bat・README の原本
- `.gitignore` に `dist/` と `build/` を追加(zip と Python 本体は git に入れない)

## 6. 起動の設計

`start_viewer.bat` は同梱の Python だけを使い、自分の PC からしか接続できない設定で Streamlit を起動します。外から接続できないので、Windows ファイアウォールの許可画面(管理者権限が必要)も出ません。

**起動 bat の動き**

1. bat のあるフォルダを基準にする(空白や日本語を含むパスでも動くようにすべて引用符で囲む)
2. `runtime\python.exe` がなければメッセージを出して止める(zip を展開せずに開いた場合の対策)
3. 環境変数を設定する
   - `CP3000_SETTINGS` = `user\settings.json`(設定の保存先)
   - `PYTHONNOUSERSITE=1`(PC に別の Python があっても影響を受けない)
4. ポート 8510 がすでに使われていれば、ビューワーは起動済みとみなし、ブラウザだけ開いて終わる
5. `runtime\python.exe -m streamlit run app\app.py --server.address 127.0.0.1 --server.port 8510` で起動する
6. 応答を待ってから既定のブラウザで http://localhost:8510 を開く(現行の「4 秒待つ」より確実)
7. 黒い画面に「この画面を閉じるとビューワーが終了します」と表示する

| 利用者がこうなったとき | bat の対応 |
| --- | --- |
| zip の中で bat を開いた | 「先に zip をすべて展開してください」と表示して止める |
| 2 回ダブルクリックした | 2 つ目は起動せず、ブラウザだけ開く |
| ブラウザを閉じてしまった | もう一度 bat を開くか、http://localhost:8510 を開く |
| 起動に失敗した | エラー内容を `user\last_error.log` に残し、画面を閉じずに止める |

**置き場所のおすすめ**:`C:\Users\<名前>\CP3000Viewer` など、OneDrive で同期されないフォルダ。同期フォルダに置くと数千個以上のファイルが同期され、動きも遅くなります。

## 7. 配布と更新の設計

配布は社内の共有フォルダで行い、更新は利用者が `update_viewer.bat` をダブルクリックして取り込みます。普段は 1MB 未満のアプリ部分だけを差し替え、Python やライブラリを上げたときだけ zip 全体を配り直します。

&#91;embedded content: 配布と更新の流れ · 開発 PC → 共有フォルダ → 利用者 PC\]

利用者は初回だけ full zip を展開し、以降は update\_viewer.bat が latest.txt を見て app zip を取り込みます。

**共有フォルダの構成**

```
\\<サーバー>\<共有>\CP3000Viewer\
  latest.txt                      最新版の番号(例: app=0.2.0 runtime=py3.12.10-r1)
  CHANGELOG.txt                   変更内容
  CP3000Viewer_0.2.0_full.zip     初回・runtime 更新用
  CP3000Viewer_app_0.2.0.zip      更新 bat 用
  old\                            過去の版(戻すときに使う)
```

**バージョンの付け方**

- アプリ:`cp3000/__init__.py` の `__version__`(例 0.2.0)。画面にも表示される。公開ごとに git のタグ `v0.2.0` を付ける
- runtime:Python の版 + ライブラリ構成の通し番号(例 py3.12.10-r1)。`requirements-lock.txt` を変えたら r を上げる

**`update_viewer.bat` の動き**(中身は同梱の Python で動く小さなスクリプト)

1. 共有フォルダの場所を `user\update_source.txt` から読む(初期値はビルド時に書き込む)
2. `latest.txt` と手元の `VERSION.txt` を比べる
3. 同じなら「最新です」と表示して終わる
4. runtime が違うなら「全体の入れ替えが必要です」と表示し、共有フォルダをエクスプローラーで開く
5. アプリだけ違うなら、ビューワーが動いていないことを確かめてから差し替える
   - 新しい app zip を一時フォルダに展開 → `app` を `app_old` に改名 → 新しい `app` を置く → `VERSION.txt` を更新 → `app_old` を消す
   - 途中で失敗したら `app_old` を戻し、元の状態で終わる
6. `user/` には触れない

**公開の手順(開発者)**

1. `__version__` を上げ、`CHANGELOG.txt` を書く
2. テストを通し、タグを付ける
3. `build_dist.py` で zip を作り、共有フォルダにコピーする
4. **最後に** `latest.txt` を書き換える(zip のコピー途中に利用者が更新しても壊れない)
5. 利用者に更新を知らせる(メールやチャット)

任意の追加機能として、起動 bat が `latest.txt` を見て「新しい版があります」と表示することもできます(自動更新はしない)。

## 8. テスト計画

開発 PC には Python が入っているため、「Python なしで動くか」は Python の入っていない PC(または Windows サンドボックス)で必ず確かめます。

| # | 確認内容 | 場所 | 担当 |
| --- | --- | --- | --- |
| 1 | 既存のテスト(`tests/test_viewer.py`)が runtime の Python 3.12 で通る | 開発 PC | Claude |
| 2 | ビルドが最後まで通り、自動の動作確認(import・起動・応答)が成功する | 開発 PC | Claude |
| 3 | PATH から Python を外した状態で `start_viewer.bat` が動く | 開発 PC | Claude |
| 4 | zip を展開して起動し、デモデータの波形が表示される | Python なし PC | 利用者側 |
| 5 | 実データの親フォルダ(例 `E:\CWA\data\raw`)を開け、開発版と同じ Te / Tc が出る | Python なし PC | 利用者側 |
| 6 | 空白や日本語を含むフォルダに置いても起動できる | Python なし PC | 利用者側 |
| 7 | ウイルス対策ソフトやファイアウォールの警告が出ない | Python なし PC | 利用者側 |
| 8 | 設定(親フォルダ)を変え、更新 bat で新しい版を入れても設定が残る | 両方 | Claude → 利用者側 |
| 9 | ビューワー起動中に更新 bat を開くと、終了を促して何も変えない | 開発 PC | Claude |
| 10 | 更新の途中で失敗させても元の版で起動できる | 開発 PC | Claude |

\#5 の「開発版と同じ結果」は、同じフォルダを開発版と配布版で開き、一覧の CSV を比べて確かめます。

## 9. リスクと対策

いちばん大きいリスクは、社内のセキュリティ設定で bat や同梱の `python.exe` の実行が止められることです。開発を進める前に、10 章の手順 0「事前確認」で確かめます。

| リスク | 影響 | 対策 |
| --- | --- | --- |
| 社内ポリシー(AppLocker など)でユーザーフォルダの exe が実行できない | 起動できない | 開発前に公式の embeddable Python だけを置いて `python.exe` が動くか確認。動かなければ情報システム部門に許可を依頼するか、社内サーバー方式に切り替える |
| ウイルス対策ソフトが同梱ファイルを削除・隔離する | 起動できない | python.org の公式配布物をそのまま使う(独自の exe を作らない)。起きたら例外登録を依頼 |
| bat の日本語メッセージが文字化けする | 表示が読めない | bat は Shift-JIS(CP932)で保存する。入り組んだ処理は bat に書かず Python のスクリプトに寄せる |
| ライブラリが Python 3.12 用の wheel を出さなくなる | ビルドできない | `requirements-lock.txt` で版を固定。Python を上げるときは runtime の版を上げて full zip を配り直す |
| embeddable Python で Streamlit がアプリのフォルダを見つけられない | `import cp3000` で失敗 | `._pth` に `..\app` を書く。ビルド時の自動確認で検出する |
| 利用者が古い版を使い続ける | 計算結果が人により異なる | 画面に版を表示済み。起動時の「新しい版があります」表示を入れるか検討 |
| Python 3.12 のサポート終了(2028 年 10 月予定) | セキュリティ修正が止まる | それまでに runtime を新しい Python に入れ替える(このアプリは外部から接続されないため緊急度は低い) |

## 10. 作業計画と未決事項

Claude の作業は合計 2〜3 時間、利用者側の確認は合計 30〜45 分が目安です。先に手順 0 で「社内 PC で同梱 Python が動くか」だけを確かめ、動かなければ方式を見直します。

| 手順 | 内容 | 担当 | 目安 |
| --- | --- | --- | --- |
| 0 | 事前確認:Python なし PC に公式 embeddable Python を展開し、`python.exe -c "print(1)"` が動くか確かめる | 利用者側 | 15 分 |
| 1 | 設定の保存先を環境変数で切り替えられるようにする(`app.py` を 2 行ほど) | Claude | 15 分 |
| 2 | `requirements-lock.txt` を作る(Python 3.12 で版を固定) | Claude | 15 分 |
| 3 | `tools/build_dist.py` を作る(5 章) | Claude | 45〜60 分 |
| 4 | `start_viewer.bat`・`update_viewer.bat`・更新スクリプト・`README.txt` を作る(6・7 章) | Claude | 30〜45 分 |
| 5 | 開発 PC でのテスト(8 章 #1〜3・8〜10) | Claude | 20〜30 分 |
| 6 | Python なし PC でのテスト(8 章 #4〜8) | 利用者側 | 15〜30 分 |
| 7 | 共有フォルダに初版を置き、利用者に知らせる | 開発者 | 15 分 |

**未決事項**

- [ ] 配布に使う共有フォルダの場所(`\\<サーバー>\<共有>`)
- [ ] 設定の保存先:`app.py` を少し直す推奨案でよいか(4 章)
- [ ] 利用者の PC がすべて 64 ビット Windows 10 / 11 か
- [ ] 社内でソフトを配るときに申請や承認が必要か
- [ ] 起動時の「新しい版があります」表示を入れるか
- [ ] 既存の `run_viewer.bat`(開発者向け)はそのまま残すか
