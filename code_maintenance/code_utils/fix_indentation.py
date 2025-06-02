#!/usr/bin/env python3
"""
fix_indentation.py

Scan the project’s .gitignore (including commented lines) to collect ignore patterns.
Then find all code files (extensions configurable below) that are NOT ignored, and
adjust their indentation so that it is an integer multiple of tabs (assuming 4 spaces = 1 tab).
- If a line’s leading whitespace contains tabs and/or spaces, compute its total indent width:
        total_width = num_tabs * TAB_WIDTH + num_spaces
        Then:
        new_tab_count = ceil(total_width / TAB_WIDTH)
        leftover_spaces = 0
        new_indent = "\t" * new_tab_count
- Lines with no leading whitespace remain unchanged.

This script displays two progress bars:
        1. Scanning phase: walks through every filesystem entry under the project root,
                filters out ignored paths, and collects code files.
        2. Fixing phase: iterates over each discovered code file and applies the indentation fix.

At the end, prints how many files were modified.

Usage:
        python fix_indentation.py

Configuration:
        CODE_EXTENSIONS = (".py", ".js", ".ts", ...)  # adjust as needed
        TAB_WIDTH = 4  # number of spaces per tab

Logging:
        Minimal INFO output to the terminal.
"""

import sys
import logging
from pathlib import Path

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: Please install pathspec (`pip install pathspec`).")
    sys.exit(1)

# ───────────────────────── Configuration ───────────────────────────
# File extensions to process:
CODE_EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".jsx")
# Number of spaces equating to one tab:
TAB_WIDTH = 4

LOG_FORMAT = "%(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("fix_indentation")
# ───────────────────────────────────────────────────────────────────


def find_project_root() -> Path:
    """
    Walk upward from cwd until a directory containing .gitignore is found.
    Return that directory, or exit if not found.
    """
    cur = Path.cwd()
    while True:
        if (cur / ".gitignore").is_file():
            return cur
        if cur == cur.parent:
            logger.error("ERROR: .gitignore not found; run this inside a project.")
            sys.exit(1)
        cur = cur.parent


def load_ignore_patterns(root: Path) -> PathSpec:
    """
    Read .gitignore (including commented lines). For each non-blank line:
            - If it begins with '#', strip that '#' and any following spaces → pattern.
            - Otherwise, strip inline comments after an unescaped '#'.
    Build a PathSpec with those patterns (gitwildmatch).
    """
    gitignore_path = root / ".gitignore"
    patterns = []
    for raw in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # a commented‐out pattern still counts (e.g. “# build/”)
            candidate = line.lstrip("#").strip()
            if candidate:
                patterns.append(candidate)
        else:
            if "#" in raw:
                candidate = raw.split("#", 1)[0].rstrip()
            else:
                candidate = raw.rstrip()
            if candidate:
                patterns.append(candidate)
    return PathSpec.from_lines("gitwildmatch", patterns)


def fix_file_indentation(path: Path) -> bool:
    """
    For each line in 'path':
            - Count leading tabs and spaces.
            - Compute total_width = num_tabs * TAB_WIDTH + num_spaces.
            - new_tab_count = ceil(total_width / TAB_WIDTH)
            - new_indent = "\t" * new_tab_count
            - Replace the original leading whitespace with new_indent.
    Return True if file was rewritten, False otherwise.
    """
    import math

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )
    except Exception as e:
        logger.error(f"ERROR: Could not read {path}: {e}")
        return False

    modified = False
    new_lines = []

    for line in lines:
        idx = 0
        while idx < len(line) and line[idx] in ("\t", " "):
            idx += 1
        indent = line[:idx]
        rest = line[idx:]
        num_tabs = indent.count("\t")
        num_spaces = indent.count(" ")
        total_width = num_tabs * TAB_WIDTH + num_spaces

        if total_width > 0:
            new_tab_count = math.ceil(total_width / TAB_WIDTH)
        else:
            new_tab_count = 0

        new_indent = "\t" * new_tab_count
        new_line = new_indent + rest
        if new_line != line:
            modified = True
        new_lines.append(new_line)

    if modified:
        try:
            path.write_text("".join(new_lines), encoding="utf-8")
        except Exception as e:
            logger.error(f"ERROR: Could not write {path}: {e}")
            return False

    return modified


def main() -> None:
    root = find_project_root()
    logger.info(f"INFO: Project root detected at {root}")

    spec = load_ignore_patterns(root)

    # ────────────────────────────────────────────────
    # Phase 1: “Scanning” – walk every entry, filter, and build code_files.
    # Show a progress bar over all filesystem entries.
    # ────────────────────────────────────────────────
    all_entries = list(root.rglob("*"))
    total_entries = len(all_entries)
    code_files: list[Path] = []

    if total_entries == 0:
        logger.info("INFO: No entries found under project root.")
    else:
        bar_length = 40
        for idx, path in enumerate(all_entries):
            percent = (idx + 1) / total_entries
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rScanning entries: [{bar}] {
                    percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            # only consider files
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if spec.match_file(str(rel)):
                continue
            if path.suffix.lower() in CODE_EXTENSIONS:
                code_files.append(path)

        print()  # finish scan‐progress bar

    logger.info(f"INFO: Found {len(code_files)} code file(s) to check.")

    # ────────────────────────────────────────────────
    # Phase 2: “Fixing” – iterate over each code file and apply indentation fix.
    # Show a progress bar over code_files.
    # ────────────────────────────────────────────────
    fixed_count = 0
    total_files = len(code_files)

    if total_files == 0:
        logger.info("INFO: No code files to process.")
    else:
        bar_length = 40
        modified_paths: list[Path] = []

        # Print initial “0%” bar
        empty_bar = " " * bar_length
        print(f"\rProcessing files : [{empty_bar}]   0.0%", end="", flush=True)

        for idx, file_path in enumerate(code_files):
            percent = (idx + 1) / total_files
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rProcessing files : [{bar}] {
                    percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            if fix_file_indentation(file_path):
                fixed_count += 1
                modified_paths.append(file_path.relative_to(root))

        print()  # finish fix‐progress bar

        # Immediately log each file that was rewritten
        for rel in modified_paths:
            logger.info(f"FIXED: {rel}")

        logger.info(f"\nINFO: {fixed_count} file(s) modified.")


if __name__ == "__main__":
    main()
