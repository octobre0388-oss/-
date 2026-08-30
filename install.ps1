<#
.SYNOPSIS
    TranscribeJA（文字起こし（日本語））をセットアップします。

.DESCRIPTION
    次の作業をまとめて行います。管理者権限は不要です。

        1. Python 3.11 以上を探す
        2. 専用の仮想環境 (.venv) を作る
        3. 必要なライブラリを入れる（GPU があれば CUDA 版の torch を選ぶ）
        4. ffmpeg / ffprobe を tools フォルダに用意する
        5. 右クリックメニューに「文字起こし（日本語）」を登録する

.EXAMPLE
    .\install.ps1
        すべて自動で行います。ふつうはこれだけで完了します。

.EXAMPLE
    .\install.ps1 -Cpu
        GPU があっても CPU 版として設定します。

.EXAMPLE
    .\install.ps1 -SkipRegister
        右クリックメニューへの登録だけを行いません（動作確認用）。

.NOTES
    実行がブロックされる場合は、PowerShell で次を実行してください。
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>

[CmdletBinding()]
param(
    [switch]$SkipFfmpeg,      # ffmpeg の準備を飛ばす
    [switch]$SkipRegister,    # 右クリックメニューの登録を飛ばす
    [switch]$SkipLibraries,   # ライブラリのインストールを飛ばす
    [switch]$Cpu,             # GPU があっても CPU 版を入れる
    [switch]$Gpu              # 自動判定に関わらず CUDA 版を入れる
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest を速くする

# ===================================================================
#  設定値
# ===================================================================

$AppName      = 'TranscribeJA'
$MenuLabel    = '文字起こし（日本語）'
$RegistryKey  = 'TranscribeJA'   # フランス語版などを併設しても衝突しない名前にすること

$Root         = $PSScriptRoot
$VenvDir      = Join-Path $Root '.venv'
$ToolsDir     = Join-Path $Root 'tools'
$SrcDir       = Join-Path $Root 'src'
$IconPath     = Join-Path $Root 'assets\transcribe_ja.ico'

# 右クリックメニューを出す拡張子
$Extensions = @(
    '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma', '.opus',
    '.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.ts'
)

$FfmpegZipUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$TorchCudaIndex = 'https://download.pytorch.org/whl/cu124'
$TorchCpuIndex  = 'https://download.pytorch.org/whl/cpu'

# ===================================================================
#  画面表示のための小道具
# ===================================================================

$script:StepNumber = 0

function Write-Step {
    param([string]$Message)
    $script:StepNumber++
    Write-Host ''
    Write-Host "[$script:StepNumber/6] $Message" -ForegroundColor Cyan
}

function Write-Ok      { param([string]$M) Write-Host "      OK   $M" -ForegroundColor Green }
function Write-Info    { param([string]$M) Write-Host "           $M" -ForegroundColor Gray }
function Write-Warn2   { param([string]$M) Write-Host "      注意 $M" -ForegroundColor Yellow }
function Write-Fail    { param([string]$M) Write-Host "      失敗 $M" -ForegroundColor Red }

function Exit-WithError {
    param([string]$Message, [string]$Hint)
    Write-Host ''
    Write-Host '===================================================================' -ForegroundColor Red
    Write-Host ' セットアップを中断しました' -ForegroundColor Red
    Write-Host '===================================================================' -ForegroundColor Red
    Write-Host ''
    Write-Host $Message
    if ($Hint) {
        Write-Host ''
        Write-Host '【対処方法】' -ForegroundColor Yellow
        Write-Host $Hint
    }
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Host '===================================================================' -ForegroundColor White
Write-Host "  $MenuLabel  セットアップ" -ForegroundColor White
Write-Host '===================================================================' -ForegroundColor White
Write-Host "  インストール先: $Root"

# ===================================================================
#  1. Python を探す
# ===================================================================

Write-Step 'Python を探しています'

# Python の探索は、PATH だけに頼らず次の 4 通りで行う。
# PATH に入れずにインストールしている人が多いため、ここを厚くしないと
# 「入っているのに見つからない」という分かりにくい失敗になる。
#
#   1. py ランチャーが把握している一覧（py -0p）
#   2. PATH 上の python / python3
#   3. レジストリ（Python の公式インストーラが登録する）
#   4. よくあるインストール先のフォルダ

$script:StoreStubFound = $false

function Test-StoreStub {
    param([string]$Path)
    # Microsoft Store の「アプリ実行エイリアス」は、Python 本体ではなく
    # ストアを開くだけの 0 バイトのダミー。これを Python と誤認しないようにする。
    if ($Path -like '*\WindowsApps\*') { return $true }
    try {
        if ((Get-Item $Path -Force -ErrorAction Stop).Length -eq 0) { return $true }
    } catch { }
    return $false
}

function Get-PythonCandidates {
    # 重複を除きつつ順序を保つ
    $found = New-Object System.Collections.Specialized.OrderedDictionary

    function Add-Candidate {
        param([string]$Value)
        if ($Value -and -not $found.Contains($Value)) { $found.Add($Value, $true) }
    }

    # --- 1. py ランチャー ---
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        try {
            foreach ($line in (& py -0p 2>$null)) {
                if ("$line" -match '([A-Za-z]:\\[^\r\n]*?python\.exe)') {
                    Add-Candidate $matches[1]
                }
            }
        } catch { }
        foreach ($v in @('-3.13', '-3.12', '-3.11', '-3')) { Add-Candidate "py $v" }
    }

    # --- 2. PATH 上（ストアのダミーは除く） ---
    foreach ($name in @('python', 'python3')) {
        foreach ($cmd in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if (-not $cmd.Source) { continue }
            if (Test-StoreStub $cmd.Source) {
                $script:StoreStubFound = $true
                continue
            }
            Add-Candidate $cmd.Source
        }
    }

    # --- 3. レジストリ ---
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        foreach ($view in @('\Software\Python\PythonCore', '\Software\Wow6432Node\Python\PythonCore')) {
            $base = "$hive$view"
            if (-not (Test-Path $base)) { continue }
            foreach ($key in (Get-ChildItem $base -ErrorAction SilentlyContinue)) {
                try {
                    $installPath = (Get-Item "$($key.PSPath)\InstallPath" -ErrorAction Stop).GetValue('')
                    if ($installPath) { Add-Candidate (Join-Path $installPath 'python.exe') }
                } catch { }
            }
        }
    }

    # --- 4. よくあるインストール先 ---
    $patterns = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        'C:\Python3*\python.exe',
        (Join-Path $env:ProgramFiles 'Python3*\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\Scripts\..\python.exe')
    )
    foreach ($pattern in $patterns) {
        foreach ($item in (Get-ChildItem $pattern -ErrorAction SilentlyContinue)) {
            Add-Candidate $item.FullName
        }
    }

    return @($found.Keys)
}

