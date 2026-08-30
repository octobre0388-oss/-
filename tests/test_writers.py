"""出力ファイルの書式と、上書き防止のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from transcribe_ja.writers import (
    CutEntry,
    OutputMeta,
    OutputSegment,
    format_timestamp_readable,
    format_timestamp_srt,
    group_paragraphs,
    render_cut_log,
    render_md,
    render_srt,
    render_txt,
    write_outputs,
)


@pytest.fixture()
def セグメント():
    return [
        OutputSegment(0.0, 3.0, "本日はお集まりいただきありがとうございます。"),
        OutputSegment(3.2, 7.0, "まず資料の3ページ目をご覧ください。"),
        OutputSegment(400.0, 404.0, "では次の議題に移ります。"),
    ]


@pytest.fixture()
def メタ():
    return OutputMeta(
        source_name="会議.mp4",
        source_duration=600.0,
        processed_duration=420.0,
        model_description="large-v3 / GPU",
        vad_engine="silero",
        chatter_method="ルールベース",
        silence_removed=120.0,
        chatter_removed=60.0,
    )


# --- 時刻の書式 -------------------------------------------------------------


@pytest.mark.parametrize(
    "秒,期待",
    [(0, "00:00:00,000"), (1.5, "00:00:01,500"), (61.25, "00:01:01,250"), (3725, "01:02:05,000")],
)
def test_SRTの時刻書式(秒, 期待):
    assert format_timestamp_srt(秒) == 期待


def test_負の時刻はゼロに丸められる():
    assert format_timestamp_srt(-5) == "00:00:00,000"


@pytest.mark.parametrize("秒,期待", [(0, "0:00"), (65, "1:05"), (3725, "1:02:05")])
def test_読みやすい時刻書式(秒, 期待):
    assert format_timestamp_readable(秒) == 期待


# --- SRT --------------------------------------------------------------------


def test_SRTは通し番号と時刻を持つ(セグメント):
    content = render_srt(セグメント)
    assert content.startswith("1\n00:00:00,000 --> 00:00:03,000")
    assert "3\n00:06:40,000 --> 00:06:44,000" in content


def test_SRTの時刻は重ならない():
    segments = [OutputSegment(0, 5, "あ"), OutputSegment(3, 8, "い")]
    content = render_srt(segments)
    assert "00:00:05,000 --> 00:00:08,000" in content


def test_SRTは長さゼロの字幕を作らない():
    content = render_srt([OutputSegment(10, 10, "一瞬")])
    assert "00:00:10,000 --> 00:00:10,200" in content


def test_SRTは長い行を折り返す():
    content = render_srt([OutputSegment(0, 5, "あ" * 60)])
    body = content.split("\n", 2)[2]
    assert "\n" in body.strip()


def test_SRTは3行以上にならない():
    content = render_srt([OutputSegment(0, 5, "あ" * 200)])
    body = content.split("\n", 2)[2].strip()
    assert len(body.splitlines()) == 2


@pytest.mark.parametrize("禁則文字", ["ー", "、", "。", "っ", "」", "）"])
def test_禁則文字は行頭に来ない(禁則文字: str):
    """「3ペー / ジ目」のような読みにくい折り返しを避けること。"""
    from transcribe_ja.writers import _wrap_subtitle

    text = "あ" * 19 + 禁則文字 + "い" * 20
    lines = _wrap_subtitle(text).splitlines()
    assert len(lines) >= 2
    for line in lines[1:]:
        assert line[0] not in "ーぁぃぅぇぉっゃゅょ、。」）"


# --- txt / md ---------------------------------------------------------------


def test_txtは間が空くと段落を分ける(セグメント, メタ):
    content = render_txt(セグメント, メタ)
    assert "本日はお集まり" in content
    # 400 秒離れた発話は別段落になる
    assert "\n\nでは次の議題に移ります。" in content


def test_txtは発話が無いときに案内を出す(メタ):
    assert "見つかりませんでした" in render_txt([], メタ)


def test_mdは時間ごとの見出しを作る(セグメント, メタ):
    content = render_md(セグメント, メタ)
    assert "## 0:00 〜 5:00" in content
    assert "## 5:00 〜 10:00" in content
    assert "**[6:40]**" in content


def test_段落分けは話者が変わると切り替わる():
    segments = [
        OutputSegment(0, 2, "はい。", speaker="話者A"),
        OutputSegment(2, 4, "そうですね。", speaker="話者B"),
    ]
    assert len(group_paragraphs(segments)) == 2


# --- カットログ -------------------------------------------------------------


def test_カットログに元ファイル基準と明記される(メタ):
    content = render_cut_log([CutEntry(10, 60, "無音")], メタ)
    assert "【元ファイル】の時刻" in content
    assert "0:10〜1:00" in content


def test_カットログに削除理由と本文が残る(メタ):
    entries = [CutEntry(120, 180, "雑談（挨拶）", "お疲れ様です。暑いですね。")]
    content = render_cut_log(entries, メタ)
    assert "理由: 雑談（挨拶）" in content
    assert "内容: お疲れ様です。暑いですね。" in content
    # 戻し方の案内があること
    assert "enabled = false" in content


def test_削除が無ければその旨を書く(メタ):
    assert "削除した区間はありません" in render_cut_log([], メタ)


# --- ファイル出力 -----------------------------------------------------------


def test_指定した形式だけ出力される(tmp_path: Path, セグメント, メタ):
    written = write_outputs(tmp_path, "会議", "_ja", ["txt", "srt"], セグメント, [], メタ)
    assert {w.kind for w in written} == {"txt", "srt"}
    assert (tmp_path / "会議_ja.txt").exists()
    assert (tmp_path / "会議_ja.srt").exists()
    assert not (tmp_path / "会議_ja.md").exists()


def test_カットログのファイル名(tmp_path: Path, セグメント, メタ):
    written = write_outputs(tmp_path, "会議", "_ja", ["cut_log"], セグメント, [], メタ)
    assert written[0].path.name == "会議_ja_cut_log.txt"


def test_同名ファイルは上書きせず連番になる(tmp_path: Path, セグメント, メタ):
    (tmp_path / "会議_ja.txt").write_text("既存の内容", encoding="utf-8")
    written = write_outputs(tmp_path, "会議", "_ja", ["txt"], セグメント, [], メタ)
    assert written[0].path.name == "会議_ja(2).txt"
    assert (tmp_path / "会議_ja.txt").read_text(encoding="utf-8") == "既存の内容"


def test_ファイル名に使えない文字は置き換えられる(tmp_path: Path, セグメント, メタ):
    written = write_outputs(tmp_path, "会議:2024/05", "_ja", ["txt"], セグメント, [], メタ)
    assert ":" not in written[0].path.name
    assert written[0].path.exists()
