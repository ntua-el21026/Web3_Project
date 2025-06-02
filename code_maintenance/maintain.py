#!/usr/bin/env python3
"""
maintain.py

Runs:
1. All Python scripts in code_utils (via run_all.py)
2. The update_all.py script in update_env
3. fix_eof.py in code_utils (again at the end, to fix .txt files generated)

Paths are resolved dynamically. Logs all output only to the terminal.
"""

import sys
import subprocess
import logging
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Configure Logging (console only)
# ──────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("maintain")
logger.setLevel(logging.INFO)

# Console handler (stdout) - minimal formatting
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch_formatter = logging.Formatter("%(message)s")
ch.setFormatter(ch_formatter)
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
        result = subprocess.run(
            [sys.executable, str(script_path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.error(f"{script_path.name} exited with code {result.returncode}")
            if result.stderr:
                logger.error(result.stderr.strip())
            return False
        if result.stdout:
            logger.info(result.stdout.strip())
        return True
    except FileNotFoundError:
        logger.error(f"Python interpreter not found when running {script_path.name}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error while running {script_path.name}: {e}")
        return False


def main():
    root_dir = Path(__file__).parent.resolve()
    code_utils = root_dir / "code_utils"
    update_env = root_dir / "update_env"

    run_all_path = code_utils / "run_all.py"
    update_all_path = update_env / "update_all.py"
    fix_eof_path = code_utils / "fix_eof.py"

    # Verify existence of required scripts
    if not run_all_path.is_file():
        logger.error("run_all.py not found under code_utils/")
        sys.exit(1)
    if not update_all_path.is_file():
        logger.error("update_all.py not found under update_env/")
        sys.exit(1)
    if not fix_eof_path.is_file():
        logger.error("fix_eof.py not found under code_utils/")
        sys.exit(1)

    # Step 1: run_all.py
    print_global_progress(1, "run_all.py")
    if not run_python_script(run_all_path):
        logger.error("Aborting: run_all.py failed.")
        sys.exit(1)

    # Step 2: update_all.py
    print_global_progress(2, "update_all.py")
    if not run_python_script(update_all_path):
        logger.error("Aborting: update_all.py failed.")
        sys.exit(1)

    # Step 3: fix_eof.py (run again at the end)
    print_global_progress(3, "fix_eof.py")
    if not run_python_script(fix_eof_path):
        logger.error("Aborting: fix_eof.py failed.")
        sys.exit(1)

    logger.info("\n[ Code and environment maintenance finished successfully ]")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)
