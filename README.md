# CP3000 波形ビューワー

CP3000 の生データ 3 種類(`prof*.dat`・`*CSV_data.csv`・`LOG*.dat`)を読み、凝固波形をブラウザで確認するアプリです。
CWA-ML-tool から、生データの読込と波形計算の部分だけを切り出しています(出典は下記)。

## 起動

本アプリは、**React + FastAPI の 3層構成（新UI）** と **従来の Streamlit 版** の両方に対応しています。

### 1. React + FastAPI 版（新UI・推奨）

#### ターミナルから起動する場合

Windows のターミナル（PowerShell またはコマンド プロンプト）を、リポジトリのルートフォルダで開いて実行します。

初めてソースを取得したときは、React の画面をビルドしてください（Node.js 18 以上が必要です）。`npm ci` は初回のみ実行し、画面コード (`web/src/`) を変更したときは `npm run build` で再ビルドします。

```bat
cd web
npm ci
npm run build
cd ..
```

準備ができたら、次のコマンドで起動します。

```bat
.\run_viewer_react.bat
```

初回は Python 3.10 以上が必要です。この bat が `.venv` の作成と Python ライブラリのインストールを行います。ブラウザで **http://localhost:8000** を開きます（API ドキュメントは http://localhost:8000/docs）。終了するにはターミナルで `Ctrl+C` を押します。bat をダブルクリックしても起動できます。

#### Python コマンドで直接起動する場合

上記のReact画面のビルドと Python ライブラリのインストールが済んでいる場合は、次のコマンドでも起動できます。

```bat
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```
ブラウザで **http://localhost:8000** を開きます。終了するには `Ctrl+C` を押します。

#### フロントエンド開発モード (React のホットリロード)
画面コードを編集しながら即座にブラウザ反映（HMR）させたい場合は、Node.js 18 以上を用意し、ターミナルを 2 つ開いて実行します。`npm ci` は `web` フォルダで初回のみ実行してください。

- **ターミナル 1 (API サーバー):**
  ```bat
  .\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
  ```
- **ターミナル 2 (Vite 開発サーバー):**
  ```bat
  cd web
  npm run dev
  ```
ブラウザで **http://localhost:5173** を開きます（API リクエストはポート 8000 へ自動中継されます）。

---

### 2. Streamlit 版（従来UI）

ターミナルをリポジトリのルートフォルダで開いて、次を実行します。
```bat
.\run_viewer.bat
```
初回は Python 3.10 以上が必要です。この bat が `.venv` の作成と Python ライブラリのインストールを行います。ブラウザで **http://localhost:8510** を開きます。終了するには `Ctrl+C` を押します。bat をダブルクリックしても起動できます。

---

データなしで試す場合は、合成データを作ってから起動します(値はすべて架空)。

```bat
.venv\Scripts\python tools\make_demo_batch.py
```


## できること

| 画面 | 内容 |
|---|---|
| サイドバー「データ」 | 親フォルダ(例 `E:\CWA\data\raw`)を指定すると、`prof*.dat` または `*CSV_data.csv` を含むフォルダ(3 階層まで)を一覧します。ファイルのアップロードでも開けます。 |
| 重ね描き | 一覧で選んだ波形(Ctrl / Shift で複数)を重ねて表示。生波形・凝固波形(最大=100% / 終点=100%)・速度波形・加速度波形を、時間軸をそろえたパネルで縦に並べます。時間軸は Tc2・速度ピーク・立ち上がり 10% でそろえられます。表示中の波形は CSV で保存できます。 |
| 1波形の詳細 | 4 種類の波形を全点で表示し、Te1 / Tc1 / Te2 / Tc2 と装置の測定値(CSV)を重ねます。前後の波形へ移動できます。 |
| 一覧・読み込み情報 | 全波形の一覧(CSV 保存可)、読んだファイル、CSV にあって波形が見つからない測定。 |

- CSV・LOG はなくても開けます。prof だけのときは 内部依頼No・項目番号 で表示します(CSV と prof の対応づけには LOG が必要です)。
- `*CSV_data.csv` 単独(prof・LOG なし)でも開けます。CSV 第2セクションの `ﾌﾟﾛﾌｧｲﾙ`(簡易タイムコース。測定モードに応じた各レコードの秒間隔・時間軸をそのまま使用)を読み込み、依頼No・属性・項目名とともに波形と計算値を表示します。
- 色は 8 色を固定順で使います。9 本以上を重ねるときは、項目名・属性などのグループで色分けします(色の使い回しはしません)。
- 生データのフォルダには何も書き込みません。元の CWA-ML-tool の merger は LOG の隣に `LOG展開後.xlsx` を作りますが、このアプリは LOG をメモリ上で解析します。

## 計算の内容

CWA-ML-tool の 01 バッチ(`cwa.signal.derive.derive_waveforms`)と同じ手順です。

