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
    text = _read(INSTALL)
    assert "HKCU:\\Software\\Classes\\SystemFileAssociations" in text
    assert "HKLM" not in text, "管理者権限が必要な HKLM を使ってはいけない"


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
