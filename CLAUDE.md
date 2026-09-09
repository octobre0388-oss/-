# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 誰が、何のために使う道具か

このリポジトリのオーナーは、**フランス在住 40 年の、ワインとパティスリーを専門とするジャーナリスト**。
毎月、関連媒体に記事を寄稿している。エンジニアではない。

TranscribeJA は、**取材音声を記事にするための下ごしらえ**として本人が自分ひとりで使う道具。
Windows のエクスプローラーで音声・動画ファイルを右クリックし「文字起こし（日本語）」を選ぶと、
すべてローカルで文字起こしして、元ファイルと同じフォルダに結果を書き出す。

ここから導かれる方針:

- **説明は日本語の平文で書く。** 専門用語を使うときは一言で言い換えを添える。
  「コードを読めば分かる」前提で書かない。変更を伝えるときは
  **「使ったときに何が変わって見えるか」を先に**、実装の話はその後。
- **毎月締切が来る。動いている状態を壊さないことが、新機能よりつねに優先。**
  大きく作り替えたくなったら、まず今の挙動を保ったまま足せないかを先に考える。
- 直近の変更のあとで不調が出たら、原因究明より先に**元に戻す手順**を渡す
  （`git revert <ハッシュ>` をそのまま貼れる形で）。原因を追うのはその後でよい。
- 使うのは本人だけ。**他人への配布を想定した一般化や設定項目の追加はしない。**
  ただし `install.ps1` は本人が入れ直すときに使うので壊さないこと。

## 取材音声という素材の性質（設計判断の根拠）

機能の是非で迷ったら、この 4 点に立ち返る。

1. **固有名詞が命。** 生産者名、ドメーヌ、シャトー、ブドウ品種、菓子の技法など、
   フランス語由来のカタカナ語が正しく出るかで実用性が決まる。Whisper はこの手の語をよく取り違える。
   - 現状、フィラー辞書（`fillers_ja.toml`）と数字辞書（`numbers_ja.toml`）はあるが、
     **固有名詞の置換辞書は無い。** 「◯◯が△△と書き起こされる」という相談が来たら、
     `postprocess/` に利用者が編集できる置換辞書を足すのが素直な拡張先。
     `postprocess/dictionaries.py` の読み込み方（TOML・初回コピー・壊れていても既定値で動き続ける）に倣う。
2. **タイムスタンプは実務要件。** 引用の裏取りのために録音の該当箇所へ戻るので、
   ずれた時刻は使えない。後述の `SegmentMap` の不変条件は、品質の話ではなく道具が使えるかどうかの話。
3. **切りすぎが最悪の失敗。** インタビューでは雑談の中に本音が出る。
   文字起こしが多少汚いのは自分で直せるが、消えた発言は取り返せない。
   - `[chatter] safety` の既定 `conservative`（迷ったら残す）を軽々に変えない。
   - `max_cut_ratio` の上限と cut_log（切った区間の記録）は外さない。判断に迷ったら必ず「残す」側へ倒す。
4. **1 本が 1〜2 時間になりやすい。** しかも後述のとおり手元は CPU のみ。処理時間の見積もりを常に意識する。

## 進め方

**コードを書く前に、方針を短く日本語で示して合意を取る**（本人の希望）。

- 示す内容は「何を変えるか / なぜ / 使ったときに何が変わるか / 戻し方」。長くて 5〜6 行。
- 選択肢があるときは 2〜3 個に絞り、**推奨を 1 つ明記する。**「お好きな方で」で終わらせない。
- 合意なしで進めてよいのは、誤字修正・コメントの補足・テストの追加・明らかな不具合の最小修正まで。
  それでも何をしたかは事後に一言で報告する。
- **一度に 1 つのことだけ変える。** 関係ない改善を混ぜない
  （不調が出たときに、どれが原因か分からなくなるため）。

## 実機での確認（Windows 実機・GPU なし）

手元の環境は **Windows 実機、GPU なし**。CPU 経路が本番であり、GPU 経路は検証できない。

- `whisper.model = "auto"` は GPU が無いと `medium` が選ばれる（`transcribe.py` の `AUTO_MODEL_CPU`）。
  large-v3 は CPU では 1 時間の音声に数時間かかることがある。
  **「精度を上げたい」という相談に対して、安易に large-v3 を勧めない。**
  まず辞書・`initial_prompt`・`beam_size` で詰める。
