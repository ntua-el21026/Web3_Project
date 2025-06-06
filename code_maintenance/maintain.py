#!/usr/bin/env python3
"""
maintain.py

Runs:
1. The update_all.py script in update_env
2. All Python scripts in code_utils (via run_all.py)
3. fix_eof.py in code_utils (again at the end, to fix .txt files generated)

Paths are resolved dynamically under code_maintenance, which itself is discovered
from the project root (the directory containing .gitignore). The script consults
.gitignore to prune ignored paths and maintains a simple cache under cache/
to remember where each target script was last found.

Logs all output only to the terminal. The cache is now located in:
    <project_root>/cache/code_maintenance/maintain_cache.json

Additionally, after run_all.py produces `fix_eof.log` in the cache, this script
renames it to `fix_eof_1.log`. Then after running fix_eof.py again at the end,
it renames the newly generated `fix_eof.log` to `fix_eof_2.log`.
"""

from pathspec import PathSpec
import sys
import subprocess
import logging
import json
from pathlib import Path
from typing import Optional, List

# ──────────────────────────────────────────────────────────────────────────────
# Configure Logging (console only)
# ──────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("maintain")
logger.setLevel(logging.INFO)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(ch)

# ──────────────────────────────────────────────────────────────────────────────
# Progress‐bar setup
# ──────────────────────────────────────────────────────────────────────────────
TOTAL_STEPS = 3
BAR_LENGTH = 40


def print_global_progress(step: int, description: str) -> None:
    """
    Print a simple global progress bar for TOTAL_STEPS.
    `step` is 1-based index of the current step.
    """
    filled = int((step / TOTAL_STEPS) * BAR_LENGTH)
    bar = "#" * filled + " " * (BAR_LENGTH - filled)
    print(
        f"\rOverall Progress: [{bar}] Step {step}/{TOTAL_STEPS} - {description}",
        end="",
        flush=True,
    )
    print()  # move to next line for detailed logs


def section(title: str) -> None:
    """
    Log a section header with minimal formatting.
    """
    logger.info(f"\n[ {title} ]")


