import sys
from pathlib import Path

src_path = str(Path(__file__).resolve().parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)
from .test_di_container import TestDIContainer

test_container = TestDIContainer()
