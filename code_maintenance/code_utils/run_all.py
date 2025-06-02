#!/usr/bin/env python3
"""
run_all.py

Run the following Python scripts in this directory, in a specific order:
1. fix_eof.py
2. fix_indentation.py
3. lint_and_format.py
4. project_analytics.py
5. project_structure.py

Exclude:
- This script itself
- Any script whose filename contains 'comment' (case-insensitive)

A global progress bar is shown as each script is executed.
"""

import runpy
import sys
from pathlib import Path


def main():
    # Locate this script and its containing folder
    current = Path(__file__).resolve()
    folder = current.parent

    # Define the desired execution order
    order = [
        "fix_eof.py",
        "fix_indentation.py",
        "lint_and_format.py",
        "project_analytics.py",
        "project_structure.py",
    ]

    # Filter out files that don't actually exist or contain "comment"
    scripts = [
        name
        for name in order
        if (folder / name).is_file() and "comment" not in name.lower()
    ]

    total = len(scripts)
    if total == 0:
        print("No scripts found to run.")
        sys.exit(0)

    bar_length = 40

    # Initial bar at 0%
    percent = 0
    filled = int(bar_length * percent)
    bar = "#" * filled + " " * (bar_length - filled)
    print(f"Overall Progress: [{bar}] {percent * 100:5.1f}%", end="", flush=True)

    for idx, name in enumerate(scripts):
        # Print running header
        print(f"\n\n=== Running {name} ===")
        script_path = folder / name
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except Exception as e:
            print(f"ERROR in {name}: {e}")

        # Update bar after running
        percent = (idx + 1) / total
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        print(f"\rOverall Progress: [{bar}] {percent * 100:5.1f}%", end="", flush=True)

    print("\n\nAll scripts finished.")


if __name__ == "__main__":
    main()
