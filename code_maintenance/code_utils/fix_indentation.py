#!/usr/bin/env python3
"""
fix_indentation.py

Scan the project’s .gitignore (including commented lines) to collect ignore patterns.
Then find all code files (extensions configurable below) that are NOT ignored, and
adjust their indentation so that it is an integer multiple of tabs (assuming 4 spaces = 1 tab).

- If a line’s leading whitespace contains tabs and/or spaces, compute its total indent width:
        total_width = num_tabs * TAB_WIDTH + num_spaces
        new_tab_count = ceil(total_width / TAB_WIDTH)
        new_indent = "\t" * new_tab_count
- Lines with no leading whitespace remain unchanged.

This script displays two progress bars:
1. Scanning phase: walks through every filesystem entry under the project root,
        prunes any ignored directories, and collects code files.
2. Fixing phase: iterates over each discovered code file and applies the indentation fix.

At the end, prints how many files were modified.

Usage:
        python fix_indentation.py

Configuration:
        CODE_EXTENSIONS = (".py", ".js", ".ts", ...)  # adjust as needed
        TAB_WIDTH = 4  # number of spaces per tab

Logging:
        INFO output goes both to the terminal and to a shared “logs” folder under
        <project_root>/cache/code_maintenance/code_utils/logs/fix_indentation.log
        Only high-level info (phase start/end, counts, and errors) are logged; progress-bar updates
        remain on the terminal and are NOT written to the log file.
"""

import sys
import logging
from pathlib import Path
import math

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: Please install pathspec (pip install pathspec).")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────────────────

# File extensions to process:
CODE_EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".jsx")
# Number of spaces equating to one tab:
TAB_WIDTH = 4


# ────────────────────────────────────────────────────────────────────────────────
# Helpers to locate project root by finding .gitignore
# ────────────────────────────────────────────────────────────────────────────────


def find_gitignore_root(start: Path) -> Path:
    """
    Walk upward from 'start' until a directory containing .gitignore is found.
    Returns that directory or exits if none found.
    """
    cur = start.resolve()
    while True:
        if (cur / ".gitignore").is_file():
            return cur
        if cur == cur.parent:
            print("ERROR: .gitignore not found; run this inside a project.")
            sys.exit(1)
        cur = cur.parent


def find_project_root() -> Path:
    """
    Walk upward from cwd until a directory containing .gitignore is found.
    Return that directory, or exit if not found.
    """
    cur = Path.cwd().resolve()
    while True:
        if (cur / ".gitignore").is_file():
            return cur
        if cur == cur.parent:
            logging.error("ERROR: .gitignore not found; run this inside a project.")
            sys.exit(1)
        cur = cur.parent


# ────────────────────────────────────────────────────────────────────────────────
# Determine shared log directory under:
#   <project_root>/cache/code_maintenance/code_utils/logs/
# ────────────────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = find_gitignore_root(_SCRIPT_DIR)
_LOG_DIR = _PROJECT_ROOT / "cache" / "code_maintenance" / "code_utils" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_PATH = _LOG_DIR / "fix_indentation.log"


# ────────────────────────────────────────────────────────────────────────────────
# Logging setup: write both to console and to shared log file
# ────────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger("fix_indentation")
logger.setLevel(logging.INFO)

# Console handler (minimal formatting)
console_h = logging.StreamHandler(sys.stdout)
console_h.setLevel(logging.INFO)
console_h.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(console_h)

# File handler (timestamps) writing into shared logs folder
file_h = logging.FileHandler(_LOG_PATH, mode="a", encoding="utf-8")
file_h.setLevel(logging.INFO)
file_h.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
)
logger.addHandler(file_h)


# ────────────────────────────────────────────────────────────────────────────────
# Read .gitignore (including commented lines) and compile PathSpec
# ────────────────────────────────────────────────────────────────────────────────


