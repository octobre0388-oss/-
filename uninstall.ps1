<#
.SYNOPSIS
    TranscribeJA（文字起こし（日本語））を取り消します。

.DESCRIPTION
    既定では、右クリックメニューの登録だけを完全に削除します。
    設定・ログ・ダウンロード済みモデル・Python 環境は残るため、
    install.ps1 を実行すればすぐに元どおり使えます。

.EXAMPLE
    .\uninstall.ps1
        右クリックメニューの登録だけを削除します。

.EXAMPLE
    .\uninstall.ps1 -All
        設定・ログ・仮想環境・ffmpeg もまとめて削除します（確認あり）。

.EXAMPLE
    .\uninstall.ps1 -All -Force
        確認なしで全部削除します。

.NOTES
    管理者権限は不要です。
    文字起こしモデル（%USERPROFILE%\.cache\huggingface）は容量が大きいため、
    -All を指定した場合に削除方法を案内します（自動では消しません）。
#>

[CmdletBinding()]
param(
    [switch]$All,     # 設定・ログ・仮想環境・ffmpeg も削除する
    [switch]$Force    # 確認を省略する
)

$ErrorActionPreference = 'Stop'

$AppName     = 'TranscribeJA'
$MenuLabel   = '文字起こし（日本語）'
$RegistryKey = 'TranscribeJA'

$Root    = $PSScriptRoot
$VenvDir = Join-Path $Root '.venv'
$ToolsDir = Join-Path $Root 'tools'
$AppData = Join-Path $env:APPDATA $AppName

# install.ps1 と同じ一覧にしておくこと
$Extensions = @(
    '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma', '.opus',
    '.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.ts'
)

function Write-Ok   { param([string]$M) Write-Host "  OK   $M" -ForegroundColor Green }
function Write-Info { param([string]$M) Write-Host "       $M" -ForegroundColor Gray }
function Write-Warn2 { param([string]$M) Write-Host "  注意 $M" -ForegroundColor Yellow }

Write-Host ''
Write-Host '===================================================================' -ForegroundColor White
Write-Host "  $MenuLabel  アンインストール" -ForegroundColor White
Write-Host '===================================================================' -ForegroundColor White
Write-Host ''

# ===================================================================
#  1. 右クリックメニューの登録を消す
# ===================================================================

Write-Host '[1/2] 右クリックメニューの登録を削除しています' -ForegroundColor Cyan

$removed = 0
$missing = 0
foreach ($ext in $Extensions) {
    $shellKey = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\$RegistryKey"
    if (Test-Path $shellKey) {
        try {
            # -Recurse で command サブキーごと消す（キーを残さない）
            Remove-Item -Path $shellKey -Recurse -Force
            $removed++
        } catch {
            Write-Warn2 "$ext の削除に失敗しました: $($_.Exception.Message)"
        }
    } else {
        $missing++
    }
}
Write-Ok "$removed 種類の拡張子から削除しました"
if ($missing -gt 0) {
    Write-Info "$missing 種類は登録されていませんでした（削除済みです）"
}

# 空になった親キー（shell / SystemFileAssociations\<ext>）も掃除する。
# 他のツールが使っている可能性があるため、子を持たないものだけ消す。
foreach ($ext in $Extensions) {
    foreach ($suffix in @("\shell", "")) {
        $key = "HKCU:\Software\Classes\SystemFileAssociations\$ext$suffix"
        if (-not (Test-Path $key)) { continue }
        $item = Get-Item $key
        if ($item.SubKeyCount -eq 0 -and $item.ValueCount -eq 0) {
            Remove-Item -Path $key -Force -ErrorAction SilentlyContinue
        }
    }
}

# 念のため、登録が本当に消えたかを確認する
$leftover = @()
foreach ($ext in $Extensions) {
    $shellKey = "HKCU:\Software\Classes\SystemFileAssociations\$ext\shell\$RegistryKey"
    if (Test-Path $shellKey) { $leftover += $ext }
}
if ($leftover.Count -gt 0) {
    Write-Warn2 "次の拡張子の登録が残っています: $($leftover -join ', ')"
    Write-Info 'PowerShell を開き直してから、もう一度実行してみてください。'
} else {
    Write-Ok '登録はすべて削除されました'
}

# ===================================================================
#  2. データの削除（-All のときだけ）
# ===================================================================

Write-Host ''
Write-Host '[2/2] 設定・ログ・プログラムの削除' -ForegroundColor Cyan

if (-not $All) {
    Write-Info '既定では削除しません（-All を付けると削除します）'
    Write-Info "設定とログ: $AppData"
    Write-Info "Python 環境: $VenvDir"
} else {
    $targets = @()
    if (Test-Path $AppData)  { $targets += $AppData }
    if (Test-Path $VenvDir)  { $targets += $VenvDir }
    if (Test-Path $ToolsDir) { $targets += $ToolsDir }

    if ($targets.Count -eq 0) {
        Write-Info '削除するものはありませんでした'
    } else {
        Write-Host ''
        Write-Host '  次のフォルダを削除します:' -ForegroundColor Yellow
        foreach ($t in $targets) { Write-Host "    $t" }
        Write-Host ''

        $ok = $Force
        if (-not $ok) {
            $answer = Read-Host '  本当に削除しますか？ (y/N)'
            $ok = ($answer -eq 'y' -or $answer -eq 'Y')
        }

        if ($ok) {
            foreach ($t in $targets) {
                try {
                    Remove-Item -Path $t -Recurse -Force
                    Write-Ok "削除しました: $t"
                } catch {
                    Write-Warn2 "削除できませんでした: $t"
                    Write-Info '　エクスプローラーやコマンドプロンプトで開いていないかご確認ください。'
                }
            }
        } else {
            Write-Info 'キャンセルしました'
        }
    }

    # モデルは他のツールと共有されることがあるので、自動では消さない
    $modelCache = Join-Path $env:USERPROFILE '.cache\huggingface'
    if (Test-Path $modelCache) {
        Write-Host ''
        Write-Warn2 'ダウンロード済みの文字起こしモデルは残しています。'
        Write-Info '他のソフトと共有している場合があるためです。削除したい場合は、'
        Write-Info 'エクスプローラーで次のフォルダを開いて削除してください（数GB あります）。'
        Write-Info "  $modelCache"
    }
}

Write-Host ''
Write-Host '===================================================================' -ForegroundColor Green
Write-Host '  アンインストールが完了しました' -ForegroundColor Green
Write-Host '===================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  もう一度使いたくなったら install.ps1 を実行してください。'
Write-Host ''
