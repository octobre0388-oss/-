"""``python -m transcribe_ja`` の入り口。

右クリックメニューからは pythonw.exe 経由でこのモジュールが呼ばれる。
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