def load_ignore_patterns(root: Path) -> PathSpec:
    """
    Read .gitignore (including commented lines). For each non-blank line:
            - If it begins with '#', strip that '#' and any following spaces → pattern.
            - Otherwise, strip inline comments after an unescaped '#'.
    For any pattern ending in '/', also add 'pattern/**' so that all children are ignored.
    Finally, ALWAYS ignore '.git' and '.git/**'.
    """
    gitignore_path = root / ".gitignore"
    raw_patterns: list[str] = []
    if gitignore_path.exists():
        for raw in gitignore_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            if not raw.strip():
                continue
            stripped = raw.lstrip()
            if stripped.startswith("#"):
                candidate = stripped[1:].strip()
                if candidate:
                    raw_patterns.append(candidate)
            else:
                if "#" in raw:
                    candidate = raw.split("#", 1)[0].rstrip()
                else:
                    candidate = raw.rstrip()
                candidate = candidate.strip()
                if candidate:
                    raw_patterns.append(candidate)

    # Always ignore the .git folder and its contents, even if not in .gitignore
    raw_patterns.append(".git/")
    raw_patterns.append(".git")

    # Build final list so that "dirname/" → ["dirname", "dirname/**"]
    final_patterns: list[str] = []
    for pat in raw_patterns:
        if pat.endswith("/"):
            base = pat.rstrip("/")
            final_patterns.append(base)
            final_patterns.append(f"{base}/**")
        else:
            final_patterns.append(pat)

    return PathSpec.from_lines("gitwildmatch", final_patterns)


# ────────────────────────────────────────────────────────────────────────────────
# Normalize a single file’s indentation: tabs only, rounding up to nearest tab.
# ────────────────────────────────────────────────────────────────────────────────


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
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )
    except Exception as e:
        logger.error(f"ERROR: Could not read {path}: {e}")
        return False

    modified = False
    new_lines: list[str] = []

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


# ────────────────────────────────────────────────────────────────────────────────
# Main: scan for code files, then fix each one
# ────────────────────────────────────────────────────────────────────────────────


def main() -> None:
    root = find_project_root()
    logger.info(f"INFO: Project root detected at {root}")

    spec = load_ignore_patterns(root)

    # ────────────────────────────────────────────────
    # Phase 1: “Scanning” – prune ignored dirs and collect code files.
    # ────────────────────────────────────────────────

    total_entries = 0
    stack: list[tuple[Path, list[Path]]] = [(root, list(root.iterdir()))]
    while stack:
        parent, children = stack.pop()
        for child in children:
            rel_child = child.relative_to(root)
            if spec.match_file(str(rel_child)):
                continue
            total_entries += 1
            if child.is_dir():
                stack.append((child, list(child.iterdir())))

    code_files: list[Path] = []
    if total_entries == 0:
        logger.info("INFO: No entries found under project root.")
    else:
        logger.info("INFO: Scanning entries (pruning ignored directories)...")
        scanned = 0
        bar_length = 40
        stack = [(root, list(root.iterdir()))]
        while stack:
            parent, children = stack.pop()
            for child in children:
                rel_child = child.relative_to(root)
                if spec.match_file(str(rel_child)):
                    continue

                # Update scanning progress bar in terminal only:
                scanned += 1
                percent = scanned / total_entries
                filled = int(bar_length * percent)
                bar = "#" * filled + " " * (bar_length - filled)
                print(
                    f"\rScanning entries: [{bar}] {percent * 100:5.1f}%",
                    end="",
                    flush=True,
                )

                if child.is_dir():
                    stack.append((child, list(child.iterdir())))
                elif child.is_file() and child.suffix.lower() in CODE_EXTENSIONS:
                    code_files.append(child)

        print()  # Finish scanning progress bar

    logger.info(f"INFO: Found {len(code_files)} code file(s) to check.")

    # ────────────────────────────────────────────────
    # Phase 2: “Fixing” – iterate over each code file and apply indentation fix.
    # ────────────────────────────────────────────────

    fixed_count = 0
    total_files = len(code_files)

    if total_files == 0:
        logger.info("INFO: No code files to process.")
    else:
        logger.info("INFO: Fixing indentation on code files...")
        bar_length = 40
        # Print initial “0%” bar in terminal only
        empty_bar = " " * bar_length
        print(f"\rProcessing files : [{empty_bar}]   0.0%", end="", flush=True)

        for idx, file_path in enumerate(code_files):
            percent = (idx + 1) / total_files
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rProcessing files : [{bar}] {percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            if fix_file_indentation(file_path):
                fixed_count += 1

        print()  # Finish fixing progress bar

        logger.info(f"INFO: {fixed_count} file(s) modified.")


if __name__ == "__main__":
    main()