function Test-PythonVersion {
    param([string]$Invocation)
    try {
        $parts = $Invocation -split ' ', 2
        $exe = $parts[0]
        if ($parts.Count -eq 1 -and (Test-Path $exe) -and (Test-StoreStub $exe)) {
            $script:StoreStubFound = $true
            return $null
        }
        $script = 'import sys;print("%d.%d"%sys.version_info[:2])'
        # $args は PowerShell の自動変数なので、別名を使う
        $cmdArgs = if ($parts.Count -gt 1) { @($parts[1], '-c', $script) } else { @('-c', $script) }
        $out = & $exe @cmdArgs 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        # 出力が複数行になることがあるので、最後の行だけを見る
        $line = (@($out) | Where-Object { "$_".Trim() } | Select-Object -Last 1)
        $version = [version]("$line".Trim())
        if ($version -ge [version]'3.11') { return $version }
        return $null
    } catch {
        return $null
    }
}

$PythonCommand = $null
$PythonVersion = $null
$Checked = @()

foreach ($candidate in Get-PythonCandidates) {
    $Checked += $candidate
    $v = Test-PythonVersion $candidate
    if ($v) {
        $PythonCommand = $candidate
        $PythonVersion = $v
        break
    }
}

if (-not $PythonCommand) {
    $detail = ''
    if ($Checked.Count -gt 0) {
        $detail = "`n次の場所を調べましたが、3.11 以上の Python はありませんでした:`n" +
                  (($Checked | ForEach-Object { "  ・$_" }) -join "`n")
    } else {
        $detail = "`nこのパソコンからは Python が 1 つも見つかりませんでした。"
    }

    $storeNote = ''
    if ($script:StoreStubFound) {
        $storeNote = @"

【重要】
「python」というコマンドは見つかりましたが、これは Microsoft Store を開くだけの
ダミーで、Python 本体ではありません。下の手順でインストールしてください。
（コマンド プロンプトで python と打つとストアが開くのは、この仕組みのためです）
"@
    }

    Exit-WithError `
        "Python 3.11 以上が見つかりませんでした。$detail" `
        @"
Python をインストールしてください。おすすめは Microsoft Store 版です。

■ 方法A: Microsoft Store（かんたん・管理者権限不要）
   1. Windows キーを押して「Microsoft Store」と入力し、ストアを開く
   2. 検索欄に「Python 3.12」と入力する
   3. 「Python 3.12」（発行元: Python Software Foundation）を選び「入手」
   4. インストールが終わったら、この PowerShell の窓を一度閉じる

■ 方法B: python.org
   1. https://www.python.org/downloads/windows/ を開く
   2. 「Latest Python 3 Release」→ ページ下部の
      「Windows installer (64-bit)」をダウンロード
   3. 実行し、最初の画面で
      ★「Add python.exe to PATH」に必ずチェックを入れてから★
      「Install Now」をクリック
$storeNote
インストールが終わったら、PowerShell を開き直してから
install.ps1 をもう一度実行してください。
（開いたままだと、新しくインストールした Python が認識されません）
"@
}
Write-Ok "Python $PythonVersion を使います（$PythonCommand）"