- CUDA 版 torch の分岐（`install.ps1` の `-Gpu` / `$TorchCudaIndex`）は手元で確認できない。
  触るときはその旨を伝え、CPU 経路を壊していないことをテストで示す。
- 確認をお願いするときは、**そのまま貼れる 1 行**と、**何が出たら成功か**をセットで書く。例:

  ```powershell
  .\.venv\Scripts\python.exe -m transcribe_ja --no-queue --no-gui --console "C:\path\to\取材音声.mp3"
  ```

  → 最後に「N 件のファイルを処理しました」と出て、音声と同じフォルダに `_ja.txt` などができていれば成功。
- **長い取材音声でいきなり試してもらわない。** まず数分の抜粋で確認してもらう。

## コマンド

```bash
# テスト（重い依存は不要。pytest と numpy だけで全件通る）
python -m pip install pytest numpy
python -m pytest -q

# 単体で流す
python -m pytest tests/test_segmap.py -q
python -m pytest tests/test_segmap.py::test_正規化は重なった区間を結合する -q
python -m pytest -q -k "正規化"
```

`pyproject.toml` の `[tool.pytest.ini_options]` で `pythonpath = ["src"]` を指定しているうえ、
`tests/conftest.py` が `sys.path` と `TRANSCRIBE_JA_HOME`（テスト用の一時フォルダ）を差し替えるので、
インストールなしで `src` レイアウトのままテストできる。

Windows 実機での操作:

```powershell
.\install.ps1                 # セットアップ（-Cpu / -Gpu / -SkipFfmpeg / -SkipRegister / -PythonPath あり）
.\.venv\Scripts\python.exe -m transcribe_ja --settings      # 設定画面
.\.venv\Scripts\python.exe -m transcribe_ja --open-config   # 設定ファイルを開く
.\.venv\Scripts\python.exe -m transcribe_ja --open-logs     # ログを開く（不調の相談を受けたらまずここ）
.\uninstall.ps1
```

リンタ・フォーマッタの設定は置いていない。既存ファイルのスタイル（4 スペース、
`from __future__ import annotations`、日本語 docstring、`# --- 見出し ---` のセクション区切り）に合わせる。
**利用者向けの文言・コメント・docstring・テスト名はすべて日本語で書く。**
エラーメッセージは「何が起きたか」＋「【対処方法】どうすればよいか」の二段構成（`errors.py` 参照）。

## アーキテクチャで押さえるべき点

### 1. 時刻の変換は 1 箇所だけ（`segmap.py`）

音声は 2 段階で短くなる（無音カット → 雑談カット）。Whisper が返す時刻は
「カット後の時間軸」なので、そのまま出力すると元の録音と突き合わせられない。

各カット段で「残した区間」を記録した `SegmentMap` を作り、`vad_map.then(chatter_map)` で合成し、
**`pipeline.to_output_segments()` の 1 箇所でだけ**元ファイルの時間軸へ戻す。

- `writers.py` に渡る時刻は変換済みが前提。writers 側では決して変換しない。
- 話者分離（`diarize.py`）は「抽出直後の WAV（元の時間軸）」に対して行う。カット後の音声を渡すとずれる。
- `tests/test_segmap.py` が最重要テスト（境界値・合成の結合法則・ランダムデータの往復検証）。
  時刻まわりに触れたら必ずここを通す。

### 2. 複数ファイル選択への対応（`queue_runner.py` / `cli.py`）

Windows のシェルは複数ファイルを選ぶと**ファイル数だけプロセスを起動する**。
そのため各プロセスは「キューに自分のファイルを追記 → ロック取得を試す」だけを行い、
ロックを取れた 1 プロセスだけがワーカーとして進捗ウィンドウを出し、キューを順に処理する。
取れなかったプロセスは静かに終了する。ロックは OS のファイルロック（Windows: `msvcrt` / 他: `fcntl`）。
シェルはプロセスを数百 ms かけて起動するのでデバウンス待ちを入れている。

`--no-queue` はこの仕組みを迂回してその場で 1 バッチ処理する（動作確認用）。

