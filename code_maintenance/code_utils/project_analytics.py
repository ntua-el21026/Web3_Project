#!/usr/bin/env python3
"""
project_analytics.py

Locate the project root by finding package-lock.json, then:
1. Run two analyses:
   a) Count total folders, files, and lines across all files (ignoring no paths).
   b) Count total folders, files, and lines excluding .gitignored paths.
2. For each run, break down file counts and line counts by programming language (based on file extension).
3. Display a progress bar as it processes each filesystem entry.

Writes a single report (containing both “no-ignore” and “with-ignore” sections) to:
<script_directory>/maintain_log/project_analytics.txt

Logging:
- INFO: progress and summary
- ERROR: fatal errors and exit
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Tuple, List

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: Please install pathspec (`pip install pathspec`).")
    sys.exit(1)

# ────────────────────────────────────────────────────────────────────────────────
# Configure Logging (console only, minimal style)
# ────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("project_analytics")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(ch)

# Map file extensions to language names
LANGUAGE_MAP: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".rs": "Rust",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}


def find_project_root(start: Path) -> Path:
    """
    Walk upward from `start` until a directory contains package-lock.json.
    Returns that directory or exits if not found.
    """
    current = start.resolve()
    while True:
        if (current / "package-lock.json").is_file():
            logger.debug(f"Found project root at {current}")
            return current
        if current == current.parent:
            logger.error("package-lock.json not found; cannot locate project root.")
            sys.exit(1)
        current = current.parent  # type: ignore


def load_ignore_patterns(root: Path) -> PathSpec:
    """
    Read .gitignore under `root`, including commented lines.
    For each non-blank line:
            - If it begins with '#', strip that '#' and any following spaces → pattern.
            - Otherwise, strip inline comments after an unescaped '#'.
    Build a PathSpec with those patterns (gitwildmatch) and return it.
    """
    gitignore_path = root / ".gitignore"
    patterns: List[str] = []
    if not gitignore_path.exists():
        return PathSpec.from_lines("gitwildmatch", patterns)

    for raw in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
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


def analyze_tree(
    root: Path, ignore_spec: PathSpec
) -> Tuple[int, int, int, Dict[str, Tuple[int, int]]]:
    """
    Walk `root` recursively, displaying a progress bar, to count:
    - total_dirs: number of directories
    - total_files: number of files
    - total_lines: sum of all lines across files
    - lang_stats: mapping language -> (file_count, line_count)
    Skips any path matching ignore_spec.
    """
    # Gather all entries first to know total for progress bar
    all_entries: List[Path] = list(root.rglob("*"))
    total_entries = len(all_entries)
    if total_entries == 0:
        return 0, 0, 0, {}

    total_dirs = 0
    total_files = 0
    total_lines = 0
    lang_stats: Dict[str, Tuple[int, int]] = {}

    bar_length = 40
    for idx, path in enumerate(all_entries):
        # Update progress bar
        percent = (idx + 1) / total_entries
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        print(f"\rProcessing: [{bar}] {percent * 100:5.1f}%", end="", flush=True)

        rel = path.relative_to(root)
        if ignore_spec.match_file(str(rel)):
            continue

        if path.is_dir():
            total_dirs += 1
        elif path.is_file():
            total_files += 1
            ext = path.suffix.lower()
            language = LANGUAGE_MAP.get(ext, "Other")
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as f:
                    count = sum(1 for _ in f)
            except Exception as e:
                logger.warning(f"\nWarning: Could not read {rel}: {e}")
                count = 0
            total_lines += count
            files, lines_so_far = lang_stats.get(language, (0, 0))
            lang_stats[language] = (files + 1, lines_so_far + count)

    print()  # Finish progress bar line
    return total_dirs, total_files, total_lines, lang_stats


def format_section_header(title: str) -> str:
    """Return a formatted section header."""
    return f"{'='*5} {title} {'='*5}\n\n"


def format_report_block(
    total_dirs: int,
    total_files: int,
    total_lines: int,
    lang_stats: Dict[str, Tuple[int, int]],
) -> str:
    """
    Build a single report block (without duplication) given the metrics.
    """
    lines = [
        f"Total directories: {total_dirs}",
        f"Total files      : {total_files}",
        f"Total lines      : {total_lines}",
        "",
        "By language:",
    ]
    for lang, (fcount, lcount) in sorted(lang_stats.items()):
        lines.append(f"  {lang:<12} Files: {fcount:<5} Lines: {lcount}")
    return "\n".join(lines) + "\n\n"


def main() -> None:
    # 1) Locate project root
    script_dir = Path(__file__).parent.resolve()
    project_root = find_project_root(script_dir)
    logger.info(f"Project root detected: {project_root}")

    # 2a) Analyze without consulting .gitignore (ignore_spec matches nothing)
    empty_spec = PathSpec.from_lines("gitwildmatch", [])
    logger.info("Analyzing project tree (no .gitignore)...")
    dirs_no, files_no, lines_no, stats_no = analyze_tree(project_root, empty_spec)
    logger.info(f"[No ignore] {dirs_no} dirs, {files_no} files, {lines_no} lines")

    # 2b) Load .gitignore patterns and analyze again
    real_ignore_spec = load_ignore_patterns(project_root)
    logger.info("Analyzing project tree (with .gitignore)...")
    dirs_wi, files_wi, lines_wi, stats_wi = analyze_tree(project_root, real_ignore_spec)
    logger.info(f"[With ignore] {dirs_wi} dirs, {files_wi} files, {lines_wi} lines")

    # 3) Prepare output directory
    maintain_log_dir = script_dir / "maintain_log"
    try:
        maintain_log_dir.mkdir(exist_ok=True)
    except Exception as e:
        logger.error(f"Could not create maintain_log directory: {e}")
        sys.exit(1)

    # 4) Write a single combined report to project_analytics.txt
    output_file = maintain_log_dir / "project_analytics.txt"
    try:
        with output_file.open("w", encoding="utf-8") as out:
            # Section for “no-ignore”
            out.write(format_section_header("ANALYSIS (No .gitignore)"))
            out.write(format_report_block(dirs_no, files_no, lines_no, stats_no))

            # Section for “with-ignore”
            out.write(format_section_header("ANALYSIS (With .gitignore)"))
            out.write(format_report_block(dirs_wi, files_wi, lines_wi, stats_wi))

        logger.info(f"Wrote combined analytics report to: {output_file}")
    except Exception as e:
        logger.error(f"Failed to write combined report to '{output_file}': {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)
