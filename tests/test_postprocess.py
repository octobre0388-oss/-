"""日本語の整形処理のテスト。"""

from __future__ import annotations

import pytest

from transcribe_ja.config import FormatConfig
from transcribe_ja.postprocess import format_text, load_fillers, load_numbers
from transcribe_ja.postprocess.fillers import remove_fillers
from transcribe_ja.postprocess.normalize import (
    convert_numbers,
    int_to_kanji,
    kanji_to_int,
    normalize_text,
)
from transcribe_ja.postprocess.punctuation import ensure_sentence_end, fix_punctuation
from transcribe_ja.postprocess.restate import fix_restatements


@pytest.fixture(scope="module")
def フィラー辞書():
    return load_fillers()


@pytest.fixture(scope="module")
def 数字辞書():
    return load_numbers()


# --- フィラー除去 -----------------------------------------------------------


@pytest.mark.parametrize(
    "入力,期待",
    [
        ("えー、これはですね。", "これはですね。"),
        ("えーっと、確認します。", "確認します。"),
        ("あのー、大丈夫です。", "大丈夫です。"),
        ("なんか、うまくいかないです。", "うまくいかないです。"),
    ],
)
def test_フィラーが除去される(入力, 期待, フィラー辞書):
    assert fix_punctuation(remove_fillers(入力, フィラー辞書)) == 期待


@pytest.mark.parametrize(
    "入力",
    [
        "あの人に聞いてください。",
        "その資料をください。",
        "ちょっと待ってください。",
        "まあまあの出来です。",
    ],
)
def test_普通の言葉としての用法は残す(入力, フィラー辞書):
    """「あの人」の「あの」まで消してしまわないこと。"""
    assert remove_fillers(入力, フィラー辞書) == 入力


def test_連続した相槌はまとめられる(フィラー辞書):
    assert remove_fillers("はい、はい、はい、そうです。", フィラー辞書).count("はい") == 1


def test_辞書のkeepに入れた言い回しは守られる(フィラー辞書):
    assert remove_fillers("はい、承知しました。", フィラー辞書) == "はい、承知しました。"


def test_フィラーだけの発話は空になる(フィラー辞書):
    assert fix_punctuation(remove_fillers("えー、あのー、うーん。", フィラー辞書)) == ""


# --- 言い直し ---------------------------------------------------------------


@pytest.mark.parametrize(
    "入力,期待",
    [
        ("これは、これはですね、大事です。", "これはですね、大事です。"),
        ("つまり、つまり結論はこうです。", "つまり結論はこうです。"),
        ("そうですね、そうですね。", "そうですね。"),
    ],
)
def test_言い直しが整理される(入力, 期待):
    assert fix_restatements(入力) == 期待


def test_途中から言い直した場合もつながる():
    """「A の X、X の B」の形。読点を取って 1 文にまとめる。"""
    assert (
        fix_restatements("資料の3ページ目の、3ページ目の予算を検討します。")
        == "資料の3ページ目の予算を検討します。"
    )
    assert fix_restatements("明日は雨です、雨ですが出かけます。") == "明日は雨ですが出かけます。"


@pytest.mark.parametrize(
    "入力",
    [
        "資料は、明日までに提出します。",
        "赤いのと、赤いのじゃない方をください。",
        "本日は、晴天なり。",
    ],
)
def test_別の内容の並列は残す(入力):
    """正当な並列表現まで壊さないこと。"""
    assert fix_restatements(入力) == 入力


# --- 表記の統一 -------------------------------------------------------------


def test_全角英数字が半角になる():
    assert normalize_text("ＡＢＣ１２３です") == "ABC123です"


def test_日本語の間の空白は削除される():
    assert normalize_text("これは テスト です") == "これはテストです"


def test_英単語の間の空白は残る():
    assert "Python file" in normalize_text("Python file を開きます")


def test_半角記号が日本語の句読点になる():
    assert normalize_text("これはテストです．はい，そうです") == "これはテストです。はい、そうです"


def test_句読点の前の空白が消える():
    assert normalize_text("そうですね 、はい") == "そうですね、はい"


# --- 数字 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "漢数字,数値",
    [("三", 3), ("十", 10), ("十五", 15), ("三十五", 35), ("百二十", 120), ("一万五千", 15000)],
)
def test_漢数字を数値に変換できる(漢数字, 数値):
    assert kanji_to_int(漢数字) == 数値


@pytest.mark.parametrize("数値", [0, 3, 10, 15, 35, 120, 1500, 15000, 120000])
def test_数値と漢数字は往復できる(数値):
    assert kanji_to_int(int_to_kanji(数値)) == 数値


def test_助数詞が続く漢数字は算用数字になる(数字辞書):
    assert convert_numbers("資料の三ページ目です", "arabic", 数字辞書) == "資料の3ページ目です"


def test_熟語の漢数字は変換されない(数字辞書):
    assert convert_numbers("一般的な話です", "arabic", 数字辞書) == "一般的な話です"


def test_漢数字モードでは算用数字が漢数字になる(数字辞書):
    assert convert_numbers("15人います", "kanji", 数字辞書) == "十五人います"


def test_時刻や小数は漢数字にしない(数字辞書):
    assert convert_numbers("10:30に3.5個", "kanji", 数字辞書) == "10:30に3.5個"


def test_keepモードでは変換しない(数字辞書):
    assert convert_numbers("三ページ", "keep", 数字辞書) == "三ページ"


# --- 句読点 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "入力,期待",
    [
        ("これは、、そうです。", "これは、そうです。"),
        ("そうです。。", "そうです。"),
        ("、はじめます。", "はじめます。"),
        ("そうですね、", "そうですね。"),
        ("本当ですか！。", "本当ですか！"),
    ],
)
def test_句読点が整う(入力, 期待):
    assert fix_punctuation(入力) == 期待


def test_段落末に句点を補う():
    assert ensure_sentence_end("これで終わります") == "これで終わります。"
    assert ensure_sentence_end("終わりました。") == "終わりました。"


# --- 全体 -------------------------------------------------------------------


def test_全部まとめて整形できる(フィラー辞書, 数字辞書):
    text = "えー、あの、これは、これはですね、まあ、資料の三ページ目です。"
    assert (
        format_text(text, FormatConfig(), フィラー辞書, 数字辞書)
        == "これはですね、資料の3ページ目です。"
    )


def test_設定を切れば整形しない(フィラー辞書, 数字辞書):
    cfg = FormatConfig(
        remove_fillers=False,
        fix_restatements=False,
        normalize_width=False,
        numbers="keep",
        fix_punctuation=False,
    )
    text = "えー、あの、これはですね。"
    assert format_text(text, cfg, フィラー辞書, 数字辞書) == text


def test_セグメント整形では空になったものが落ちる(フィラー辞書, 数字辞書):
    from transcribe_ja.postprocess import format_segments
    from transcribe_ja.writers import OutputSegment

    segments = [
        OutputSegment(0, 1, "えー、あのー。"),
        OutputSegment(1, 3, "資料を確認します。"),
    ]
    result = format_segments(segments, FormatConfig())
    assert len(result) == 1
    assert result[0].text == "資料を確認します。"
    # 時刻は変わらないこと
    assert result[0].start == 1 and result[0].end == 3
