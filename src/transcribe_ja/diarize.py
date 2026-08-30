"""話者分離（任意機能・既定オフ）。

pyannote.audio を使って「誰が話しているか」を推定し、各セグメントに
話者ラベル（話者A、話者B …）を付ける。

■ 既定で無効にしている理由

    * pyannote は追加のインストールが必要で、容量も大きい
    * Hugging Face のアカウント登録と、モデル利用規約への同意が必要
    * 会議の書き起こしでは無くても十分に使えることが多い

有効にする手順は README の「話者分離を使う」に書いてある。
未導入のまま有効にした場合は、警告を出して話者なしで処理を続ける
（話者分離のせいで文字起こし全体が失敗しないようにするため）。

■ 時間軸に注意

この関数に渡すセグメントは **元ファイルの時間軸** に変換済みであること。
話者分離は元の音声（抽出直後の WAV）に対して行うため、
カット後の時刻を渡すと話者がずれる。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .config import Config
from .logging_setup import get_logger
from .writers import OutputSegment

logger = get_logger("diarize")

#: 話者ラベルの表示名。
_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _speaker_name(index: int) -> str:
    if index < len(_LABELS):
        return f"話者{_LABELS[index]}"
    return f"話者{index + 1}"


def diarize_audio(wav_path: Path, config: Config) -> list[tuple[float, float, str]] | None:
    """音声全体の話者区間を求める。

    Returns:
        (開始秒, 終了秒, 話者ラベル) の一覧。使えない場合は None。
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        logger.warning(
            "話者分離が有効になっていますが、pyannote.audio が入っていません。"
            "話者なしで続行します。"
        )
        return None

    token = os.environ.get(config.diarization.token_env, "")
    if not token:
        logger.warning(
            "話者分離に必要なトークン（環境変数 %s）が設定されていません。話者なしで続行します。",
            config.diarization.token_env,
        )
        return None

    try:
        pipeline = Pipeline.from_pretrained(config.diarization.model, use_auth_token=token)
        annotation = pipeline(str(wav_path))
    except Exception as exc:
        logger.warning("話者分離に失敗しました（話者なしで続行します）: %s", exc)
        return None

    speakers: dict[str, int] = {}
    result: list[tuple[float, float, str]] = []
    for turn, _, label in annotation.itertracks(yield_label=True):
        if label not in speakers:
            speakers[label] = len(speakers)
        result.append((float(turn.start), float(turn.end), _speaker_name(speakers[label])))

    logger.info("話者分離が完了しました（%d 名を検出）", len(speakers))
    return result


def _speaker_at(turns: Sequence[tuple[float, float, str]], start: float, end: float) -> str:
    """セグメントと最も長く重なっている話者を返す。"""
    best_label = ""
    best_overlap = 0.0
    for turn_start, turn_end, label in turns:
        overlap = min(end, turn_end) - max(start, turn_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    return best_label


def apply_speakers(
    segments: Sequence[OutputSegment], wav_path: Path, config: Config
) -> list[OutputSegment]:
    """各セグメントに話者ラベルを付ける（失敗時は元のまま返す）。

    Args:
        segments: 元ファイルの時間軸に変換済みのセグメント。
        wav_path: 抽出直後の WAV（カット前・元の時間軸）。
        config: 設定。
    """
    turns = diarize_audio(wav_path, config)
    if not turns:
        return list(segments)

    result: list[OutputSegment] = []
    for segment in segments:
        speaker = _speaker_at(turns, segment.start, segment.end)
        result.append(
            OutputSegment(
                start=segment.start, end=segment.end, text=segment.text, speaker=speaker
            )
        )
    return result