# ===================================================================
#  2. 仮想環境を作る
# ===================================================================

Write-Step '専用の Python 環境を作っています'

$VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPythonW = Join-Path $VenvDir 'Scripts\pythonw.exe'

if (Test-Path $VenvPython) {
    Write-Ok '既存の環境が見つかりました（作り直しません）'
} else {
    try {
        $parts = $PythonCommand -split ' ', 2
        if ($parts.Count -gt 1) {
            & $parts[0] $parts[1] -m venv $VenvDir
        } else {
            & $parts[0] -m venv $VenvDir
        }
    } catch {
        Exit-WithError "Python の仮想環境を作れませんでした。`n$($_.Exception.Message)" `
            "ウイルス対策ソフトが書き込みを止めていないかご確認ください。"
    }
    if (-not (Test-Path $VenvPython)) {
        Exit-WithError '仮想環境の作成に失敗しました。' `
            "別の場所（例: C:\Users\<ユーザー名>\TranscribeJA）にフォルダごと移してからお試しください。"
    }
    Write-Ok "作成しました: $VenvDir"
}

# ※ プログラム本体を import できるようにする処理は、
#    ライブラリのインストール（手順3）の最後に行います。

# ===================================================================
#  3. ライブラリを入れる
# ===================================================================

Write-Step '必要なライブラリを入れています（数分〜十数分かかります）'

