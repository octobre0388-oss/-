"""faster-whisper による文字起こし（下読みと本番の両方）。

■ 日本語向けの設定について

    language="ja"                      自動判定に任せない（英語と誤判定する事故を防ぐ）
    initial_prompt=句読点付きの例文     句読点の付いた出力を促す
    condition_on_previous_text=False   同じ文を延々と繰り返す暴走を防ぐ
    word_timestamps=True               単語単位の時刻を得る（字幕の精度に効く）
    no_speech_threshold など            無音部分での幻覚を抑える

■ モデルの使い回し

モデルの読み込みには数秒〜数十秒かかる。複数ファイルをまとめて処理するとき、
毎回読み直すと待ち時間が積み上がるので、プロセス内でキャッシュして共有する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .config import WhisperConfig
from .errors import DependencyMissingError, ModelDownloadError, HINT_NETWORK
from .logging_setup import get_logger
from .segmap import Interval

logger = get_logger("transcribe")

#: GPU があるときに "auto" で選ばれるモデル。
AUTO_MODEL_GPU = "large-v3"

#: GPU が無いときに "auto" で選ばれるモデル。
#: large-v3 は CPU では 1 時間の音声に数時間かかることがあるため、
#: 実用性を優先して medium に落とす（config で明示指定すれば large-v3 も使える）。
AUTO_MODEL_CPU = "medium"

#: 読み込み済みモデルのキャッシュ。キーは (モデル名, 装置, 精度, 保存先)。
_MODEL_CACHE: dict[tuple[str, str, str, str], Any] = {}


@dataclass
class Word:
    """単語 1 つ分。時刻はカット後の時間軸（あとで元の時刻に変換する）。"""

    start: float
    end: float
    text: str
    probability: float = 1.0


@dataclass
class TranscriptSegment:
    """発話のかたまり 1 つ分。時刻はカット後の時間軸。"""

    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    speaker: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def char_per_second(self) -> float:
        """発話密度。雑談判定で「中身が薄い区間」を見つけるのに使う。"""
        if self.duration <= 0:
            return 0.0
        return len(self.text.strip()) / self.duration

    def as_interval(self) -> Interval:
        return Interval(self.start, self.end)


# --- 装置とモデルの決定 ---------------------------------------------------------


def cuda_available() -> bool:
    """CUDA が使えるかを調べる。

    faster-whisper の実体である ctranslate2 に直接聞くのが最も確実
    （torch が入っていない構成でも判定できる）。
    """
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_device(configured: str) -> str:
    if configured in ("cuda", "cpu"):
        return configured
    return "cuda" if cuda_available() else "cpu"


def resolve_compute_type(configured: str, device: str) -> str:
    if configured and configured != "auto":
        return configured
    # GPU は float16 が速く精度も十分。CPU は int8 が現実的な速度になる。
    return "float16" if device == "cuda" else "int8"


def resolve_model_size(configured: str, device: str) -> str:
    if configured and configured != "auto":
        return configured
    return AUTO_MODEL_GPU if device == "cuda" else AUTO_MODEL_CPU


def describe_setup(cfg: WhisperConfig) -> str:
    """ログとログ表示用に、実際に使う構成を文字列で返す。"""
    device = resolve_device(cfg.device)
    model = resolve_model_size(cfg.model, device)
    compute = resolve_compute_type(cfg.compute_type, device)
    device_ja = "GPU (CUDA)" if device == "cuda" else "CPU"
    return f"モデル={model} / 装置={device_ja} / 精度={compute}"


# --- モデルの読み込み -----------------------------------------------------------


def load_model(cfg: WhisperConfig, model_size: str | None = None) -> Any:
    """faster-whisper のモデルを読み込む（キャッシュあり）。

    Raises:
        DependencyMissingError: faster-whisper が入っていない場合。
        ModelDownloadError: 初回ダウンロードに失敗した場合。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise DependencyMissingError(
            "文字起こしに必要な faster-whisper がインストールされていません。",
            hint=(
                "install.ps1 をもう一度実行してください。\n"
                "それでも直らない場合は、README の「インストールがうまくいかないとき」を"
                "ご覧ください。"
            ),
        ) from exc

    device = resolve_device(cfg.device)
    compute_type = resolve_compute_type(cfg.compute_type, device)
    size = model_size or resolve_model_size(cfg.model, device)
    model_dir = cfg.model_dir or ""

    key = (size, device, compute_type, model_dir)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    logger.info("モデルを読み込みます: %s (%s, %s)", size, device, compute_type)
    kwargs: dict[str, Any] = {"device": device, "compute_type": compute_type}
    if model_dir:
        kwargs["download_root"] = model_dir

    try:
        model = WhisperModel(size, **kwargs)
    except Exception as exc:
        message = str(exc).lower()
        if device == "cuda" and ("cuda" in message or "cudnn" in message or "cublas" in message):
            # GPU で失敗したら CPU で再挑戦する（ドライバ不足はよくある）。
            logger.warning("GPU での読み込みに失敗したため CPU に切り替えます: %s", exc)
            fallback_compute = resolve_compute_type("auto", "cpu")
            fallback_size = resolve_model_size(cfg.model, "cpu") if cfg.model == "auto" else size
            try:
                model = WhisperModel(
                    fallback_size, device="cpu", compute_type=fallback_compute, **(
                        {"download_root": model_dir} if model_dir else {}
                    )
                )
                key = (fallback_size, "cpu", fallback_compute, model_dir)
            except Exception as inner:
                raise _model_error(inner, fallback_size) from inner
        else:
            raise _model_error(exc, size) from exc

    _MODEL_CACHE[key] = model
    return model


