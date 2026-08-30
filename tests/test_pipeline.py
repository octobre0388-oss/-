"""パイプライン全体の結線テスト。

ffmpeg と faster-whisper は重いので差し替え、次の点を検証する:

    * 音声抽出 → 無音カット → 文字起こし → 出力 が最後まで通ること
    * 出力される時刻が「元ファイルの時間軸」になっていること（最重要）
    * 同名ファイルがあるときに上書きせず連番になること
    * 雑談カットを有効にしたときも時刻がずれないこと
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from transcribe_ja import pipeline, wavtools
from transcribe_ja.config import Config
from transcribe_ja.ffmpeg_tools import AudioStream, MediaInfo
from transcribe_ja.segmap import SegmentMap
from transcribe_ja.transcribe import TranscriptSegment
from transcribe_ja.writers import OutputSegment

#: テスト用の音声: 無音 3 秒 → 音 5 秒 → 無音 4 秒 → 音 5 秒（合計 17 秒）
SILENCE_1 = 3.0
SPEECH_1 = 5.0
SILENCE_2 = 4.0
SPEECH_2 = 5.0
TOTAL = SILENCE_1 + SPEECH_1 + SILENCE_2 + SPEECH_2


def _make_audio() -> np.ndarray:
    return np.concatenate(
        [
            wavtools.make_silence(SILENCE_1),
            wavtools.make_tone(SPEECH_1, frequency=220),
            wavtools.make_silence(SILENCE_2),
            wavtools.make_tone(SPEECH_2, frequency=330),
        ]
    )


class FakeFfmpeg:
    """ffmpeg の代わりに、合成した音声を書き出すだけの偽物。"""

    def __init__(self) -> None:
        self.extract_calls: list[dict] = []

    def probe(self, media_path: Path) -> MediaInfo:
        return MediaInfo(
            path=media_path,
            duration=TOTAL,
            audio_streams=[AudioStream(audio_index=0, codec="aac", channels=2)],
            has_video=True,
        )

    def extract_audio(self, media_path, destination, **kwargs):
        self.extract_calls.append({"path": media_path, **kwargs})
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress(1.0)
        wavtools.write_wav(Path(destination), _make_audio())
        return Path(destination)


@pytest.fixture()
def 入力ファイル(tmp_path: Path) -> Path:
    path = tmp_path / "会議 資料.mp4"
    path.write_bytes(b"dummy movie data")
    return path


@pytest.fixture()
def 設定(tmp_path: Path) -> Config:
    config = Config()
    config.chatter.enabled = False
    config.general.keep_temp = False
    config.output.formats = ["txt", "srt", "md", "cut_log"]
    return config


def _fake_transcribe(texts: list[str]):
    """カット後の音声を等分して、指定したテキストを割り当てる偽の文字起こし。"""

    def _inner(samples, cfg, **kwargs):
        duration = len(samples) / 16000.0
        if duration <= 0 or not texts:
            return []
        step = duration / len(texts)
        return [
            TranscriptSegment(start=i * step, end=(i + 1) * step, text=text)
            for i, text in enumerate(texts)
        ]

    return _inner


def _srt_times(content: str) -> list[tuple[str, str]]:
    return re.findall(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", content)


def _to_seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


# --- 基本の流れ -------------------------------------------------------------


def test_最小構成が最後まで通る(monkeypatch, 入力ファイル, 設定):
    monkeypatch.setattr(
        pipeline, "transcribe_samples", _fake_transcribe(["最初の発話です。", "次の発話です。"])
    )
    result = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())

    kinds = {w.kind for w in result.written}
    assert kinds == {"txt", "srt", "md", "cut_log"}
    for written in result.written:
        assert written.path.exists()
        assert written.path.parent == 入力ファイル.parent
        assert written.path.name.startswith("会議 資料_ja")


def test_出力の時刻は元ファイルの時間軸になる(monkeypatch, 入力ファイル, 設定):
    """無音カットで縮んだ時刻がそのまま出ていないことを確認する。"""
    monkeypatch.setattr(
        pipeline, "transcribe_samples", _fake_transcribe(["前半の話です。", "後半の話です。"])
    )
    result = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())

    srt = next(w.path for w in result.written if w.kind == "srt")
    times = _srt_times(srt.read_text(encoding="utf-8"))
    assert len(times) == 2

    starts = [_to_seconds(t[0]) for t in times]
    ends = [_to_seconds(t[1]) for t in times]

    # 冒頭 3 秒は無音なので、最初の発話が 0 秒から始まることはありえない
    assert starts[0] > 1.0
    # 後半の発話は、2 つ目の音（12 秒以降）の付近から始まるはず。
    # 無音を切ったあとの時間軸（約 5 秒）のままなら、この判定に引っかかる。
    assert starts[1] > 8.0
    # 元ファイルの長さを超えないこと
    assert ends[-1] <= TOTAL + 0.5
    # 時刻が前後しないこと
    assert starts == sorted(starts)


def test_カットログに削除区間と元時刻が残る(monkeypatch, 入力ファイル, 設定):
    monkeypatch.setattr(pipeline, "transcribe_samples", _fake_transcribe(["本編です。"]))
    result = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())

    cut_log = next(w.path for w in result.written if w.kind == "cut_log")
    content = cut_log.read_text(encoding="utf-8-sig")
    assert "元ファイル" in content
    assert "無音" in content
    # 削除量が記録されていること
    assert re.search(r"無音カット\s*:", content)


def test_同名ファイルがあれば連番になる(monkeypatch, 入力ファイル, 設定):
    monkeypatch.setattr(pipeline, "transcribe_samples", _fake_transcribe(["こんにちは。"]))
    設定.output.formats = ["txt"]

    first = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())
    second = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())

    assert first.written[0].path.name == "会議 資料_ja.txt"
    assert second.written[0].path.name == "会議 資料_ja(2).txt"
    # 1 回目の内容が失われていないこと
    assert first.written[0].path.exists()


def test_音声トラックが無ければ日本語エラー(monkeypatch, 入力ファイル, 設定):
    from transcribe_ja.errors import NoAudioTrackError

    class 音声なし(FakeFfmpeg):
        def probe(self, media_path):
            return MediaInfo(path=media_path, duration=TOTAL, audio_streams=[])

    with pytest.raises(NoAudioTrackError) as excinfo:
        pipeline.process_file(入力ファイル, 設定, ffmpeg=音声なし())
    assert "音声" in excinfo.value.user_message()


def test_対応していない拡張子は日本語エラー(tmp_path, 設定):
    from transcribe_ja.errors import UnsupportedFileError

    path = tmp_path / "資料.pdf"
    path.write_bytes(b"x")
    with pytest.raises(UnsupportedFileError) as excinfo:
        pipeline.process_file(path, 設定, ffmpeg=FakeFfmpeg())
    assert ".pdf" in excinfo.value.message


def test_存在しないファイルは日本語エラー(tmp_path, 設定):
    from transcribe_ja.errors import InputFileNotFoundError

    with pytest.raises(InputFileNotFoundError):
        pipeline.process_file(tmp_path / "ない.mp3", 設定, ffmpeg=FakeFfmpeg())


def test_一時ファイルは処理後に消える(monkeypatch, 入力ファイル, 設定):
    from transcribe_ja.paths import work_root

    monkeypatch.setattr(pipeline, "transcribe_samples", _fake_transcribe(["テスト。"]))
    pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())
    assert not list(work_root().glob("job_*"))


def test_デバッグ設定なら一時ファイルが残る(monkeypatch, 入力ファイル, 設定):
    from transcribe_ja.paths import work_root

    monkeypatch.setattr(pipeline, "transcribe_samples", _fake_transcribe(["テスト。"]))
    設定.general.keep_temp = True
    try:
        pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())
        assert list(work_root().glob("job_*"))
    finally:
        import shutil

        for leftover in work_root().glob("job_*"):
            shutil.rmtree(leftover, ignore_errors=True)


# --- 雑談カットを含む流れ ---------------------------------------------------


def test_雑談カットを有効にしても時刻がずれない(monkeypatch, 入力ファイル, 設定):
    """2 段階カットの合成が正しく効いているかを確認する。"""
    from transcribe_ja import chatter

    設定.chatter.enabled = True
    設定.chatter.max_cut_ratio = 0.9

    # 下読みでは前半を「機材確認」、後半を「本編」として返す
    def _fake_prescan(samples, cfg, **kwargs):
        duration = len(samples) / 16000.0
        half = duration / 2
        return [
            TranscriptSegment(0.0, half, "お疲れ様です。聞こえてますか、マイク大丈夫ですか。"),
            TranscriptSegment(half, duration, "では議題です。資料の3ページ目をご覧ください。"),
        ]

    monkeypatch.setattr(chatter, "transcribe_samples", _fake_prescan)
    monkeypatch.setattr(
        pipeline, "transcribe_samples", _fake_transcribe(["では議題です。資料の3ページ目です。"])
    )

    result = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())

    srt = next(w.path for w in result.written if w.kind == "srt")
    times = _srt_times(srt.read_text(encoding="utf-8"))
    assert times, "字幕が 1 件も出力されていない"
    start = _to_seconds(times[0][0])
    end = _to_seconds(times[-1][1])

    # 前半（元の 3〜8 秒あたり）が切られているので、
    # 残った本編は元ファイルの後半（8 秒以降）に対応するはず
    assert start > 6.0
    assert end <= TOTAL + 0.5

    cut_log = next(w.path for w in result.written if w.kind == "cut_log")
    content = cut_log.read_text(encoding="utf-8-sig")
    assert "機材" in content or "雑談" in content
    assert "マイク大丈夫" in content, "カットした本文が記録されていない"


def test_雑談カットの上限を超えると削除が減る(monkeypatch, 入力ファイル, 設定):
    from transcribe_ja import chatter

    設定.chatter.enabled = True
    設定.chatter.max_cut_ratio = 0.0  # 一切切らせない

    def _fake_prescan(samples, cfg, **kwargs):
        duration = len(samples) / 16000.0
        return [TranscriptSegment(0.0, duration, "お疲れ様です。聞こえてますか。")]

    monkeypatch.setattr(chatter, "transcribe_samples", _fake_prescan)
    monkeypatch.setattr(pipeline, "transcribe_samples", _fake_transcribe(["本編です。"]))

    result = pipeline.process_file(入力ファイル, 設定, ffmpeg=FakeFfmpeg())
    assert result.meta is not None
    assert result.meta.chatter_removed == pytest.approx(0.0)


# --- 時刻変換の単体 ---------------------------------------------------------


def test_to_output_segments_は元の時刻に変換する():
    total_map = SegmentMap([(10, 20), (40, 50)], source_duration=60)
    segments = [
        TranscriptSegment(0.0, 5.0, "前半"),
        TranscriptSegment(12.0, 18.0, "後半"),
    ]
    result = pipeline.to_output_segments(segments, total_map)

    assert [(round(s.start, 2), round(s.end, 2)) for s in result] == [
        (10.0, 15.0),
        (42.0, 48.0),
    ]


def test_to_output_segments_は空マップで空を返す():
    assert pipeline.to_output_segments([TranscriptSegment(0, 1, "x")], SegmentMap([])) == []


def test_build_cut_entries_は時刻順に並べる():
    silence = SegmentMap([(5, 10)], source_duration=20)
    from transcribe_ja.writers import CutEntry

    entries = pipeline.build_cut_entries(
        silence, [CutEntry(start=2.0, end=3.0, reason="雑談", text="あ")]
    )
    assert [round(e.start, 1) for e in entries] == [0.0, 2.0, 10.0]
