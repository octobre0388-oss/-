"""テスト共通の設定。

src レイアウトのままテストできるように、sys.path に src を通す。
また、テスト中に %APPDATA% を汚さないよう TRANSCRIBE_JA_HOME を差し替える。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault(
    "TRANSCRIBE_JA_HOME", tempfile.mkdtemp(prefix="transcribe_ja_test_")
)
