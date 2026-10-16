"""Regenerate instructions, or fail read-only when checked-in outputs drift."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from parrhesia.policy import check_generated, generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without changing files")
    args = parser.parse_args()
    try:
        if args.check:
            check_generated(ROOT)
            print("Policy outputs are consistent.")
        else:
            changed = generate(ROOT)
            print(f"Updated {len(changed)} policy files.")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
