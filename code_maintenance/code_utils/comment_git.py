#!/usr/bin/env python3
"""
comment_git.py

This script toggles comments on lines in the .gitignore file in the current directory.

USAGE:
        ./comment_git.py c   # Comment all non-preserved lines in .gitignore
        ./comment_git.py u   # Uncomment non-preserved commented lines in .gitignore

EXAMPLES:
        # To comment out all non-preserved lines in .gitignore:
        ./comment_git.py c

        # To uncomment previously commented lines (except preserved) in .gitignore:
        ./comment_git.py u

BEHAVIOR:
- Operates only on the `.gitignore` file in the directory where the script is run.
- Lines starting with "# =" are considered *preserved* comments and are never modified.
- In 'comment' mode ('c'), all non-commented, non-empty, non-preserved lines are prepended with "# ".
- In 'uncomment' mode ('u'), all lines that are commented (starting with '# ') but not preserved are restored.
"""

import sys
from pathlib import Path


def should_preserve(line: str) -> bool:
    """Return True if line starts with preserved comment marker '# ='."""
    return line.lstrip().startswith("# =")


def is_commented(line: str) -> bool:
    """Return True if line is a comment (ignores preserved check)."""
    return line.lstrip().startswith("#")


def comment_line(line: str) -> str:
    """Return commented line unless it's already commented or preserved."""
    if should_preserve(line) or is_commented(line) or not line.strip():
        return line
    return "# " + line


def uncomment_line(line: str) -> str:
    """Return uncommented line unless it's preserved."""
    if should_preserve(line):
        return line
    stripped = line.lstrip()
    if stripped.startswith("#"):
        prefix_len = len(line) - len(stripped)
        uncommented = stripped[1:].lstrip()
        return " " * prefix_len + uncommented
    return line


def process_gitignore(mode: str):
    gitignore_path = Path(".gitignore")

    if not gitignore_path.is_file():
        print(f"[ERROR] .gitignore not found in current directory: {Path.cwd()}")
        sys.exit(1)

    try:
        lines = gitignore_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as e:
        print(f"[ERROR] Failed to read .gitignore: {e}")
        sys.exit(1)

    total_lines = len(lines)
    if total_lines == 0:
        print("[INFO] .gitignore is empty. Nothing to do.")
        return

    new_lines = []
    changed = 0
    skipped = 0

    bar_length = 40
    for idx, line in enumerate(lines):
        # Progress bar update
        percent = (idx + 1) / total_lines
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        print(f"\rProcessing lines: [{bar}] {percent * 100:5.1f}%", end="", flush=True)

        original = line
        if mode == "c":
            new_line = comment_line(line)
        else:  # mode == 'u'
            new_line = uncomment_line(line)

        if new_line != original:
            changed += 1
        else:
            skipped += 1

        new_lines.append(new_line)

    # Finish progress bar line
    print()

    try:
        gitignore_path.write_text("".join(new_lines), encoding="utf-8")
    except Exception as e:
        print(f"[ERROR] Failed to write .gitignore: {e}")
        sys.exit(1)

    print(f"[INFO] .gitignore processed: {gitignore_path.resolve()}")
    print(f"[INFO] Lines changed: {changed}")
    print(f"[INFO] Lines skipped: {skipped}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./comment_git.py [c|u]")
        sys.exit(1)

    mode_arg = sys.argv[1].strip().lower()
    if mode_arg not in ("c", "u"):
        print("[ERROR] Invalid mode. Use 'c' to comment or 'u' to uncomment.")
        sys.exit(1)

    process_gitignore(mode_arg)
