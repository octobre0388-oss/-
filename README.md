# 文字起こし（日本語） - TranscribeJA

Windows 11 のエクスプローラーで音声・動画ファイルを右クリックし、
**「文字起こし（日本語）」** を選ぶだけで、日本語の文字起こしができるツールです。

```
右クリック → 文字起こし（日本語）
    ↓
  音声を取り出す
    ↓
  無音をカット
    ↓
  不要な雑談をカット
    ↓
  文字起こし
    ↓
  日本語として読みやすく整える
    ↓
  元のファイルと同じフォルダに結果を保存
```

- インターネットに文字起こしの内容を送りません（すべてお使いのパソコンの中で処理します）
- 管理者権限は不要です
- GPU があれば自動で使い、無ければ CPU で動きます
- 複数のファイルをまとめて選んでも、ウィンドウは 1 つだけ。順番に処理します

---

## もくじ

1. [必要なもの](#必要なもの)
2. [インストール手順](#インストール手順)
3. [使い方](#使い方)
4. [出力されるファイル](#出力されるファイル)
5. [設定を変える](#設定を変える)
6. [設定項目の一覧](#設定項目の一覧)
7. [よくあるトラブルと対処](#よくあるトラブルと対処)
8. [応用: AI で雑談カットの精度を上げる](#応用-ai-で雑談カットの精度を上げる)
9. [応用: 話者分離を使う](#応用-話者分離を使う)
10. [アンインストール](#アンインストール)
11. [開発者向け](#開発者向け)

---

## 必要なもの

| 項目 | 内容 |
|---|---|
| OS | Windows 11（64bit）。Windows 10 でも動きます |
| Python | **3.11 以上**（入っていない場合は下の手順でご案内します） |
| 空き容量 | **5GB 以上**（文字起こしモデルに 1.5〜3GB 使います） |
| インターネット | インストール時のみ必要です |
| GPU | 無くても動きます。あると 5〜20 倍ほど速くなります |

> **ffmpeg は自分で用意する必要はありません。** インストール時に自動でダウンロードし、
> このツールのフォルダの中に置きます。パソコンの他の設定（PATH）は変更しません。

---

## インストール手順

### 手順 0: Python が入っているか確認する

1. キーボードの **Windows キー** を押して、`powershell` と入力し、
   **Windows PowerShell** を開きます
2. 次のように入力して **Enter** を押します

   ```powershell
   python --version
   ```

3. `Python 3.11.9` のように **3.11 以上**の数字が出れば大丈夫です。次の手順へ進んでください

> **`python` と打つと Microsoft Store が開いてしまう場合**
> それは Python 本体ではなく、ストアを開くだけのダミー（アプリ実行エイリアス）です。
> 下の「方法A」でストアから Python をインストールしてください。

<details>
<summary>「Python が見つかりません」と出た場合、または 3.10 以下だった場合（クリックで開く）</summary>

**方法A: Microsoft Store から入れる（かんたん・管理者権限不要）**

1. Windows キーを押して `Microsoft Store` を開く
2. 検索欄に `Python 3.12` と入力する
3. 「Python 3.12」を選んで「入手」をクリックする
4. インストールが終わったら PowerShell を **開き直して**、もう一度 `python --version` を試す

> ⚠️ **PowerShell は必ず開き直してください。** 開いたままだと、新しく入れた
> Python が認識されず「見つかりません」のままになります。

**方法B: python.org から入れる**

1. https://www.python.org/downloads/windows/ を開く
2. 「Latest Python 3 Release」をクリックし、
   ページ下部の **Windows installer (64-bit)** をダウンロードする
3. ダウンロードしたファイルを実行する
4. **最初の画面で「Add python.exe to PATH」に必ずチェックを入れてから**
   「Install Now」をクリックする
5. インストールが終わったら PowerShell を開き直して確認する

</details>

### 手順 1: ファイルをダウンロードして置く

#### 1-1. ZIP ファイルをダウンロードする

ブラウザで次のアドレスを開くと、ZIP ファイルのダウンロードが始まります。

```
https://github.com/octobre0388-oss/-/archive/refs/heads/claude/windows-transcribe-ja-tool-72vy5f.zip
```

<details>
<summary>GitHub のページから操作したい場合（クリックで開く）</summary>

1. https://github.com/octobre0388-oss/- を開く
2. 画面左上のブランチ名のボタン（`main` などと書かれています）をクリック
3. 一覧から `claude/windows-transcribe-ja-tool-72vy5f` を選ぶ
4. 緑色の **「Code」** ボタン → **「Download ZIP」** をクリック

</details>

#### 1-2. ZIP を展開する

1. ダウンロードした ZIP ファイル（ふつうは「ダウンロード」フォルダにあります）を
   **右クリック** → **「すべて展開」** をクリック
2. 「展開」をクリック

#### 1-3. フォルダを置く場所を決める

展開されたフォルダは `--claude-windows-transcribe-ja-tool-72vy5f` のような
長い名前になっています。**`TranscribeJA` に名前を変えて**、
次の場所に移動してください。

```
C:\Users\<あなたのユーザー名>\TranscribeJA
```

> **注意 1:** OneDrive で同期されるフォルダ（デスクトップ、ドキュメントなど）は
> 避けてください。同期のたびに数 GB のファイルが転送されてしまいます。
>
> **注意 2:** フォルダの場所に**日本語が入らないようにしてください。**
> ユーザー名が日本語（例: `C:\Users\山田太郎\`）の場合は、
> `C:\TranscribeJA` に置くのが確実です。
> （※ 文字起こしする音声・動画のほうは、日本語のファイル名で問題ありません）

#### 1-4. 中身を確認する

`TranscribeJA` フォルダを開いて、次のファイルが**直接**入っていることを確認してください。

```
install.ps1      ← これがある階層が正解です
uninstall.ps1
README.md
requirements.txt
src              （フォルダ）
```

`TranscribeJA` を開いたらもう 1 つフォルダがあるだけ、という場合は
展開の都合で階層が深くなっています。中のフォルダを開き直して、
`install.ps1` がある階層まで進んでください。

### 手順 2: インストールを実行する

#### 2-1. そのフォルダで PowerShell を開く

`install.ps1` があるフォルダをエクスプローラーで開いた状態で、
**アドレス欄**（`PC > ローカルディスク(C:) > TranscribeJA` のように
フォルダの場所が書いてある、画面上部の細長い欄）をクリックします。

すると文字が入力できる状態になるので、そこに書かれている文字をすべて消して

```
powershell
```

と入力し、**Enter** を押します。青い画面（PowerShell）が開きます。

> この方法で開くと、**そのフォルダの中で** PowerShell が始まります。
> スタートメニューから開くと別の場所で始まってしまい、
> 「そのようなファイルはありません」というエラーになります。

#### 2-2. 開いた場所が正しいか確かめる

念のため、次の 1 行を貼り付けて **Enter** を押してください。

```powershell
dir install.ps1
```

`install.ps1` の行が表示されれば正しい場所です。
`見つかりません` と出た場合は、手順 1-4 に戻ってフォルダを確認してください。

#### 2-3. インストールを実行する

次の 1 行を **そのままコピーして貼り付け**、**Enter** を押します。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; Get-ChildItem *.ps1 | Unblock-File; .\install.ps1
```

> **貼り付け方:** PowerShell の画面の上で**右クリック**すると貼り付けられます
> （`Ctrl + V` でも大丈夫です）。
>
> **この 1 行の意味:**
> - `Set-ExecutionPolicy ...` … この窓の中だけスクリプトの実行を許可します
>   （パソコン全体の設定は変わりません）
> - `Unblock-File` … インターネットからダウンロードしたファイルに付く
>   「ブロック」の印を外します
> - `.\install.ps1` … セットアップを開始します

#### 2-4. 待つ

**5〜20 分ほど**かかります。途中で画面が止まったように見えても、
ライブラリをダウンロードしているだけなので、そのままお待ちください。

インストールでは次のことが行われます。

```
[1/6] Python を探しています
[2/6] 専用の Python 環境を作っています      ← 他のソフトに影響しません
[3/6] 必要なライブラリを入れています        ← ここが一番時間がかかります
[4/6] ffmpeg を用意しています               ← 自動でダウンロードします
[5/6] 右クリックメニューに登録しています
[6/6] 動作を確認しています
```

「セットアップが完了しました」と緑色で表示されれば成功です。

途中で**赤い文字**が出て止まった場合は、その下に
「【対処方法】」として具体的な手順が表示されます。
それでも解決しない場合は、下の
[よくあるトラブルと対処](#よくあるトラブルと対処)をご覧ください。

---

## 使い方

1. 文字起こししたい **音声ファイルまたは動画ファイル** を右クリックします
2. **「その他のオプションを表示」** をクリックします
   （Windows 11 の場合。`Shift` を押しながら右クリックしても同じです）
3. **「文字起こし（日本語）」** をクリックします
4. 小さな進捗ウィンドウが出ます。終わるまで待ちます
5. 完了すると Windows の通知が出ます。クリックすると結果のフォルダが開きます

### ⏰ 最初の 1 回だけ、とても時間がかかります

**初回の実行時に、文字起こし用のモデル（AI の頭脳にあたるデータ）を
インターネットからダウンロードします。**

| モデル | サイズ | ダウンロード時間の目安 |
|---|---|---|
| large-v3（GPU がある場合の既定） | 約 3GB | 10〜40 分 |
| medium（GPU が無い場合の既定） | 約 1.5GB | 5〜20 分 |

このあいだ進捗ウィンドウは「文字起こし中」のまま止まって見えますが、
**故障ではありません。** そのままお待ちください。
2 回目からはこの待ち時間はありません。

### 処理にかかる時間の目安

1 時間の音声を処理した場合の目安です（雑談カットを含む）。

| 環境 | モデル | 目安 |
|---|---|---|
| GPU あり（RTX 3060 程度） | large-v3 | 8〜15 分 |
| GPU なし（一般的なノート PC） | medium | 40〜90 分 |
| GPU なし | large-v3 | **3〜6 時間**（おすすめしません） |

### 複数のファイルをまとめて処理する

ファイルを複数選んでから右クリックしても大丈夫です。
ウィンドウは 1 つだけ開き、**1 件ずつ順番に**処理します。
進捗ウィンドウには `[3/12] 文字起こし中` のように、いま何件目かが表示されます。

### 途中でやめたいとき

進捗ウィンドウの **「キャンセル」** ボタンを押してください。
区切りのよいところで停止します（すぐには止まりません）。

---

## 出力されるファイル

**元のファイルと同じフォルダ**に、元のファイル名を引き継いで保存されます。
`会議.mp4` を処理した場合は次のようになります。

| ファイル | 内容 |
|---|---|
| `会議_ja.txt` | 整形済みの読みやすい本文。ふだんはこれを見ます |
| `会議_ja.srt` | 字幕ファイル。**元の動画のタイムコード**に対応しています |
| `会議_ja.md` | 5 分ごとの見出し付き。長い会議を追いやすい形式です |
| `会議_ja_cut_log.txt` | 削除した区間の記録。「いつ・なぜ・何を」消したかが分かります |

### ⭐ タイムスタンプについて（重要）

無音や雑談をカットすると音声は短くなりますが、
**出力される時刻はすべて「元のファイルの時刻」に変換されています。**

たとえば `会議_ja.srt` の `00:12:34` は、
**元の `会議.mp4` を 12 分 34 秒の位置まで進めたところ**に対応します。
動画プレイヤーで字幕を読み込んでも、話している内容とぴったり合います。

### カット記録の見方

`会議_ja_cut_log.txt` には次のように記録されます。

```
[2:10〜3:05] (55秒)
  理由: 雑談・不要と判定（挨拶（お疲れ様です）、機材・接続の確認（聞こえてますか）、冒頭・末尾）
  内容: お疲れ様です。聞こえてますか、マイク大丈夫ですか。
```

時刻は元ファイル基準なので、実際に元の動画の 2 分 10 秒を再生して
「本当に消してよかったか」を確認できます。

### 同じファイルを 2 回処理したら

**上書きしません。** `会議_ja(2).txt` のように連番が付きます。
前回の結果が消えることはありません。

---

## 設定を変える

### 設定画面を開く

PowerShell で、このツールのフォルダに移動して次を実行します。

```powershell
.\.venv\Scripts\python.exe -m transcribe_ja --settings
```

よく使う項目だけを画面から変更できます。
細かい調整は「設定ファイルを開く」ボタンから直接編集してください。

### 設定ファイルを直接開く

設定ファイルの場所は次のとおりです。

```
C:\Users\<ユーザー名>\AppData\Roaming\TranscribeJA\config.toml
```

エクスプローラーのアドレス欄に `%APPDATA%\TranscribeJA` と入力しても開けます。
メモ帳で編集して保存すれば、次回の処理から反映されます。

> **設定を元に戻したいときは、この config.toml を削除してください。**
> 次回起動時に既定値で作り直されます。

---

## 設定項目の一覧

### `[general]` 全般

| 項目 | 既定値 | 説明 |
|---|---|---|
| `language` | `"ja"` | 文字起こしの言語。日本語版なので変更は不要です |
| `keep_temp` | `false` | `true` にすると一時ファイルを残します（不具合調査用） |
| `log_level` | `"INFO"` | ログの詳しさ。調査時は `"DEBUG"` にします |

### `[output]` 出力

| 項目 | 既定値 | 説明 |
|---|---|---|
| `formats` | `["txt","srt","md","cut_log"]` | 出力する種類。要らないものを消せます |
| `suffix` | `"_ja"` | ファイル名に付ける文字。`会議.mp4` → `会議_ja.txt` |
| `open_folder_when_done` | `true` | 通知をクリックしたときにフォルダを開くか |

### `[audio]` 音声の取り出し

| 項目 | 既定値 | 説明 |
|---|---|---|
| `track` | `1` | 音声トラックが複数ある動画で、何本目を使うか |
| `normalize` | `"loudnorm"` | 音量の正規化。`"dynaudnorm"`（小声も持ち上がる）、`"none"`（しない）も選べます |

### `[vad]` 無音カット

| 項目 | 既定値 | 説明 |
|---|---|---|
| `enabled` | `true` | 無音カットを行うか |
| `engine` | `"silero"` | 検出方式。`"webrtc"` は軽量ですが精度は落ちます |
| `min_silence_ms` | `700` | これより短い無音は切りません（ミリ秒） |
| `padding_ms` | `200` | 発話の前後に残す余白。語頭・語尾の欠けを防ぎます |
| `threshold` | `0.5` | 発話とみなす感度。BGM を拾ってしまうときは `0.6`〜`0.7` に上げます |
| `min_speech_ms` | `250` | これより短い音は雑音として捨てます |

> **なぜ ffmpeg の無音除去を使わないのか:** 音量だけで判断する方式は、
> 空調音や BGM がある素材でほとんど切れません。逆にしきい値を上げると
> 小声の発言まで消えます。このツールは「人の声かどうか」を判定する
> Silero VAD を使うため、BGM の上に乗った発話も正しく残せます。

### `[chatter]` 雑談カット

| 項目 | 既定値 | 説明 |
|---|---|---|
| `enabled` | `true` | **`false` にすると無音カットだけになります**（処理も速くなります） |
| `method` | `"rules"` | 判定方式。`"llm"` にすると AI が判定します（別途設定が必要） |
| `prescan_model` | `"small"` | 下読み用の軽量モデル |
| `safety` | `"conservative"` | 安全度。`"conservative"`（迷ったら残す）／`"balanced"`／`"aggressive"`（迷ったら切る） |
| `max_cut_ratio` | `0.35` | 雑談カットで削る割合の上限。誤判定で本編が消える事故を防ぎます |
| `llm_model` | `"claude-opus-5"` | AI 判定に使うモデル |
| `rules_file` | `"chatter_ja.toml"` | 判定辞書のファイル名 |

**切りすぎると感じたら:** `safety = "conservative"` のまま、
`max_cut_ratio` を `0.2` などに下げてください。
それでも気になる場合は `enabled = false` にすれば雑談カットを止められます。

**判定に使う言葉を編集する:**
`%APPDATA%\TranscribeJA\dictionaries\chatter_ja.toml` を開くと、
「お疲れ様です」「聞こえてますか」といった判定用の表現を追加・削除できます。

### `[whisper]` 文字起こし

| 項目 | 既定値 | 説明 |
|---|---|---|
| `model` | `"auto"` | **GPU があれば large-v3、無ければ medium を自動選択**。`"large-v3"` などで固定もできます |
| `device` | `"auto"` | `"cuda"` / `"cpu"` で固定もできます |
| `compute_type` | `"auto"` | 計算精度。通常は変更不要です |
| `beam_size` | `5` | 大きいほど精度が上がり、遅くなります |
| `initial_prompt` | （日本語の例文） | 句読点付きの出力を促すための見本文 |
| `no_speech_threshold` | `0.6` | 無音部分で存在しない文章が出る（幻覚）のを抑えます。増やすと厳しくなります |
| `log_prob_threshold` | `-1.0` | 同上 |
| `compression_ratio_threshold` | `2.4` | 同じ言葉の繰り返しを検出して捨てるための値 |
| `model_dir` | `""` | モデルの保存先。空欄なら既定の場所に保存されます |

### `[format]` 日本語の整形

| 項目 | 既定値 | 説明 |
|---|---|---|
| `remove_fillers` | `true` | 「えー」「あのー」などを取り除きます |
| `fillers_file` | `"fillers_ja.toml"` | フィラー辞書のファイル名 |
| `normalize_width` | `true` | 英数字を半角に、記号を日本語の句読点に統一します |
| `numbers` | `"arabic"` | 数字の表記。`"kanji"`（漢数字）、`"keep"`（変換しない）も選べます |
| `fix_restatements` | `true` | 「これは、これはですね」→「これはですね」 |
| `fix_punctuation` | `true` | 重複した句読点などを整えます |
| `line_width` | `0` | txt で 1 行の文字数を制限したい場合に指定（0 なら折り返しません） |

**フィラーの除去リストを編集する:**
`%APPDATA%\TranscribeJA\dictionaries\fillers_ja.toml` を開いてください。
`keep` の欄に書いた言い回しは、除去の対象外になります。

### `[advanced]` 詳細

| 項目 | 既定値 | 説明 |
|---|---|---|
| `ffmpeg_path` / `ffprobe_path` | `""` | 手動で場所を指定したい場合のみ記入します |
| `queue_debounce_seconds` | `1.5` | 複数選択したときに、後続を待つ秒数 |
| `show_progress_window` | `true` | 進捗ウィンドウを出すか |
| `show_notification` | `true` | 完了時に通知を出すか |

---

## よくあるトラブルと対処

### インストールがうまくいかないとき

<details>
<summary><b>「このシステムではスクリプトの実行が無効になっているため…」と出る</b></summary>

PowerShell の安全機能によるものです。次の 1 行を貼り付けてから実行してください。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\install.ps1
```

`-Scope Process` は「この窓の中だけ」という意味なので、
パソコン全体の設定は変わりません。
</details>

<details>
<summary><b>Python は入っているのに「見つかりません」と言われる</b></summary>

`install.ps1` は次の 4 通りで Python を探します。

1. `py` ランチャーが把握している一覧（`py --list-paths` で確認できます）
2. PATH 上の `python` / `python3`
3. レジストリ（公式インストーラが登録します）
4. `%LOCALAPPDATA%\Programs\Python\Python3*` などのよくある場所

それでも見つからない場合は、使う Python を直接指定できます。

```powershell
.\install.ps1 -PythonPath "C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python312\python.exe"
```

自分の Python の場所は、次のコマンドで確認できます。

```powershell
py --list-paths
```

なお、複数のバージョンが入っている場合は **3.12 → 3.13 → 3.11** の順に優先して選びます。
3.14 のような新しすぎるバージョンは、文字起こしライブラリ（torch など）の対応が
追いついていないことがあるためです。

</details>

<details>
<summary><b>ライブラリのインストールで止まる・失敗する</b></summary>

インターネット接続をご確認のうえ、もう一度 `install.ps1` を実行してください。
途中まで終わった分はやり直しになりません。

会社のネットワークでプロキシをお使いの場合は、次を実行してから
`install.ps1` を実行してください。

```powershell
$env:HTTPS_PROXY = "http://プロキシのアドレス:ポート番号"
```
</details>

<details>
<summary><b>ffmpeg のダウンロードに失敗する</b></summary>

手動で配置できます。

1. https://www.gyan.dev/ffmpeg/builds/ を開く
2. **ffmpeg-release-essentials.zip** をダウンロードする
3. zip を右クリック →「すべて展開」
4. 展開したフォルダの中の `bin` フォルダにある
   **`ffmpeg.exe`** と **`ffprobe.exe`** の 2 つを、
   このツールの `tools\ffmpeg\` フォルダにコピーする
   （`tools\ffmpeg` フォルダが無ければ作ってください）
5. `install.ps1` をもう一度実行する
</details>

### 使っているときのトラブル

<details>
<summary><b>右クリックしてもメニューに出てこない</b></summary>

1. Windows 11 では **「その他のオプションを表示」** の中にあります。
   `Shift` を押しながら右クリックしても表示されます
2. 対応していない拡張子かもしれません。対応しているのは次の 15 種類です

   `.mp3` `.wav` `.m4a` `.aac` `.flac` `.ogg` `.wma` `.opus`
   `.mp4` `.mov` `.mkv` `.avi` `.webm` `.m4v` `.ts`

3. エクスプローラーを再起動すると反映されることがあります。
   タスクマネージャー → 「エクスプローラー」を右クリック →「再起動」

**Shift を押さずに出したい場合**（Windows 11 のメニューを従来型に戻す方法）:

```powershell
reg add "HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32" /f /ve
```

を実行してサインインし直すと、右クリックで従来型メニューが直接出るようになります。
元に戻す場合は次を実行します。

```powershell
reg delete "HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}" /f
```
</details>

<details>
<summary><b>クリックしても何も起きない / ウィンドウが一瞬で消える</b></summary>

すでに別のウィンドウが処理中の可能性があります（これは正常な動作です）。
タスクバーに進捗ウィンドウがないかご確認ください。

それでも何も起きない場合は、ログをご確認ください。

```
%APPDATA%\TranscribeJA\logs\transcribe_ja.log
```

エクスプローラーのアドレス欄に `%APPDATA%\TranscribeJA\logs` と入力すると開けます。

コマンドから直接実行すると、エラーの内容が画面に出ます。

```powershell
.\.venv\Scripts\python.exe -m transcribe_ja --no-queue --no-gui "C:\パス\ファイル.mp4"
```
</details>

<details>
<summary><b>処理がとても遅い / 終わらない</b></summary>

- **初回はモデルのダウンロードで 10〜40 分かかります。** 故障ではありません
- GPU が無い場合、`model = "large-v3"` を指定していると 1 時間の音声に
  3〜6 時間かかります。設定ファイルの `[whisper] model` を `"medium"` か
  `"small"` に変えてください
- 雑談カットを止めると、下読みの分だけ速くなります
  （`[chatter] enabled = false`）
</details>

<details>
<summary><b>文字起こしの内容がおかしい（同じ文が繰り返される・無音なのに文字が出る）</b></summary>

`[whisper]` の次の値を調整してください。

- 同じ文の繰り返し → `compression_ratio_threshold` を `2.0` に下げる
- 無音部分に文章が出る → `no_speech_threshold` を `0.7`〜`0.8` に上げる
- 精度を上げたい → `model` を `"large-v3"` に、`beam_size` を `8` に上げる
</details>

<details>
<summary><b>必要な部分まで消されてしまった</b></summary>

まず `_cut_log.txt` を開いて、何が消されたかを確認してください。

- 雑談カットを止める → `[chatter] enabled = false`
- 削る量を減らす → `[chatter] max_cut_ratio = 0.2`
- 特定の言い回しを守る → `dictionaries\chatter_ja.toml` の
  `main_topic` にその言葉を追加する（本編扱いされやすくなります）
- 無音カットで語尾が切れる → `[vad] padding_ms` を `300`〜`400` に増やす
</details>

<details>
<summary><b>「音声トラックがありません」と出る</b></summary>

- 映像だけで音声が入っていないファイルの可能性があります
- 音声が複数入っている動画で、指定した番号が存在しない場合もこのエラーが出ます。
  エラーメッセージにトラックの一覧が表示されるので、
  `[audio] track` をその番号に合わせてください
</details>

<details>
<summary><b>ファイル名やフォルダ名に日本語・空白が入っていても大丈夫？</b></summary>

大丈夫です。日本語、空白、長いパス、ネットワーク上の共有フォルダ（`\\server\share\...`）
にも対応しています。

ただし、パスが極端に長い場合（数百文字以上）は、
ファイルをデスクトップなど浅い場所にコピーしてからお試しください。
</details>

<details>
<summary><b>ディスクの空き容量が足りないと言われる</b></summary>

処理中は元ファイルの 2〜3 倍程度の一時領域を使います。
不要なファイルを削除してからお試しください。
モデルの保存先を別のドライブに移すこともできます
（`[whisper] model_dir` に `"D:\\models"` のように指定）。
</details>

---

## 応用: AI で雑談カットの精度を上げる

既定の雑談カットは、辞書に登録された言い回しで判定します（インターネット不要）。
Anthropic の API を使うと、文脈を読んだうえで判定できるようになります。

> **注意:** この機能を使うと、**下読みした文字起こしのテキストが
> Anthropic のサーバーに送信されます。** 機密性の高い内容の場合はご注意ください。
> 音声そのものは送信されません。

1. https://console.anthropic.com/ で API キーを取得します
2. Windows の環境変数に登録します（PowerShell で 1 回だけ実行）

   ```powershell
   [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'sk-ant-...', 'User')
   ```

3. 設定ファイルの `[chatter]` を次のように変更します

   ```toml
   method = "llm"
   ```

4. PowerShell とエクスプローラーを開き直します

API キーが設定されていない場合や通信に失敗した場合は、
**自動的に辞書による判定に切り替わります。** 文字起こしが失敗することはありません。

---

## 応用: 話者分離を使う

「誰が話したか」を区別してラベルを付ける機能です。既定では無効です。

1. https://huggingface.co/ でアカウントを作ります
2. https://huggingface.co/pyannote/speaker-diarization-3.1 を開き、
   利用規約に同意します（無料）
3. https://huggingface.co/settings/tokens でアクセストークンを作ります
4. 環境変数に登録します

   ```powershell
   [Environment]::SetEnvironmentVariable('HUGGINGFACE_TOKEN', 'hf_...', 'User')
   ```

5. ライブラリを追加します

   ```powershell
   .\.venv\Scripts\python.exe -m pip install "pyannote.audio>=3.1"
   ```

6. 設定ファイルの `[diarization]` を `enabled = true` にします

出力は `話者A: こんにちは。` のような形式になります。
うまく動かない場合は、警告をログに残したうえで、話者なしで処理を続けます。

---

## アンインストール

PowerShell でこのツールのフォルダを開き、次を実行します。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\uninstall.ps1
```

右クリックメニューの登録が**完全に**削除されます。
設定・ログ・Python 環境はそのまま残るので、`install.ps1` を実行すればすぐ元に戻ります。

設定やダウンロードしたものも含めてすべて消したい場合は次を実行します。

```powershell
.\uninstall.ps1 -All
```

そのあと、このフォルダごと削除してください。

> 文字起こしモデル（`%USERPROFILE%\.cache\huggingface`、数 GB）は、
> 他のソフトと共有していることがあるため自動では削除しません。
> 不要であればエクスプローラーで削除してください。

---

## 開発者向け

### 構成

```
src/transcribe_ja/
├─ cli.py            引数解析／キュー投入かワーカー起動かの分岐
├─ queue_runner.py   複数選択対策（ロック＋キュー＋デバウンス）
├─ pipeline.py       処理全体の流れ
├─ segmap.py         ★ 時刻変換の中核（カット後 → 元ファイル）
├─ wavtools.py       WAV の読み書きとサンプル単位の切り貼り
├─ ffmpeg_tools.py   ffmpeg / ffprobe の探索と実行
├─ vad.py            発話区間の検出（無音カット）
├─ chatter/          雑談カット（ルールベース／AI 判定）
├─ transcribe.py     faster-whisper による文字起こし
├─ postprocess/      日本語の整形
├─ writers.py        txt / srt / md / cut_log の出力
└─ gui/              進捗ウィンドウ・通知・設定画面
```

### 時刻変換の考え方

音声は 2 段階で短くなります。

```
元ファイル      0 ────────────────────────────── 60:00
                    ↓ 無音カット
無音除去後      0 ──────────────── 42:00
                    ↓ 雑談カット
本編のみ        0 ─────────── 35:00   ← Whisper が返す時刻はこの軸
```

各段で「残した区間」を記録した `SegmentMap` を作り、
`vad_map.then(chatter_map)` で合成します。
出力の直前（`pipeline.to_output_segments`）でのみ元の時間軸に戻すため、
変換漏れが起きません。

### テストを動かす

```bash
python -m pip install pytest numpy
python -m pytest -q
```

`tests/test_segmap.py` が最重要です。境界値、合成の結合法則、
ランダムデータでの往復検証まで行っています。

### 動作確認用のコマンド

```powershell
# GUI を出さずコンソールで確認する
.\.venv\Scripts\python.exe -m transcribe_ja --no-queue --no-gui --console "C:\path\to\音声.mp3"

# 設定画面を開く
.\.venv\Scripts\python.exe -m transcribe_ja --settings

# 設定ファイルを開く
.\.venv\Scripts\python.exe -m transcribe_ja --open-config
```

### 別の言語版を併設する

レジストリキー名は `TranscribeJA` を使っています。
フランス語版を作る場合は、`install.ps1` の `$RegistryKey` を
`TranscribeFR` のように変えれば、同じ拡張子に両方のメニューを共存させられます。

---

## ライセンス

MIT License

使用しているソフトウェアのライセンスは各配布元をご確認ください
（ffmpeg、faster-whisper、Silero VAD など）。
