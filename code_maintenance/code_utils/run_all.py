#!/usr/bin/env python3
"""
run_all.py

Run the following Python scripts in a specific order, searching recursively under `code_maintenance/`
(which itself is discovered from the project root — the directory containing .gitignore):

1. fix_eof.py
2. fix_indentation.py
3. lint_and_format.py
4. project_analytics.py
5. project_structure.py

Exclude:

* This script itself
* Any script whose filename contains 'comment' (case-insensitive)

Uses a JSON cache under:
<project_root>/cache/code_maintenance/code_utils/run_all_cache.json

On subsequent runs, if the cached path still exists and is not ignored, it is reused.
Otherwise, the script is re-searched (skipping any paths matching .gitignore) and the cache is updated.

A global progress bar is shown when scanning (for missing or moved scripts) and when executing.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: pip install pathspec")
    sys.exit(1)

# ────────────────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────────────────

CACHE_FILENAME = "run_all_cache.json"
SCRIPT_ORDER = [
    "fix_eof.py",
    "fix_indentation.py",
    "lint_and_format.py",
    "project_analytics.py",
    "project_structure.py",
]
IGNORE_FILES = [".gitignore"]

# ────────────────────────────────────────────────────────────────────────────────


def print_global_progress(step: int, total: int, bar_length: int = 40) -> None:
    """
    Print a simple global progress bar for `total` steps.
    `step` is the number of completed steps (1-based).
    """
    percent = step / total
    filled = int(bar_length * percent)
    bar = "#" * filled + " " * (bar_length - filled)
    print(f"\rOverall Progress    : [{bar}] {percent * 100:5.1f}%", end="", flush=True)


def section(title: str) -> None:
    """Log a simple section header to stdout."""
    print(f"\n[ {title} ]")


def error_exit(message: str) -> None:
    """Log an error-level message and exit."""
    print(f"[ERROR] {message}")
    sys.exit(1)


def find_project_root(start: Path) -> Optional[Path]:
    """Walk upward from `start` to find the directory containing .gitignore."""
    current = start.resolve()
    while True:
        if (current / ".gitignore").is_file():
            return current
        if current == current.parent:
            return None
        current = current.parent


def load_ignore_spec(root: Path) -> PathSpec:
    """
    Read .gitignore under `root` (including commented lines). For each non-blank line:
    - If it begins with '#', strip that '#' and any following spaces → pattern.
    - Otherwise, strip inline comments after an unescaped '#'.
    For any pattern ending in '/', also add 'pattern/**' so that all children are ignored.
    Always ignore '.git' and '.git/**'.
    """
    gitignore_path = root / ".gitignore"
    raw_patterns: List[str] = []
    if gitignore_path.exists():
        for raw in gitignore_path.read_text("utf-8", errors="ignore").splitlines():
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
                candidate = candidate.strip()
                if candidate:
                    raw_patterns.append(candidate)

    # Always ignore the .git directory and its contents
    raw_patterns.append(".git")
    raw_patterns.append(".git/**")

    final_patterns: List[str] = []
    for pat in raw_patterns:
        if pat.endswith("/"):
            base = pat.rstrip("/")
            final_patterns.append(base)
            final_patterns.append(f"{base}/**")
        else:
            final_patterns.append(pat)

    return PathSpec.from_lines("gitwildmatch", final_patterns)


def find_code_maintenance(root: Path) -> Optional[Path]:
    """Recursively find a folder named 'code_maintenance' under the root."""
    return next((p for p in root.rglob("code_maintenance") if p.is_dir()), None)


def find_script(
    name: str, base: Path, ignore_spec: PathSpec, project_root: Path
) -> Optional[Path]:
    """
    Find a script with exact filename under base (excluding any with 'comment' in the name),
    skipping any path matching ignore_spec. Returns the first match or None.
    """
    for candidate in base.rglob(name):
        if "comment" in candidate.name.lower():
            continue
        rel = candidate.relative_to(project_root)
        if ignore_spec.match_file(str(rel)):
            continue
        if candidate.is_file():
            return candidate
    return None


def load_cache(cache_path: Path) -> Dict[str, str]:
    """Load the JSON cache if it exists, else return empty dict."""
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache_path: Path, data: Dict[str, str]) -> None:
    """Write the cache dict to disk as JSON, ensuring parent folder exists."""
    cache_dir = cache_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARNING] Failed to write cache: {e}")


def main():
    script_dir = Path(__file__).resolve().parent

    # ──────────────────────────────────────────────────────────────────────────
    # 1) Locate project root
    # ──────────────────────────────────────────────────────────────────────────
    proj = find_project_root(script_dir)
    if not proj:
        error_exit(".gitignore not found in any parent directories.")
    assert proj is not None
    project_root: Path = proj  # now type is definitely Path

    # 2) Load ignore patterns from project root
    ignore_spec = load_ignore_spec(project_root)

    # ──────────────────────────────────────────────────────────────────────────
    # 3) Locate code_maintenance/ under project root
    # ──────────────────────────────────────────────────────────────────────────
    cd = find_code_maintenance(project_root)
    if not cd:
        error_exit(f"Could not locate 'code_maintenance' under: {project_root}")
    assert cd is not None
    code_dir: Path = cd
    print(f"[INFO] code_maintenance found at: {code_dir}")

    # ──────────────────────────────────────────────────────────────────────────
    # 4) Derive cache directory under:
    #      <project_root>/cache/code_maintenance/code_utils/
    #    where `code_utils` is the subfolder of code_maintenance containing this script.
    # ──────────────────────────────────────────────────────────────────────────
    code_maint_root: Path = code_dir
    relative_to_code_maint: Path = script_dir.relative_to(
        code_maint_root
    )  # e.g. "code_utils"
    cache_dir = project_root / "cache" / "code_maintenance" / relative_to_code_maint
    cache_path = cache_dir / CACHE_FILENAME
    cache_data: Dict[str, str] = load_cache(cache_path)

    # ──────────────────────────────────────────────────────────────────────────
    # 5) Scan for each script (using cache when possible)
    # ──────────────────────────────────────────────────────────────────────────
    print(f"[INFO] Locating scripts under: {code_dir}")
    total = len(SCRIPT_ORDER)
    bar_length = 40
    script_paths: List[Path] = []
    updated_cache: Dict[str, str] = {}

    for idx, name in enumerate(SCRIPT_ORDER):
        # Progress bar update for scanning
        percent = (idx + 1) / total
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        print(
            f"\rScanning scripts   : [{bar}] {
                percent * 100:5.1f}%",
            end="",
            flush=True,
        )

        # Check cache first
        cached = cache_data.get(name)
        if cached:
            cached_path = Path(cached)
            if cached_path.is_file():
                try:
                    rel_cached = cached_path.relative_to(project_root)
                    if not ignore_spec.match_file(str(rel_cached)):
                        script_paths.append(cached_path)
                        updated_cache[name] = str(cached_path)
                        continue
                except Exception:
                    pass  # fallback to rescan if relative_to fails

        # Otherwise, search afresh
        found = find_script(name, code_dir, ignore_spec, project_root)
        if found:
            script_paths.append(found)
            updated_cache[name] = str(found)
        else:
            print(f"\n[WARNING] Script not found: {name}")

    print()  # finish scanning bar

    # 6) Save updated cache (even if some scripts were missing)
    save_cache(cache_path, updated_cache)

    if not script_paths:
        print("[INFO] No scripts found to run.")
        return

    # ──────────────────────────────────────────────────────────────────────────
    # 7) Execution phase: change cwd so scripts run from code_maintenance root
    # ──────────────────────────────────────────────────────────────────────────
    try:
        os.chdir(code_dir)
    except Exception as e:
        error_exit(f"Could not change directory to '{code_dir}': {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # 8) Define run_script() to execute and rely on child scripts for their own logs
    # ──────────────────────────────────────────────────────────────────────────
    def run_script(script_path: Path) -> None:
        """
        Execute the given Python script via the same interpreter.
        If execution fails, abort with error.
        """
        section(f"Running {script_path.name}")

        try:
            # Let each child script manage its own logging/output
            result = subprocess.run([sys.executable, str(script_path)], check=True)
        except subprocess.CalledProcessError as e:
            error_exit(f"Script {script_path.name} exited with code {e.returncode}.")

    # ──────────────────────────────────────────────────────────────────────────
    # 9) Run each script in order with a progress bar
    # ──────────────────────────────────────────────────────────────────────────
    total = len(script_paths)
    print(f"Overall Progress    : [{' ' * bar_length}]   0.0%", end="", flush=True)

    for idx, path in enumerate(script_paths, start=1):
        run_script(path)
        print_global_progress(idx, total, bar_length)

    print("\n\nAll scripts finished.")


if __name__ == "__main__":
    main()