1. 生波形(0.1 秒間隔。最初の 0 の手前までが測定値)
2. 移動平均(前 4・後 4 点)→ 隣接差分 → 移動中央値(±20 点)→ 累積(0 で下限)
3. Te/Tc の探索(前後 20 点の和の比 < 1.05、累積 ≥ 250、15 秒以降、Te/Tc ≤ 1.8)。Tc は累積が終点の 50% に達した時刻
4. 最大 = 100% に規格化 → 速度波形(±10 点の回帰の傾き)→ 加速度波形(速度波形の傾き)

サイドバーの「計算の設定」で、解析窓(生波形を切る秒数)と Tc の判定割合を変えられます。

## フォルダ構成

```
web/                    React + TypeScript (画面UI層)
  src/                  React コンポーネント・チャート描画
  dist/                 本番用静的ビルド成果物
api/                    FastAPI (薄い API 層)
  routes/               エンドポイント (バッチ・波形計算・エクスポート・設定)
  schemas/              Pydantic リクエスト/レスポンスモデル
  services/             セッション・インメモリキャッシュ管理
cp3000/                 計算コア (波形計算・ファイル読込)
  prof.py               prof*.dat の読込(3600 / 6000 点を自動判定)
  log.py                LOG*.dat の解析(依頼情報・サンプリング情報)
  batch.py              CSV の読込と 3 ファイルの突合、フォルダの探索
  signal.py             移動平均・累積・速度・加速度、Te/Tc
  plots.py              Plotly の図 (Streamlit 用)
legacy/                 旧 Streamlit アプリ関連 (app.py, run_viewer.bat, .streamlit)
run_viewer_react.bat    React + FastAPI 版の起動 bat
dist_files/
  start_viewer.bat      配布パッケージ用の起動 bat (FastAPI + React 配信)
  update_viewer.bat     配布パッケージ用の更新 bat(Shift-JIS)
  viewer_ctl.py         起動・ヘルスチェック・差分更新スクリプト
  README.txt            利用者向けの使い方説明書
requirements-lock.txt   配布パッケージ用の固定ライブラリ一覧(Python 3.12 / win_amd64)
tools/
  build_dist.py         Python 同梱配布パッケージ(zip)のビルドスクリプト
  make_demo_batch.py    合成バッチの作成
  check_against_cwa.py  元の CWA-ML-tool のコードと結果が一致するかの確認
tests/
  test_viewer.py        波形読込・計算・画面表示のテスト(合成データのみ)
  test_api.py           FastAPI エンドポイント・SPA 配信のテスト
  test_dist.py          配布パッケージ・起動 bat・更新 bat のテスト
```


テスト: `.venv\Scripts\python -m pytest tests -v -p no:cacheprovider`

## 配布パッケージのビルド(Python 不要の Windows 64 ビット向け)

Python をインストールしていない PC 向けに、embeddable Python 3.12 とライブラリ一式を同梱した配布 zip を作成できます。

```bat
.venv\Scripts\python tools\build_dist.py
```

`dist/` に以下のファイルが出力されます:

- `CP3000Viewer_<版>_full.zip`: 初回配布・runtime 更新用(展開して `start_viewer.bat` をダブルクリックするだけで起動)
- `CP3000Viewer_app_<版>.zip`: アプリ更新用(`update_viewer.bat` が取り込む軽量パッケージ)
- `latest.txt`: 共有フォルダに置く最新版情報

## 出典(CWA-ML-tool、commit a591105)

| このアプリ | 元のファイル | 変更 |
|---|---|---|
| `cp3000/prof.py` | `src/cwa/ingestion/prof.py` | なし(docstring のみ) |
| `cp3000/log.py` | `src/cwa/log_parser.py` | 行の解析はそのまま。Excel に書く代わりに DataFrame を返す |
| `cp3000/batch.py` | `src/cwa/ingestion/merger.py` | 文字列処理・`read_csv_sections`・`canonicalize_csv_attr_columns`・`csv_build_item_master` はそのまま。`read_log_key` の規則はそのまま DataFrame 入力に。突合は prof を基準に組み直し(CSV に対応のない波形も残す)。属性列のない CSV も読める |
| `cp3000/signal.py` | `src/cwa/signal/{filters,cumulative,slope}.py`、`src/cwa/coagulation/{tetc,trimming}.py`、`src/cwa/plotting/waveforms.py` の `align_waveform_time` | 関数はそのまま(特徴量レジストリのデコレータのみ削除)。`derive_batch` は `src/cwa/signal/derive.py` の手順を配列向けにしたもの。加速度は `src/cwa/signal/waveform_viewer_service.py` と同じく速度波形の傾き |

`tools/check_against_cwa.py` で、突合結果(依頼No・SID・項目名・測定値・全点の波形)と、0–100% 波形・速度・加速度・Te/Tc が元のコードと一致することを確認しています(合成バッチ 2 件、解析窓あり / なし)。
