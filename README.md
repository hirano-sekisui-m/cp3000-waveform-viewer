# CP3000 波形ビューワー

CP3000 の生データ 3 種類(`prof*.dat`・`*CSV_data.csv`・`LOG*.dat`)を読み、凝固波形をブラウザで確認するアプリです。
CWA-ML-tool から、生データの読込と波形計算の部分だけを切り出しています(出典は下記)。

## 起動

`run_viewer.bat` をダブルクリックします。初回だけ `.venv` を作って必要なライブラリを入れます。
ブラウザで http://localhost:8510 が開きます。

手動で起動する場合:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

データなしで試す場合は、合成データを作ってから起動します(値はすべて架空)。

```bat
.venv\Scripts\python tools\make_demo_batch.py
```

## できること

| 画面 | 内容 |
|---|---|
| サイドバー「データ」 | 親フォルダ(例 `E:\CWA\data\raw`)を指定すると、`prof*.dat` を含むフォルダ(3 階層まで)を一覧します。ファイルのアップロードでも開けます。 |
| 重ね描き | 一覧で選んだ波形(Ctrl / Shift で複数)を重ねて表示。生波形・凝固波形(最大=100% / 終点=100%)・速度波形・加速度波形を、時間軸をそろえたパネルで縦に並べます。時間軸は Tc2・速度ピーク・立ち上がり 10% でそろえられます。表示中の波形は CSV で保存できます。 |
| 1波形の詳細 | 4 種類の波形を全点で表示し、Te1 / Tc1 / Te2 / Tc2 と装置の測定値(CSV)を重ねます。前後の波形へ移動できます。 |
| 一覧・読み込み情報 | 全波形の一覧(CSV 保存可)、読んだファイル、CSV にあって波形が見つからない測定。 |

- CSV・LOG はなくても開けます。prof だけのときは 内部依頼No・項目番号 で表示します(CSV と prof の対応づけには LOG が必要です)。
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
app.py                  Streamlit アプリ
cp3000/
  prof.py               prof*.dat の読込(3600 / 6000 点を自動判定)
  log.py                LOG*.dat の解析(依頼情報・サンプリング情報)
  batch.py              CSV の読込と 3 ファイルの突合、フォルダの探索
  signal.py             移動平均・累積・速度・加速度、Te/Tc
  plots.py              Plotly の図
dist_files/
  start_viewer.bat      配布パッケージ用の起動 bat(Shift-JIS)
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
