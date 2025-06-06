#!/usr/bin/env python3
"""
project_analytics.py

Locate the project root by finding package-lock.json, then:
1. Run two analyses:
       a) Count total folders, files, and lines across all files (ignoring no paths).
       b) Count total folders, files, and lines excluding .gitignored paths (plus .git).
2. For each run, break down file counts and line counts by programming language (based on file extension).
3. Display a progress bar as it processes each filesystem entry.

Writes a single report (containing both “no-ignore” and “with-ignore” sections) to:
<script_directory>/organization_log/project_analytics.txt

Logging:
- INFO: progress and summary (both to console and to
  <project_root>/cache/code_maintenance/organization/logs/project_analytics.log)
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
# Configure Logging (console only for now; file handler added in main)
# ────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("project_analytics")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
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
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".bat": "Batch",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".ini": "INI",
    ".cfg": "Config",
    ".toml": "TOML",
    ".env": "Env",
    ".gitignore": "GitIgnore",
    ".dockerfile": "Dockerfile",
    ".docker": "Dockerfile",
    ".lock": "Lockfile",
    ".csv": "CSV",
    ".tsv": "TSV",
    ".sql": "SQL",
    ".log": "Log",
    ".txt": "TEXT",
    ".md": "README",
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
    If a pattern ends with '/', we:
      (1) strip the trailing slash and add that as a pattern (to ignore the directory itself)
      (2) add pattern+'/**' so that everything under that directory is also ignored.

    We also always add ".git" and ".git/**", so the .git folder is never counted.
    """
    gitignore_path = root / ".gitignore"
    raw_patterns: List[str] = []

    if gitignore_path.exists():
        for raw in gitignore_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                candidate = line.lstrip("#").strip()
                if candidate:
                    raw_patterns.append(candidate)
            else:
                if "#" in raw:
                    candidate = raw.split("#", 1)[0].rstrip()
                else:
                    candidate = raw.rstrip()
                if candidate:
                    raw_patterns.append(candidate)

    # Always ignore the .git folder and its contents, even if not in .gitignore
    raw_patterns.append(".git")
    raw_patterns.append(".git/**")

    # Build a final list that transforms "dirname/" → ["dirname", "dirname/**"]
    final_patterns: List[str] = []
    for pat in raw_patterns:
        if pat.endswith("/"):
            stripped = pat.rstrip("/")
            # ignore the directory itself:
            final_patterns.append(stripped)
            # ignore everything under it:
            final_patterns.append(stripped + "/**")
        else:
            final_patterns.append(pat)

    return PathSpec.from_lines("gitwildmatch", final_patterns)


def collect_non_ignored(root: Path, ignore_spec: PathSpec) -> List[Path]:
    """
    Recursively collect all non-ignored entries under `root`, including `root` itself,
    pruning entire directories whose relative path matches ignore_spec.
    Returns a list of Paths (both files and directories).
    """
    non_ignored: List[Path] = []

    # If the root directory itself is not ignored, include it:
    rel_root = Path(".")  # relative path of root to itself
    if not ignore_spec.match_file(str(rel_root)):
        non_ignored.append(root)

    def recurse(path: Path):
        rel = path.relative_to(root)
        # If this path (file or directory) matches any ignore pattern, skip it and
        # do NOT recurse inside.
        if ignore_spec.match_file(str(rel)):
            return

        non_ignored.append(path)
        if path.is_dir():
            for child in path.iterdir():
                recurse(child)

    for child in root.iterdir():
        recurse(child)

    return non_ignored


def analyze_tree(
    root: Path, ignore_spec: PathSpec
) -> Tuple[int, int, int, Dict[str, Tuple[int, int]]]:
    """
    Recursively walk `root`, pruning ignored subtrees at the highest level,
    to count:
      - total_dirs: number of directories (including the root itself)
      - total_files: number of files
      - total_lines: sum of all lines across files
      - lang_stats: mapping language -> (file_count, line_count)
    Uses collect_non_ignored() to build the list of entries to process.
    Displays a simple progress bar over the number of non-ignored entries.
    """
    non_ignored = collect_non_ignored(root, ignore_spec)
    total_process = len(non_ignored)

    # If there are no files or folders under root (other than the root itself),
    # we still count the root as a directory:
    if total_process == 0:
        return 1, 0, 0, {}

    bar_length = 40
    total_dirs = 0
    total_files = 0
    total_lines = 0
    lang_stats: Dict[str, Tuple[int, int]] = {}

    logger.info("Processing non-ignored entries...")
    next_update = 0.0
    for idx, path in enumerate(non_ignored):
        percent = (idx + 1) / total_process
        if percent >= next_update:
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            # Terminal-only progress update:
            print(
                f"\rProcessing:     [{bar}] {percent * 100:6.1f}%",
                end="",
                flush=True,
            )
            next_update += 0.001  # update roughly every 0.1%

        if path.is_dir():
            total_dirs += 1
        else:
            total_files += 1
            ext = path.suffix.lower()
            language = LANGUAGE_MAP.get(ext, "Other")
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as f:
                    count_lines = sum(1 for _ in f)
            except Exception as e:
                logger.warning(
                    f"\nWarning: Could not read {path.relative_to(root)}: {e}"
                )
                count_lines = 0
            total_lines += count_lines
            prev_files, prev_lines = lang_stats.get(language, (0, 0))
            lang_stats[language] = (prev_files + 1, prev_lines + count_lines)

    # final update at 100%
    bar = "#" * bar_length
    print(f"\rProcessing:     [{bar}] 100.0%", flush=True)

    return total_dirs, total_files, total_lines, lang_stats


