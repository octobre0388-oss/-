"""設定ファイルの生成・読み込み・検証のテスト。"""

from __future__ import annotations

import pytest

from transcribe_ja import config as C
from transcribe_ja.errors import ConfigError


def test_既定設定は同梱ファイルから読める():
    defaults = C.load_defaults()
    assert defaults["whisper"]["model"] == "auto"
    assert defaults["chatter"]["safety"] == "conservative"


def test_初回は既定値でファイルが作られる(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_JA_HOME", str(tmp_path))
    path = C.ensure_config_file()
    assert path.exists()
    assert "TranscribeJA 設定ファイル" in path.read_text(encoding="utf-8")


def test_辞書ファイルがコピーされる(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_JA_HOME", str(tmp_path))
    directory = C.ensure_dictionaries()
    assert (directory / "chatter_ja.toml").exists()
    assert (directory / "fillers_ja.toml").exists()


def test_利用者の編集が既定値より優先される(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[whisper]\nmodel = "small"\n', encoding="utf-8")
    config = C.load(path)
    assert config.whisper.model == "small"
    # 書かれていない項目は既定値のまま
    assert config.whisper.beam_size == 5


def test_項目が足りなくても壊れない(tmp_path):
    """バージョンアップで項目が増えても、古い設定ファイルで動くこと。"""
    path = tmp_path / "config.toml"
    path.write_text('[general]\nlanguage = "ja"\n', encoding="utf-8")
    config = C.load(path)
    assert config.output.formats
    assert config.vad.min_silence_ms == 700


def test_知らない項目は読み飛ばす(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[whisper]\nmodel = "small"\nfuture_option = 123\n', encoding="utf-8")
    assert C.load(path).whisper.model == "small"


def test_書式が壊れていたら日本語で知らせる(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[whisper\nmodel = small", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        C.load(path)
    message = excinfo.value.user_message()
    assert "書式" in message
    assert "削除する" in message


@pytest.mark.parametrize(
    "内容,含まれる語",
    [
        ('[whisper]\nmodel = "gpt"\n', "model"),
        ('[vad]\nthreshold = 5.0\n', "threshold"),
        ('[chatter]\nsafety = "wild"\n', "safety"),
        ('[audio]\nnormalize = "loud"\n', "normalize"),
        ('[format]\nnumbers = "roman"\n', "numbers"),
        ('[output]\nformats = ["pdf"]\n', "formats"),
        ('[output]\nformats = []\n', "formats"),
        ('[audio]\ntrack = 0\n', "track"),
    ],
)
def test_不正な値は日本語で理由を説明する(tmp_path, 内容, 含まれる語):
    path = tmp_path / "config.toml"
    path.write_text(内容, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        C.load(path)
    assert 含まれる語 in excinfo.value.message


def test_型が違えば日本語で知らせる(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[vad]\nmin_silence_ms = "長め"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        C.load(path)
    assert "数値" in excinfo.value.message


def test_真偽値の項目に文字列を書いたら知らせる(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[general]\nkeep_temp = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        C.load(path)
    assert "true" in excinfo.value.message


def test_出力形式の判定():
    config = C.Config()
    config.output.formats = ["txt", "srt"]
    assert config.wants("txt")
    assert not config.wants("md")


def test_既定設定ファイルは検証を通る():
    """同梱している既定値そのものが不正だと初回起動で必ず失敗するため。"""
    C.validate(C.from_dict(C.load_defaults()))
