"""conftest.py — shared pytest fixtures.

Makes the project's src/ and the kit's lib/ importable from tests. Mirrors
what an installed package would do; the example avoids `pip install -e .` to
keep the scaffolding minimal.
"""
import sys
from pathlib import Path

# Add project's src/ to path.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Add kit's lib/ to path. The example assumes sdd-kit-2/ is one level up
# from example/.
KIT_LIB = ROOT.parent / "lib"
sys.path.insert(0, str(KIT_LIB))
