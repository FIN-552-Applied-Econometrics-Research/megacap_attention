"""
Step 0: hello world / environment check.

Confirms that Python and every package in requirements.txt import correctly
and that the repo folders exist. Does NOT need WRDS.

    python src/00_hello_world.py
"""

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PACKAGES = [
    "pandas", "numpy", "statsmodels", "linearmodels", "wrds",
    "requests", "pandas_market_calendars", "pyarrow", "matplotlib",
]
FOLDERS = [
    "src", "notebooks", "data/raw", "data/processed",
    "output/tables", "output/figures", "paper", "slides",
]


def main():
    print(f"Hello from megacap_attention! Python {sys.version.split()[0]}\n")
    ok = True

    print("Packages:")
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
            print(f"  [OK]      {name} {getattr(mod, '__version__', '')}")
        except Exception as e:
            ok = False
            print(f"  [MISSING] {name}  ({e.__class__.__name__})")

    print("\nFolders:")
    for f in FOLDERS:
        exists = (REPO_ROOT / f).is_dir()
        ok &= exists
        print(f"  [{'OK' if exists else 'MISSING':7}] {f}/")

    if ok:
        print("\nAll good. Next: python src/00_check_wrds_access.py --user <wrds_username>")
        return 0
    print("\nSomething is missing. Run: pip install -r requirements.txt")
    return 1


if __name__ == "__main__":
    sys.exit(main())