if ($SkipLibraries) {
    Write-Warn2 '-SkipLibraries が指定されたため飛ばします'
} else {
    # --- GPU の有無を調べる ---
    $useGpu = $false
    if ($Gpu) {
        $useGpu = $true
        Write-Info 'GPU 版を指定されました'
    } elseif ($Cpu) {
        Write-Info 'CPU 版を指定されました'
    } elseif (Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue) {
        $useGpu = $true
        Write-Ok 'NVIDIA の GPU を検出しました。CUDA 版を入れます'
    } else {
        Write-Info 'GPU が見つからないため CPU 版を入れます（動作します。処理は遅くなります）'
    }

    & $VenvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warn2 'pip の更新に失敗しましたが続行します' }

    # --- torch は GPU/CPU で入れ分ける（CPU 版はダウンロード量が大幅に少ない）---
    $torchIndex = if ($useGpu) { $TorchCudaIndex } else { $TorchCpuIndex }
    Write-Info "torch を取得しています（$(if ($useGpu) { 'CUDA 版・約 2.5GB' } else { 'CPU 版・約 200MB' })）"
    & $VenvPython -m pip install torch --index-url $torchIndex
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 'torch のインストールに失敗しました。通常版で再試行します'
        & $VenvPython -m pip install torch
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 'torch を入れられませんでした。無音カットは簡易方式で動作します'
        }
    }

    # --- 残りのライブラリ ---
    $requirements = Join-Path $Root 'requirements.txt'
    Write-Info '文字起こしライブラリなどを取得しています'
    & $VenvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Exit-WithError 'ライブラリのインストールに失敗しました。' `
            @"
インターネット接続をご確認のうえ、もう一度 install.ps1 を実行してください。
社内ネットワークでプロキシをお使いの場合は、次のように設定してから実行してください。

    `$env:HTTPS_PROXY = "http://プロキシのアドレス:ポート"
"@
    }
    Write-Ok 'ライブラリの準備ができました'
}

# --- プログラム本体を import できるようにする ---
# pip の編集可能インストールを使う。
# 単純に .pth ファイルへパスを書く方法もあるが、.pth は Python のバージョンに
# よって想定する文字コードが異なり、ユーザー名に日本語が含まれるパス
# （例: C:\Users\山田\TranscribeJA）で読み込みに失敗することがある。
# pip の方式は経路情報を UTF-8 の .py に持つため、その問題が起きない。
Write-Info 'プログラム本体を登録しています'
& $VenvPython -m pip install -e $Root --no-deps --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 '通常の方法で登録できなかったため、簡易な方法に切り替えます'
    $SitePackages = Join-Path $VenvDir 'Lib\site-packages'
    if (Test-Path $SitePackages) {
        # 非 ASCII 文字を含むパスではこの方法が使えないことがある
        if ($SrcDir -match '[^\u0000-\u007F]') {
            Exit-WithError `
                "フォルダのパスに日本語が含まれているため、登録に失敗しました。`n$SrcDir" `
                @"
このツールのフォルダを、英数字だけのパスに移してからやり直してください。

  例) C:\TranscribeJA
      C:\Users\<ユーザー名>\Documents\TranscribeJA

※ 処理する音声・動画ファイルのほうは、日本語のファイル名・フォルダ名でも
   問題ありません。
"@
        }
        Set-Content -Path (Join-Path $SitePackages 'transcribe_ja.pth') -Value $SrcDir -Encoding ASCII
        Write-Ok 'プログラム本体の場所を登録しました'
    }
} else {
    Write-Ok 'プログラム本体を登録しました'
}

# ===================================================================
#  4. ffmpeg を用意する
# ===================================================================

Write-Step 'ffmpeg を用意しています'

function Find-BundledFfmpeg {
    if (-not (Test-Path $ToolsDir)) { return $null }
    $exe = Get-ChildItem -Path $ToolsDir -Filter 'ffmpeg.exe' -Recurse -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($exe) { return $exe.FullName }
    return $null
}