def format_section_header(title: str) -> str:
    """
    Return a formatted section header.
    """
    return f"{'=' * 5} {title} {'=' * 5}\n\n"


def format_report_block(
    total_dirs: int,
    total_files: int,
    total_lines: int,
    lang_stats: Dict[str, Tuple[int, int]],
) -> str:
    """
    Build a single report block (without duplication) given the metrics.
    Numbers are formatted with thousand separators.
    Align the “Lines:” label in each language line to a fixed column.
    """
    lines = [
        f"Total directories: {total_dirs:,}",
        f"Total files      : {total_files:,}",
        f"Total lines      : {total_lines:,}",
        "",
        "By language:",
    ]

    # Determine a fixed width for the file-count column to align “Lines:” consistently
    formatted_counts = [f"{fcount:,}" for fcount, _ in lang_stats.values()]
    max_fcount_width = max((len(s) for s in formatted_counts), default=0)

    for lang, (fcount, lcount) in sorted(lang_stats.items()):
        fcount_str = f"{fcount:,}".rjust(max_fcount_width)
        line = f"  {lang:<12} Files: {fcount_str}  Lines: {lcount:,}"
        lines.append(line)

    return "\n".join(lines) + "\n\n"


def main() -> None:
    """
    Main entry point: locate project root, run analyses with and without .gitignore,
    and write combined report to project_analytics.txt. Also configure file logging.
    """
    # 1) Locate project root
    script_dir = Path(__file__).parent.resolve()
    project_root = find_project_root(script_dir)
    logger.info(f"Project root detected: {project_root}")

    # ─────────────────────────────────────────────────────────────────────────────
    # Configure file logging under:
    #    <project_root>/cache/code_maintenance/organization/logs/project_analytics.log
    # ─────────────────────────────────────────────────────────────────────────────
    log_dir = project_root / "cache" / "code_maintenance" / "organization" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "project_analytics.log"

        # If the log file already exists, truncate it to delete previous contents
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")

        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(fh)
        logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        logger.error(f"Could not configure file logging: {e}")
        # Continue without file logging if it fails

    # ─────────────────────────────────────────────────────────────────────────────
    # Phase 1: Analyze without consulting .gitignore
    # ─────────────────────────────────────────────────────────────────────────────
    logger.info("Analyzing project tree (no .gitignore)...")
    empty_spec = PathSpec.from_lines("gitwildmatch", [])
    dirs_no, files_no, lines_no, stats_no = analyze_tree(project_root, empty_spec)
    logger.info(
        f"[No ignore]    {dirs_no:,} dirs, {files_no:,} files, {lines_no:,} lines"
    )

    # ─────────────────────────────────────────────────────────────────────────────
    # Phase 2: Analyze with .gitignore
    # ─────────────────────────────────────────────────────────────────────────────
    logger.info("Analyzing project tree (with .gitignore)...")
    real_ignore_spec = load_ignore_patterns(project_root)
    dirs_wi, files_wi, lines_wi, stats_wi = analyze_tree(project_root, real_ignore_spec)
    logger.info(
        f"[With ignore]  {dirs_wi:,} dirs, {files_wi:,} files, {lines_wi:,} lines"
    )

    # 3) Prepare output directory
    organization_log_dir = script_dir / "organization_log"
    try:
        organization_log_dir.mkdir(exist_ok=True)
    except Exception as e:
        logger.error(f"Could not create organization_log directory: {e}")
        sys.exit(1)

    # 4) Write a single combined report to project_analytics.txt
    output_file = organization_log_dir / "project_analytics.txt"
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
