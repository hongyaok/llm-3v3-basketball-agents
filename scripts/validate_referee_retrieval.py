"""Run local WS5 Phase B retrieval validation from the repository root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bball3x3.referee.retrieval_validation import main

if __name__ == "__main__":
    raise SystemExit(main())