function Copy-FfmpegFrom {
    param([string]$SourceDir)
    $target = Join-Path $ToolsDir 'ffmpeg'
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $copied = 0
    foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
        $found = Get-ChildItem -Path $SourceDir -Filter $name -Recurse -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) {
            Copy-Item $found.FullName -Destination (Join-Path $target $name) -Force
            $copied++
        }
    }
    return $copied -eq 2
}

if ($SkipFfmpeg) {
    Write-Warn2 '-SkipFfmpeg が指定されたため飛ばします'
} elseif ($existingFfmpeg = Find-BundledFfmpeg) {
    Write-Ok "既に用意されています: $existingFfmpeg"
} else {
    New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
    $done = $false

    # --- 方法1: winget で入れて、tools フォルダにコピーする ---
    if (Get-Command 'winget' -ErrorAction SilentlyContinue) {
        Write-Info 'winget で ffmpeg を探しています'
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements --silent 2>$null | Out-Null

        # winget 直後は PATH が更新されていないので、環境変数を読み直す
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $installed = Get-Command 'ffmpeg' -ErrorAction SilentlyContinue
        if ($installed) {
            # PATH に依存しないよう、本ツールの tools フォルダへ複製する
            if (Copy-FfmpegFrom (Split-Path $installed.Source -Parent)) {
                Write-Ok 'winget で取得し、tools フォルダに配置しました'
                $done = $true
            }
        }
    }

    # --- 方法2: 直接ダウンロードする ---
    if (-not $done) {
        Write-Info 'ffmpeg をダウンロードしています（約 80MB）'
        $zipPath = Join-Path $env:TEMP 'transcribe_ja_ffmpeg.zip'
        $extractDir = Join-Path $env:TEMP 'transcribe_ja_ffmpeg'
        try {
            Invoke-WebRequest -Uri $FfmpegZipUrl -OutFile $zipPath -UseBasicParsing
            if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
            Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
            if (Copy-FfmpegFrom $extractDir) {
                Write-Ok 'ダウンロードして tools フォルダに配置しました'
                $done = $true
            }
        } catch {
            Write-Fail $_.Exception.Message
        } finally {
            Remove-Item $zipPath -ErrorAction SilentlyContinue
            Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $done) {
        Exit-WithError 'ffmpeg を用意できませんでした。' `
            @"
お手数ですが、手動で配置してください。

  1. https://www.gyan.dev/ffmpeg/builds/ を開く
  2. 「ffmpeg-release-essentials.zip」をダウンロードする
  3. zip を展開し、中の bin フォルダにある
         ffmpeg.exe と ffprobe.exe
     を次のフォルダにコピーする
         $ToolsDir\ffmpeg\
  4. install.ps1 をもう一度実行する
"@
    }
}

# ===================================================================
#  5. 右クリックメニューに登録する
# ===================================================================

Write-Step '右クリックメニューに登録しています'

# --------------------------------------------------------------------
#  【メモ】Windows 11 のモダンメニュー（Shift 不要の第一階層）について
#
#  本スクリプトが登録するのは「従来型（クラシック）メニュー」です。
#  Windows 11 では、ファイルを右クリックしたあと
#      「その他のオプションを表示」（または Shift + 右クリック）
#  を選ぶと表示されます。
#
#  Shift を押さずに出る第一階層のメニュー（モダンメニュー）に項目を出すには、
#  レジストリだけでは不可能で、次のすべてが必要になります。
#
#    1. IExplorerCommand インターフェースを実装した COM の DLL を作る
#       （C++ / C# / Rust などのコンパイル言語が必要。Python では作れません）
#    2. その DLL を「スパースパッケージ」と呼ばれる MSIX パッケージに含める
#       AppxManifest.xml に <desktop4:Extension Category="windows.fileExplorerContextMenus">
#       を記述し、対象拡張子と CLSID を登録する
#    3. パッケージに署名する（自己署名証明書でも可。ただし利用者側で
#       その証明書を「信頼されたルート証明機関」に入れる作業が必要）
#    4. Add-AppxPackage -Register でパッケージを登録する
#
#  つまり「管理者権限なしで、初心者でも実行できるセットアップ」という
#  本ツールの前提と両立しないため、あえて従来型メニューを採用しています。
#
#  参考: Microsoft の公式サンプル
#    https://github.com/microsoft/AppModelSamples/tree/master/Samples/SparsePackages
#
#  なお Windows 11 では、右クリック後に Shift+F10 を押すか、
#  設定で「常に従来型メニューを表示する」ようにもできます（README に記載）。
# --------------------------------------------------------------------

if ($SkipRegister) {
    Write-Warn2 '-SkipRegister が指定されたため飛ばします'
} else {
    if (-not (Test-Path $VenvPythonW)) {
        Exit-WithError "pythonw.exe が見つかりません: $VenvPythonW" `
            'install.ps1 を最初からもう一度実行してください。'
    }

    # pythonw.exe を使うことで、実行時に黒いコンソール画面が出ないようにする
    $command = '"{0}" -m transcribe_ja "%1"' -f $VenvPythonW

    $iconValue = ''
    if (Test-Path $IconPath) { $iconValue = $IconPath }

    $registered = 0
    foreach ($ext in $Extensions) {
        # HKEY_CURRENT_USER の下に作るので管理者権限は不要
        $shellKey   = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\$RegistryKey"
        $commandKey = "$shellKey\command"
        try {
            New-Item -Path $commandKey -Force | Out-Null
            Set-ItemProperty -Path $shellKey -Name '(Default)' -Value $MenuLabel
            if ($iconValue) {
                Set-ItemProperty -Path $shellKey -Name 'Icon' -Value $iconValue
            }
            Set-ItemProperty -Path $commandKey -Name '(Default)' -Value $command
            $registered++
        } catch {
            Write-Warn2 "$ext の登録に失敗しました: $($_.Exception.Message)"
        }
    }
    Write-Ok "$registered 種類の拡張子に登録しました"
    Write-Info "メニュー名: $MenuLabel"
}

# ===================================================================
#  6. 動作確認
# ===================================================================

Write-Step '動作を確認しています'

& $VenvPython -m transcribe_ja --version
if ($LASTEXITCODE -ne 0) {
    Exit-WithError 'プログラムを起動できませんでした。' `
        "install.ps1 をもう一度実行しても直らない場合は、README の「インストールがうまくいかないとき」をご覧ください。"
}
Write-Ok '正常に起動できました'

# 設定ファイルと判定辞書を既定値で作っておく（初回起動を待たずに編集できるように）。
# --open-config はメモ帳が開いてしまうので、ここでは作成だけを行う。
& $VenvPython -c "from transcribe_ja.config import load; load()" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Ok '設定ファイルを作成しました' }

Write-Host ''
Write-Host '===================================================================' -ForegroundColor Green
Write-Host '  セットアップが完了しました' -ForegroundColor Green
Write-Host '===================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  使い方:'
Write-Host '    1. 音声ファイルや動画ファイルを右クリック'
Write-Host '    2. 「その他のオプションを表示」をクリック'
Write-Host "       （Windows 11 の場合。Shift + 右クリックでも同じです）"
Write-Host "    3. 「$MenuLabel」をクリック"
Write-Host ''
Write-Host '  ★ 最初の 1 回だけ、文字起こしモデルのダウンロードに' -ForegroundColor Yellow
Write-Host '     10〜30 分ほどかかります（1.5〜3GB）。2 回目以降は不要です。' -ForegroundColor Yellow
Write-Host ''
Write-Host '  設定ファイル:'
Write-Host "    $env:APPDATA\$AppName\config.toml"
Write-Host '  ログ:'
Write-Host "    $env:APPDATA\$AppName\logs\"
Write-Host ''
Write-Host '  取り消したいときは uninstall.ps1 を実行してください。'
Write-Host ''
