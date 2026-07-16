#!/usr/bin/env python3
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_str = str(REPO_ROOT)
if repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

from tablea2_parsefilter_repair import run_repair


def main() -> None:
    chart_dir = Path(__file__).resolve().parent
    run_repair(base_dir=chart_dir, output_dir=chart_dir)


if __name__ == "__main__":
    main()
