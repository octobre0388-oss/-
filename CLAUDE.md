# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリについて

TranscribeJA（`transcribe-ja`）は、Windows のエクスプローラーの右クリックメニューから
音声・動画ファイルを日本語で文字起こしする単体ツール。すべてローカルで処理し、
管理者権限を必要としない。配布形態は「フォルダごと配って `install.ps1` を実行してもらう」方式で、
PyPI パッケージやサービスとしては配布しない。

**利用者向けの文言・コメント・docstring・テスト名はすべて日本語で書く。** 既存コードに合わせること。
エラーメッセージは「何が起きたか」＋「どうすればよいか」の二段構成（`errors.py` 参照）。

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

実機（Windows）での動作確認:

```powershell
.\install.ps1                 # 通常のセットアップ（-Cpu / -Gpu / -SkipFfmpeg / -SkipRegister / -PythonPath あり）
.\.venv\Scripts\python.exe -m transcribe_ja --no-queue --no-gui --console "C:\path\to\音声.mp3"
.\.venv\Scripts\python.exe -m transcribe_ja --settings      # 設定画面
.\.venv\Scripts\python.exe -m transcribe_ja --open-config   # 設定ファイルを開く
.\.venv\Scripts\python.exe -m transcribe_ja --open-logs
.\uninstall.ps1
```

リンタ・フォーマッタの設定は置いていない。既存ファイルのスタイル（4 スペース、
`from __future__ import annotations`、日本語 docstring、セクション区切りの `# --- 見出し ---` コメント）に合わせる。

## アーキテクチャで押さえるべき点

### 1. 時刻の変換は 1 箇所だけ（`segmap.py`）

音声は 2 段階で短くなる（無音カット → 雑談カット）。Whisper が返す時刻は
「カット後の時間軸」なので、そのまま出力すると元動画と突き合わせられない。

各カット段で「残した区間」を記録した `SegmentMap` を作り、`vad_map.then(chatter_map)` で合成し、
**`pipeline.to_output_segments()` の 1 箇所でだけ**元ファイルの時間軸へ戻す。

- `writers.py` に渡る時刻は変換済みが前提。writers 側では決して変換しない。
- 話者分離（`diarize.py`）は「抽出直後の WAV（元の時間軸）」に対して行う。カット後の音声を渡すとずれる。
- `tests/test_segmap.py` が最重要テスト（境界値・合成の結合法則・ランダムデータの往復検証）。
  時刻まわりに触れたら必ずここを通す。

### 2. 複数ファイル選択への対応（`queue_runner.py` / `cli.py`）

Windows のシェルは複数ファイルを選ぶと**ファイル数だけプロセスを起動する**。
そのため各プロセスは「キューに自分のファイルを追記 → ロック取得を試す」だけを行い、
ロックを取れた 1 プロセスだけがワーカーとして進捗ウィンドウを出しキューを順に処理する。
取れなかったプロセスは静かに終了する。ロックは OS のファイルロック（Windows: `msvcrt` / 他: `fcntl`）。
シェルはプロセスを数百 ms かけて起動するのでデバウンス待ちを入れている。

`--no-queue` はこの仕組みを迂回してその場で 1 バッチ処理する（動作確認・自動化用）。

### 3. 重い依存は遅延 import

`torch` / `faster-whisper` / `silero-vad` / `anthropic` / `pyannote.audio` は
関数の中で import する（`transcribe.py`、`vad.py`、`chatter/llm.py`、`diarize.py`）。
これにより Windows 以外の開発環境でも全モジュールを import でき、テストが軽量なまま動く。
**この方針を崩してトップレベル import を足さないこと。**
import に失敗したときは `DependencyMissingError` などの日本語エラーに変換する。

### 4. 設定は `resources/default_config.toml` が唯一の出所（`config.py`）

初回起動時にコメント付きの既定ファイルを `%APPDATA%\TranscribeJA\config.toml` へそのままコピーする
（利用者がファイルを開いたときに説明が読めるようにするため）。
利用者のファイルに項目が欠けていても既定値で埋めて動かす（項目追加で壊れないように）。
値が不正なときは日本語で理由を説明して停止する。
**設定項目を追加するときは、dataclass・`default_config.toml`・README の「設定項目の一覧」の 3 箇所を揃える。**

### 5. install.ps1 と Python 側の定数は同期が必須

`tests/test_install_scripts.py` が PowerShell スクリプトを正規表現で読み、次を検証している。

- `$Extensions`（install.ps1／uninstall.ps1）と `pipeline.SUPPORTED_EXTENSIONS` が一致すること
- `$MenuLabel` と `transcribe_ja.MENU_LABEL` が一致すること
- 両スクリプトが **UTF-8 BOM 付き**で保存されていること（Windows PowerShell 5.1 の文字化け対策）

対応拡張子やメニュー名を変えるときは両方を直す。PowerShell を編集したら BOM を落とさない。

### 6. パスの面倒事は `paths.py` に閉じ込める

MAX_PATH（260 文字）超えの `\\?\` プレフィックス、UNC パス、日本語・空白を含むパスの扱いはここだけ。
OS 依存処理は `os.name == "nt"` で分岐し、それ以外では素通しする（開発環境で import できるようにするため）。
アプリのデータ置き場は `TRANSCRIBE_JA_HOME` > `%APPDATA%\TranscribeJA` > `~/.config/TranscribeJA` の順で決まる。

出力ファイルは `unique_path()` により `会議_ja(2).txt` のように連番を付ける。**既存ファイルは決して上書きしない。**

### 7. 雑談カットの安全装置（`chatter/`）

小型モデルで下読み（パス1）→ ルールベースまたは LLM で本編／不要を判定 → 不要区間をカット、の 2 パス構成。

- 既定の安全度は `conservative`（迷ったら残す）
- `[chatter] max_cut_ratio` を超える量は切らない。超えたら確信度の低い判定から「残す」へ戻す
- 切った区間は必ずカットログに残す（元ファイルの時刻・理由・本文）

この 3 つは利用者の信頼に直結するので、判定ロジックを変えても安全装置は外さない。

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

- レジストリキー名は `TranscribeJA`。別言語版を併設する場合は `install.ps1` の `$RegistryKey` を
  `TranscribeFR` などに変えれば同じ拡張子でメニューを共存させられる。
