#!/usr/bin/env python3
"""
update_all.py

Run all “update” Python scripts in sequence:
1. update_global.py   (curated global npm tools)
2. update_venv.py     (upgrade pip and virtual‐env packages)
3. update_node.py     (Node.js version, core Node tools)

Must live inside update_env/ and will cd into its own directory.

Logging:
- INFO logs report progress.
- ERROR logs fatal errors and exit.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import List

# ──────────────────────────────────────────────────────────────────────────────
# Configure Logging (console only, minimal style)
# ──────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("run_all_updates")
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
    Log a simple section header.
    """
    logger.info(f"\n[ {title} ]")


def error_exit(message: str) -> None:
    """
    Log an error-level message and exit.
    """
    logger.error(f"ERROR: {message}")
    sys.exit(1)


def run_script(script_path: Path) -> None:
    """
    Execute the given Python script via the same interpreter.
    If execution fails (non-zero exit), abort with error.
    """
    # Predefine `result` so that Pylance knows it always exists.
    result = subprocess.CompletedProcess(args=[str(script_path)], returncode=1)

    try:
        result = subprocess.run([sys.executable, str(script_path)], check=False)
    except FileNotFoundError:
        error_exit(f"Unable to run {script_path.name}: interpreter not found.")

    if result.returncode != 0:
        error_exit(f"Script {script_path.name} exited with code {result.returncode}.")


def main() -> None:
    # ─────────────────────────────────────────────────────────────
    # Ensure we’re in the directory containing this script
    # ─────────────────────────────────────────────────────────────
    script_dir = Path(__file__).parent.resolve()
    try:
        os.chdir(script_dir)
    except Exception as e:
        error_exit(f"Could not change directory to '{script_dir}': {e}")

    # ─────────────────────────────────────────────────────────────
    # 0. Verify presence of required Python update scripts
    # ─────────────────────────────────────────────────────────────
    section("Checking for required update scripts")
    required_scripts: List[str] = [
        "update_global.py",
        "update_venv.py",
        "update_node.py",
    ]
    for name in required_scripts:
        path = script_dir / name
        if not path.is_file():
            error_exit(f"Missing required script: {name}")

    # ─────────────────────────────────────────────────────────────
    # 1. Update or install global npm packages
    # ─────────────────────────────────────────────────────────────
    print_global_progress(1, "Running update_global.py")
    section("Running update_global.py")
    run_script(script_dir / "update_global.py")

    # ─────────────────────────────────────────────────────────────
    # 2. Update Python packages/env (if applicable)
    # ─────────────────────────────────────────────────────────────
    print_global_progress(2, "Running update_venv.py")
    section("Running update_venv.py")
    run_script(script_dir / "update_venv.py")

    # ─────────────────────────────────────────────────────────────
    # 3. Update Node.js version or core Node tools
    # ─────────────────────────────────────────────────────────────
    print_global_progress(3, "Running update_node.py")
    section("Running update_node.py")
    run_script(script_dir / "update_node.py")

    # ─────────────────────────────────────────────────────────────
    # 4. Final message
    # ─────────────────────────────────────────────────────────────
    section("All updates completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_exit(f"Unhandled exception: {e}")
