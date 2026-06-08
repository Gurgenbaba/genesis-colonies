"""Optimize planet landscape backgrounds — delegates to tools/optimize_images.py (GC-549)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.optimize_images import main  # noqa: E402

if __name__ == "__main__":
    if "--only" not in sys.argv:
        sys.argv[1:1] = ["--only", "landscapes"]
    main()
