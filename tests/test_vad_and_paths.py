"""無音カットの区間整形と、パス関連のテスト。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from transcribe_ja import paths, wavtools
from transcribe_ja.config import VadConfig
from transcribe_ja.errors import DiskSpaceError
from transcribe_ja.segmap import Interval
from transcribe_ja.vad import detect_speech_intervals, refine_intervals


# --- 発話区間の整形 ---------------------------------------------------------


def test_短い無音は埋められる():
    """文の途中の息継ぎで区切られないこと。"""
    result = refine_intervals(
        [(1.0, 2.0), (2.3, 3.0)], 10, min_silence_ms=700, padding_ms=0, min_speech_ms=0
    )
    assert [(i.start, i.end) for i in result] == [(1.0, 3.0)]


def test_長い無音は残る():
    result = refine_intervals(
        [(1.0, 2.0), (5.0, 6.0)], 10, min_silence_ms=700, padding_ms=0, min_speech_ms=0
    )
    assert len(result) == 2


def test_前後に余白が付く():
    result = refine_intervals(
        [(2.0, 3.0)], 10, min_silence_ms=700, padding_ms=200, min_speech_ms=0
    )
    assert result[0].start == pytest.approx(1.8)
    assert result[0].end == pytest.approx(3.2)


def test_余白は音声の範囲を超えない():
    result = refine_intervals(
        [(0.05, 9.95)], 10, min_silence_ms=700, padding_ms=500, min_speech_ms=0
    )
    assert result[0].start == 0.0
    assert result[0].end == pytest.approx(10.0)


def test_短すぎる発話は捨てられる():
    result = refine_intervals(
        [(1.0, 1.1), (5.0, 7.0)], 10, min_silence_ms=700, padding_ms=0, min_speech_ms=250
    )
    assert [(i.start, i.end) for i in result] == [(5.0, 7.0)]


def test_短い発話は余白で伸びても復活しない():
    """整形の順序（捨ててから余白）が守られていること。"""
    result = refine_intervals(
        [(1.0, 1.1)], 10, min_silence_ms=700, padding_ms=500, min_speech_ms=250
    )
    assert result == []


def test_検出がゼロ件なら空になる():
    assert refine_intervals([], 10) == []


def test_余白で重なった区間は結合される():
    """無音としては残す幅でも、余白を付けて重なったら 1 本にまとめること。"""
    result = refine_intervals(
        [(1.0, 2.0), (2.5, 4.0)], 10, min_silence_ms=100, padding_ms=300, min_speech_ms=0
    )
    assert [(i.start, i.end) for i in result] == [(0.7, 4.3)]


def test_余白が届かなければ区間は分かれたまま():
    result = refine_intervals(
        [(1.0, 2.0), (2.9, 4.0)], 10, min_silence_ms=100, padding_ms=300, min_speech_ms=0
    )
    assert len(result) == 2


# --- 検出全体 ---------------------------------------------------------------


def test_無音と発話が分かれて検出される():
    """このテスト環境には torch が無いので、音量ベースの簡易判定が使われる。"""
    samples = np.concatenate(
        [
            wavtools.make_silence(2.0),
            wavtools.make_tone(3.0),
            wavtools.make_silence(2.0),
            wavtools.make_tone(2.0),
        ]
    )
    intervals, engine = detect_speech_intervals(samples, 16000, VadConfig())
    assert engine
    assert len(intervals) == 2
    assert intervals[0].start == pytest.approx(1.8, abs=0.3)
    assert intervals[1].end == pytest.approx(9.0, abs=0.3)


def test_全部無音なら切らずに全体を残す():
    """発話が検出できなかったときに全部消えてしまわないこと。"""
    samples = wavtools.make_silence(5.0)
    intervals, _ = detect_speech_intervals(samples, 16000, VadConfig())
    assert len(intervals) == 1
    assert intervals[0].start == 0.0
    assert intervals[0].end == pytest.approx(5.0)


def test_長さゼロの音声は空を返す():
    intervals, _ = detect_speech_intervals(np.zeros(0, dtype=np.float32), 16000, VadConfig())
    assert intervals == []


# --- WAV の切り貼り ---------------------------------------------------------


def test_書き出して読み直すと同じ長さになる(tmp_path: Path):
    samples = wavtools.make_tone(1.5)
    path = tmp_path / "a.wav"
    wavtools.write_wav(path, samples)
    back, rate = wavtools.read_wav(path)
    assert rate == 16000
    assert len(back) == len(samples)


def test_カット後の長さがマップと一致する():
    """SegmentMap の計算と実際の音声長がずれないこと。"""
    samples = wavtools.make_tone(10.0)
    segment_map = wavtools.build_map([(1.234, 3.456), (7.0, 9.5)], 10.0)
    cut = wavtools.cut_by_map(samples, segment_map)
    assert wavtools.duration_of(cut) == pytest.approx(segment_map.processed_duration, abs=1e-6)


def test_区間はサンプル境界に丸められる():
    snapped = wavtools.snap_intervals([(0.00003, 1.00003)], 2.0)
    assert snapped[0].start * 16000 == pytest.approx(round(snapped[0].start * 16000))


def test_範囲外の区間は切り詰められる():
    snapped = wavtools.snap_intervals([(-1.0, 99.0)], 5.0)
    assert snapped[0].start == 0.0
    assert snapped[0].end == pytest.approx(5.0)


def test_空のマップでカットすると空になる():
    from transcribe_ja.segmap import SegmentMap

    cut = wavtools.cut_by_map(wavtools.make_tone(1.0), SegmentMap([]))
    assert len(cut) == 0


# --- パス -------------------------------------------------------------------


def test_ファイル名に使えない文字が置き換わる():
    assert paths.sanitize_stem('会議:2024/05?') == "会議_2024_05_"


def test_空になる名前は既定名になる():
    assert paths.sanitize_stem("...") == "output"


def test_連番は既存ファイルを避ける(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a(2).txt").write_text("x", encoding="utf-8")
    assert paths.unique_path(tmp_path, "a", ".txt").name == "a(3).txt"


def test_UNCパスの判定():
    assert paths.is_unc(r"\\server\share\file.mp4") is True
    assert paths.is_unc(r"C:\Users\file.mp4") is False


def test_空き容量が足りなければ日本語エラー(tmp_path: Path):
    with pytest.raises(DiskSpaceError) as excinfo:
        paths.ensure_free_space(tmp_path, 10**18)
    assert "空き容量" in excinfo.value.message


def test_空き容量が足りていれば通る(tmp_path: Path):
    paths.ensure_free_space(tmp_path, 1024)
