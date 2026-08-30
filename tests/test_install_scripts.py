"""install.ps1 / uninstall.ps1 と Python 側の設定がずれていないかを確認する。

拡張子の一覧やレジストリキー名が食い違うと、
「右クリックには出るのに処理できない」「アンインストールしても消えない」
といった分かりにくい不具合になるため、テストで縛っておく。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from transcribe_ja import MENU_LABEL
from transcribe_ja.pipeline import SUPPORTED_EXTENSIONS

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.ps1"
UNINSTALL = ROOT / "uninstall.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _extensions(text: str) -> set[str]:
    match = re.search(r"\$Extensions = @\((.*?)\)", text, re.S)
    assert match, "$Extensions の定義が見つからない"
    return set(re.findall(r"'(\.[a-z0-9]+)'", match.group(1)))


@pytest.mark.parametrize("path", [INSTALL, UNINSTALL])
def test_スクリプトが存在する(path: Path):
    assert path.is_file()


@pytest.mark.parametrize("path", [INSTALL, UNINSTALL])
def test_UTF8のBOM付きで保存されている(path: Path):
    """Windows PowerShell 5.1 は BOM が無いと日本語を文字化けさせるため。"""
    assert path.read_bytes()[:3] == b"\xef\xbb\xbf", f"{path.name} に BOM がない"


@pytest.mark.parametrize("path", [INSTALL, UNINSTALL])
def test_対応拡張子がPython側と一致する(path: Path):
    assert _extensions(_read(path)) == SUPPORTED_EXTENSIONS


def test_インストールとアンインストールで拡張子が一致する():
    assert _extensions(_read(INSTALL)) == _extensions(_read(UNINSTALL))


def _variable(text: str, name: str) -> str:
    """PowerShell の `$名前 = '値'` から値を取り出す（空白の数は問わない）。"""
    match = re.search(rf"\${name}\s*=\s*'([^']*)'", text)
    assert match, f"${name} の定義が見つからない"
    return match.group(1)


@pytest.mark.parametrize("path", [INSTALL, UNINSTALL])
def test_レジストリキー名が同じ(path: Path):
    """将来フランス語版を併設したときに衝突しないよう、専用のキー名を使う。"""
    assert _variable(_read(path), "RegistryKey") == "TranscribeJA"


@pytest.mark.parametrize("path", [INSTALL, UNINSTALL])
def test_メニュー表示名がPython側と一致する(path: Path):
    assert _variable(_read(path), "MenuLabel") == MENU_LABEL


def test_登録先はHKCUで管理者権限が不要():
    """右クリックメニューの登録は HKCU にのみ書き込むこと。

    HKLM への書き込みには管理者権限が必要になってしまう。
    （Python の場所を調べるための HKLM の「読み取り」は権限不要なので問題ない）
    """
    text = _read(INSTALL)
    assert "HKCU:\\Software\\Classes\\SystemFileAssociations" in text

    # レジストリに書き込むコマンドの行に HKLM が出てこないこと
    writers = ("New-Item", "Set-ItemProperty", "New-ItemProperty", "reg add", "Remove-Item")
    for line in text.splitlines():
        if any(w in line for w in writers) and "HKLM" in line:
            raise AssertionError(f"HKLM へ書き込もうとしている: {line.strip()}")

    # HKLM が登場するのは読み取り専用の用途だけであること
    readers = ("Test-Path", "Get-ChildItem", "Get-Item", "$hive", "'HKLM:'")
    for line in text.splitlines():
        if "HKLM" in line:
            assert any(r in line for r in readers), f"HKLM の使い方が不明: {line.strip()}"


def test_アンインストールはキーごと削除する():
    text = _read(UNINSTALL)
    assert "Remove-Item -Path $shellKey -Recurse -Force" in text


def test_黒い窓が出ないようpythonwを使う():
    assert "pythonw.exe" in _read(INSTALL)


def test_モダンメニューの解説が残されている():
    """要件: モダンメニューに出す方法をコメントで解説すること。"""
    text = _read(INSTALL)
    assert "IExplorerCommand" in text
    assert "スパースパッケージ" in text or "MSIX" in text


def test_アイコンが用意されている():
    icon = ROOT / "assets" / "transcribe_ja.ico"
    assert icon.is_file()
    # ICO ファイルのシグネチャ（予約領域 0 / 種別 1 = アイコン）
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_インストールはアイコンを登録する():
    assert "Set-ItemProperty -Path $shellKey -Name 'Icon'" in _read(INSTALL)


# --- PowerShell 特有の落とし穴に対する回帰テスト -----------------------------


def _code_lines(text: str) -> list[str]:
    """コメント行と説明用の here-string を除いた、実際に動く行だけを返す。"""
    lines = []
    in_help = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<#"):
            in_help = True
        if in_help:
            if stripped.endswith("#>"):
                in_help = False
            continue
        if stripped.startswith("#") or not stripped:
            continue
        lines.append(line)
    return lines


def test_ネイティブコマンドの引数にダブルクォートを埋め込まない():
    """Windows PowerShell 5.1 は、外部コマンドへ渡す引数の中の
    ダブルクォートをエスケープしない。

        -c "import sys;print("...")"   → Python には import sys;print(...) が届く

    そのため引数の中にダブルクォートを含めると、必ず壊れた形で渡される。
    （この不具合で Python の検出が常に失敗していた）
    """
    for line in _code_lines(_read(INSTALL)) + _code_lines(_read(UNINSTALL)):
        if " -c " not in line:
            continue
        after = line.split(" -c ", 1)[1]
        assert after.count('"') <= 2, (
            "外部コマンドの引数にダブルクォートが埋め込まれています。\n"
            f"  {line.strip()}"
        )


def test_版数の判定はVオプションを使う():
    """引数にクォートを含まない -V なら、上記の問題を避けられる。"""
    text = _read(INSTALL)
    assert "@($parts[1], '-V')" in text
    assert "Python\\s+(\\d+)\\.(\\d+)" in text


def test_新しすぎるPythonより実績のある版を優先する():
    """既定が 3.14 のような新しい版でも、torch が入る版を選ぶこと。"""
    text = _read(INSTALL)
    assert "$PreferredVersions = @('3.12', '3.13', '3.11')" in text
    assert "Get-VersionRank" in text


def test_Pythonを手動指定できる():
    """自動検出が外れたときの逃げ道があること。"""
    assert "[string]$PythonPath" in _read(INSTALL)