def run_python_script(script_path: Path) -> bool:
    """
    Execute a Python script using the current interpreter.
    Returns True on success, False on failure.
    """
    section(f"Running Python script: {script_path.name}")
    try:
        proc = subprocess.run([sys.executable, str(script_path)])
        if proc.returncode != 0:
            logger.error(f"{script_path.name} exited with code {proc.returncode}")
            return False
        return True
    except FileNotFoundError:
        logger.error(f"Python interpreter not found when running {script_path.name}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error while running {script_path.name}: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic cache handling (under <project_root>/cache/code_maintenance)
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent


def find_project_root(start: Path) -> Path:
    """
    Walk upward from `start` until a directory contains .gitignore.
    Returns that directory or exits if not found.
    """
    current = start.resolve()
    while True:
        if (current / ".gitignore").is_file():
            return current
        if current == current.parent:
            logger.error(".gitignore not found; cannot locate project root.")
            sys.exit(1)
        current = current.parent  # type: ignore


def get_cache_paths() -> tuple[Path, Path]:
    """
    Determine CACHE_DIR and CACHE_PATH under:
        <project_root>/cache/code_maintenance/maintain_cache.json
    """
    project_root = find_project_root(SCRIPT_DIR)
    cache_dir = project_root / "cache" / "code_maintenance"
    cache_path = cache_dir / "maintain_cache.json"
    return cache_dir, cache_path


def load_cache() -> dict:
    """
    Load the JSON cache if it exists, else return empty dict.
    The cache file lives under <project_root>/cache/code_maintenance/maintain_cache.json
    """
    cache_dir, cache_path = get_cache_paths()
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(data: dict) -> None:
    """
    Write the cache dict to disk as JSON, ensuring parent folder exists.
    The cache file is under <project_root>/cache/code_maintenance/maintain_cache.json
    """
    cache_dir, cache_path = get_cache_paths()
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write cache: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# .gitignore consultation (prune ignored paths)
# ──────────────────────────────────────────────────────────────────────────────


def load_ignore_spec(root: Path) -> PathSpec:
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


def find_code_maintenance(root: Path) -> Optional[Path]:
    """Recursively find a folder named 'code_maintenance' under the root."""
    return next((p for p in root.rglob("code_maintenance") if p.is_dir()), None)


def find_target_script(
    base: Path, folder_name: str, script_name: str, ignore_spec: PathSpec
) -> Optional[Path]:
    """
    Under `base`, look for a directory named `folder_name`, then within it find
    `script_name`. Prune ignored paths using ignore_spec. Returns the first match.
    """
    candidates = []
    # First, find all subdirs named folder_name, excluding ignored paths
    for path in base.rglob(folder_name):
        rel = path.relative_to(base)
        if ignore_spec.match_file(str(rel)):
            continue
        if path.is_dir():
            # Within that folder, look for script_name, excluding ignored
            for candidate in path.rglob(script_name):
                rel_cand = candidate.relative_to(base)
                if ignore_spec.match_file(str(rel_cand)):
                    continue
                if candidate.is_file():
                    candidates.append(candidate)
    return candidates[0] if candidates else None


def rename_fix_eof_log(project_root: Path, suffix: str) -> None:
    """
    Find any file named `fix_eof.log` under project_root/cache and rename it to fix_eof_{suffix}.log.
    """
    cache_root = project_root / "cache"
    for log_path in cache_root.rglob("fix_eof.log"):
        try:
            new_name = log_path.with_name(f"fix_eof_{suffix}.log")
            log_path.rename(new_name)
            logger.info(f"Renamed {log_path} → {new_name}")
            return
        except Exception as e:
            logger.warning(f"Could not rename {log_path}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
def main():
    # Load cache
    cache = load_cache()

    # Step 1: Locate project root
    project_root = find_project_root(SCRIPT_DIR)
    ignore_spec = load_ignore_spec(project_root)

    code_maint = find_code_maintenance(project_root)
    if not code_maint:
        logger.error("Could not locate 'code_maintenance' under project root.")
        sys.exit(1)

    # Determine paths for run_all.py, update_all.py, and fix_eof.py
    # Keys in cache: "run_all.py", "update_all.py", "fix_eof.py"
    updated_cache = {}

    def locate_or_cache(key: str, folder: str, name: str) -> Optional[Path]:
        # Check cache first
        cached = cache.get(key)
        if cached:
            cached_path = Path(cached)
            if cached_path.is_file():
                updated_cache[key] = str(cached_path)
                return cached_path
        # Otherwise, search under code_maint
        found = find_target_script(code_maint, folder, name, ignore_spec)
        if found:
            updated_cache[key] = str(found)
            return found
        return None

    run_all_path = locate_or_cache("run_all.py", "code_utils", "run_all.py")
    update_all_path = locate_or_cache("update_all.py", "update_env", "update_all.py")
    fix_eof_path = locate_or_cache("fix_eof.py", "code_utils", "fix_eof.py")

    # Save updated cache
    save_cache(updated_cache)

    # Verify existence
    if not run_all_path:
        logger.error("run_all.py not found under code_utils/ within code_maintenance/")
        sys.exit(1)
    if not update_all_path:
        logger.error(
            "update_all.py not found under update_env/ within code_maintenance/"
        )
        sys.exit(1)
    if not fix_eof_path:
        logger.error("fix_eof.py not found under code_utils/ within code_maintenance/")
        sys.exit(1)

    # Step 1: update_all.py
    print_global_progress(1, "update_all.py")
    if not run_python_script(update_all_path):
        logger.error("Aborting: update_all.py failed.")
        sys.exit(1)

    # Step 2: run_all.py
    print_global_progress(2, "run_all.py")
    if not run_python_script(run_all_path):
        logger.error("Aborting: run_all.py failed.")
        sys.exit(1)

    # After run_all.py, rename the produced fix_eof.log to fix_eof_1.log
    rename_fix_eof_log(project_root, "1")

    # Step 3: fix_eof.py (run again at the end)
    print_global_progress(3, "fix_eof.py")
    if not run_python_script(fix_eof_path):
        logger.error("Aborting: fix_eof.py failed.")
        sys.exit(1)

    # After fix_eof.py, rename the newly produced fix_eof.log to fix_eof_2.log
    rename_fix_eof_log(project_root, "2")

    logger.info("\n[ Code and environment maintenance finished successfully ]")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)