### 3. 重い依存は遅延 import

`torch` / `faster-whisper` / `silero-vad` / `anthropic` / `pyannote.audio` は
関数の中で import する（`transcribe.py`、`vad.py`、`chatter/llm.py`、`diarize.py`）。
これにより Windows 以外の開発環境でも全モジュールを import でき、テストが軽量なまま動く。
**この方針を崩してトップレベル import を足さないこと。**
import に失敗したときは `DependencyMissingError` などの日本語エラーに変換する。

### 4. 設定は `resources/default_config.toml` が唯一の出所（`config.py`）

初回起動時に、コメント付きの既定ファイルを `%APPDATA%\TranscribeJA\config.toml` へそのままコピーする
（設定ファイルを開いたときに各項目の説明が読めるようにするため）。
項目が欠けていても既定値で埋めて動かす。値が不正なときは日本語で理由を説明して停止する。
**設定項目を追加するときは、dataclass・`default_config.toml`・README の「設定項目の一覧」の 3 箇所を揃える。**

### 5. install.ps1 と Python 側の定数は同期が必須

`tests/test_install_scripts.py` が PowerShell スクリプトを正規表現で読み、次を検証している。

- `$Extensions`（install.ps1／uninstall.ps1）と `pipeline.SUPPORTED_EXTENSIONS` が一致すること
- `$MenuLabel` と `transcribe_ja.MENU_LABEL` が一致すること
- 両スクリプトが **UTF-8 BOM 付き**で保存されていること（Windows PowerShell 5.1 の文字化け対策）

対応拡張子やメニュー名を変えるときは両方を直す。PowerShell を編集したら BOM を落とさない。

### 6. パスの面倒事は `paths.py` に閉じ込める

MAX_PATH（260 文字）超えの `\\?\` プレフィックス、UNC パス、日本語・空白を含むパスの扱いはここだけ。
OS 依存処理は `os.name == "nt"` で分岐し、それ以外では素通しする。
データ置き場は `TRANSCRIBE_JA_HOME` > `%APPDATA%\TranscribeJA` > `~/.config/TranscribeJA` の順で決まる。

出力ファイルは `unique_path()` により `取材_ja(2).txt` のように連番を付ける。
**既存ファイルは決して上書きしない**（前回の結果を失わないため）。

### 7. 雑談カットの安全装置（`chatter/`）

小型モデルで下読み（パス1）→ ルールベースまたは LLM で本編／不要を判定 → 不要区間をカット、の 2 パス構成。
安全装置は 3 つ。**判定ロジックを変えても、これらは外さない**（上の「切りすぎが最悪の失敗」を参照）。

- 既定の安全度は `conservative`（迷ったら残す）
- `[chatter] max_cut_ratio` を超える量は切らない。超えたら確信度の低い判定から「残す」へ戻す
- 切った区間は必ずカットログに残す（元ファイルの時刻・理由・本文）

### 8. 日本語整形の順序には意味がある（`postprocess/`）

フィラー除去 → 言い直しの整理 → 表記の統一 → **句読点の整形（最後）**。
前段の除去で「、、」や行頭の読点が生じるため、句読点の掃除は必ず最後に置く。

## 処理の流れ（`pipeline.process_file`）

1. 音声抽出・正規化（ffmpeg で 16kHz / モノラル / PCM16）
2. 無音カット（VAD: silero → webrtc → エネルギーの順にフォールバック）
3. 雑談カット（`chatter/`。設定で無効化可）
4. 文字起こし（faster-whisper）
5. **元ファイルの時刻へ戻す** → 話者分離（任意）→ 日本語整形
6. 出力（txt / srt / md / cut_log を元ファイルと同じフォルダへ）

工程名は `progress.Stage` で一元管理している（進捗ウィンドウの表示文字列もここ）。

## 別言語版の併設

レジストリキー名は `TranscribeJA`。フランス語版を作る場合は `install.ps1` の `$RegistryKey` を
`TranscribeFR` のように変えれば、同じ拡張子で両方のメニューを共存させられる。
ただし文字起こし以降（`postprocess/` の日本語整形、辞書、`initial_prompt`）は日本語専用なので、
言語版を増やすのは設定の切り替えでは済まない。着手前に必ず範囲を相談すること。