def _model_error(exc: Exception, size: str) -> ModelDownloadError:
    """モデル読み込みの失敗を、原因別の日本語メッセージにする。"""
    message = str(exc)
    lowered = message.lower()

    if any(w in lowered for w in ("connection", "timeout", "network", "resolve", "ssl", "proxy")):
        return ModelDownloadError(
            f"文字起こしモデル（{size}）のダウンロードに失敗しました。\n"
            "インターネットに接続できていない可能性があります。",
            hint=HINT_NETWORK,
        )
    if "no space" in lowered or "disk" in lowered:
        from .errors import HINT_DISK_SPACE

        return ModelDownloadError(
            f"文字起こしモデル（{size}）を保存する空き容量が足りません。\n"
            "large-v3 は約 3GB、medium は約 1.5GB を使います。",
            hint=HINT_DISK_SPACE,
        )
    if "permission" in lowered or "access is denied" in lowered:
        return ModelDownloadError(
            f"文字起こしモデル（{size}）の保存先に書き込めませんでした。",
            hint=(
                "セキュリティソフトがブロックしている可能性があります。\n"
                "config.toml の [whisper] model_dir に、書き込めるフォルダを指定することもできます。"
            ),
        )
    return ModelDownloadError(
        f"文字起こしモデル（{size}）を準備できませんでした。\n（{message.splitlines()[0] if message else ''}）",
        hint=(
            "しばらく待ってからもう一度お試しください。\n"
            "繰り返し失敗する場合は、config.toml の [whisper] model を "
            "small など小さいモデルに変えると解決することがあります。"
        ),
    )


# --- 文字起こし本体 -------------------------------------------------------------


def transcribe_samples(
    samples: np.ndarray,
    cfg: WhisperConfig,
    *,
    language: str = "ja",
    model_size: str | None = None,
    beam_size: int | None = None,
    word_timestamps: bool = True,
    initial_prompt: str | None = None,
    total_duration: float | None = None,
    on_progress: Callable[[float, int], None] | None = None,
) -> list[TranscriptSegment]:
    """音声データを文字起こしして、セグメントの一覧を返す。

    Args:
        samples: float32 の音声データ（16kHz モノラル）。
        cfg: [whisper] セクションの設定。
        language: 言語コード。"ja" を明示指定する。
        model_size: モデルを上書きしたい場合（下読み用に small を使うなど）。
        beam_size: 探索幅の上書き。
        word_timestamps: 単語単位の時刻を取得するか。
        initial_prompt: 上書きする初期プロンプト。
        total_duration: 進捗率の計算に使う長さ。
        on_progress: (0.0〜1.0 の進捗, これまでのセグメント数) を受け取る関数。

    Returns:
        セグメントの一覧。時刻は渡した音声（カット後）の時間軸。
    """
    if samples.size == 0:
        return []

    model = load_model(cfg, model_size=model_size)
    duration = total_duration or (len(samples) / 16000.0)

    options: dict[str, Any] = {
        "language": language,
        "task": "transcribe",
        "beam_size": beam_size or cfg.beam_size,
        "word_timestamps": word_timestamps,
        # 同じ文を無限に繰り返す暴走を防ぐ。日本語では特に起こりやすい。
        "condition_on_previous_text": False,
        # 無音部分で存在しない文章を作り出す「幻覚」を抑える設定。
        "no_speech_threshold": cfg.no_speech_threshold,
        "log_prob_threshold": cfg.log_prob_threshold,
        "compression_ratio_threshold": cfg.compression_ratio_threshold,
        # 品質が悪いときに温度を上げて再試行する（faster-whisper の既定と同じ）。
        "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        # 無音カットは自前で済ませているので、ここでは二重にかけない。
        "vad_filter": False,
    }
    prompt = initial_prompt if initial_prompt is not None else cfg.initial_prompt
    if prompt:
        options["initial_prompt"] = prompt

    logger.info(
        "文字起こしを開始します（%.1f 秒 / beam_size=%s）", duration, options["beam_size"]
    )

    try:
        raw_segments, _info = model.transcribe(samples, **options)
    except Exception as exc:  # pragma: no cover - ライブラリ側の例外
        raise _model_error(exc, model_size or cfg.model) from exc

    results: list[TranscriptSegment] = []
    for raw in raw_segments:
        segment = _convert_segment(raw)
        if segment.text:
            results.append(segment)
        if on_progress is not None and duration > 0:
            on_progress(min(1.0, float(raw.end) / duration), len(results))

    logger.info("文字起こしが終わりました（%d セグメント）", len(results))
    return results


def _convert_segment(raw: Any) -> TranscriptSegment:
    """faster-whisper のセグメントを、本ツールのデータ構造に変換する。"""
    words: list[Word] = []
    for w in getattr(raw, "words", None) or []:
        text = (getattr(w, "word", "") or "").strip()
        if not text:
            continue
        words.append(
            Word(
                start=float(w.start),
                end=float(w.end),
                text=text,
                probability=float(getattr(w, "probability", 1.0) or 1.0),
            )
        )
    return TranscriptSegment(
        start=float(raw.start),
        end=float(raw.end),
        text=(raw.text or "").strip(),
        words=words,
        no_speech_prob=float(getattr(raw, "no_speech_prob", 0.0) or 0.0),
        avg_logprob=float(getattr(raw, "avg_logprob", 0.0) or 0.0),
    )


def clear_model_cache() -> None:
    """読み込み済みモデルを解放する（メモリを空けたいとき用）。"""
    _MODEL_CACHE.clear()
