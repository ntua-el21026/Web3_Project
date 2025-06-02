#!/usr/bin/env python3
"""
fix_eof.py

Recursively scan a project for “code” files (by extension), skip any paths
that match .gitignore / .eslintignore / .prettierignore—including lines that
start with ‘#’ (optionally with spaces) as ignore patterns—and make sure each
file ends with exactly one newline (no more, no fewer). Files larger than 5 MB
are skipped.

Usage:
	./fix_eof.py [--root /path/to/project] [--dry-run] [--verbose]

By default, we look for package-lock.json upward from this script’s folder to find
the project root. You can override via --root. A small ENV var cache (PROJECT_ROOT_CACHE)
is set for child processes, but note that it does not persist across separate invocations
unless you explicitly export it in your shell.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import List

try:
	from pathspec import PathSpec
except ImportError:
	print("ERROR: You need to install the pathspec module:\n    pip install pathspec")
	sys.exit(1)

# ───────────────────────────────────────────────────────────────────────────────
# === Configuration ===
CODE_EXTENSIONS = {
	".py",
	".ts",
	".tsx",
	".js",
	".jsx",
	".json",
	".html",
	".css",
	".scss",
	".sql",
	".md",
	".sh",
	".yaml",
	".yml",
	".env",
	".xml",
	".sol",
	".go",
	".rs",
	".c",
	".cpp",
	".h",
	".hpp",
	".java",
	".kt",
	".swift",
	".dart",
	".txt",
	".cfg",
	".ini",
}
IGNORE_FILES = [".gitignore", ".eslintignore", ".prettierignore"]
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ENV_VAR = "PROJECT_ROOT_CACHE"

# Pre-compiled regex: strip any number of trailing CRLF/CR/LF at EOF, then add exactly one
RE_EOF = re.compile(r"(?:\r\n|\r|\n)*\Z")
# ───────────────────────────────────────────────────────────────────────────────

# Logging setup (console only, minimal)
LOG_FORMAT = "%(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("fix_eof")


def find_project_root(start_path: Path) -> Path:
	"""
	Walk upward from start_path until we find a package-lock.json file.
	Return the containing directory. Raises FileNotFoundError if none found.
	"""
	current = start_path.resolve()
	while current != current.parent:
		if (current / "package-lock.json").exists():
			return current
		current = current.parent
	raise FileNotFoundError("No package-lock.json found in any parent directory.")


def load_combined_ignore_spec(root: Path) -> PathSpec:
	"""
	Read all ignore files (IGNORE_FILES) under 'root', accumulate patterns:
		- If a line’s first non-whitespace character is '#', treat everything
			after that '#' as a literal ignore pattern.
		- Otherwise, strip inline comments (anything after an unescaped '#') and skip
			blank lines. Build and return a PathSpec for matching.
	"""
	patterns: List[str] = []
	for fname in IGNORE_FILES:
		ignore_path = root / fname
		if not ignore_path.exists():
			continue

		lines = ignore_path.read_text(encoding="utf-8").splitlines()
		for raw_line in lines:
			if not raw_line:
				continue

			stripped = raw_line.lstrip()
			if stripped.startswith("#"):
				# A full-line comment (possibly preserved): take everything after '#'
				pattern = stripped[1:].strip()
				if pattern:
					patterns.append(pattern)
				continue

			# Otherwise strip inline comment
			if "#" in raw_line:
				line = raw_line.split("#", 1)[0].rstrip()
			else:
				line = raw_line.rstrip()

			line = line.strip()
			if not line:
				continue
			patterns.append(line)

	return PathSpec.from_lines("gitwildmatch", patterns)


def is_code_file(path: Path) -> bool:
	"""
	Return True if 'path' has a “code” extension that we care about.
	"""
	return path.suffix.lower() in CODE_EXTENSIONS


def ensure_single_final_newline(file_path: Path) -> bool:
	"""
	Read the entire file. If its size ≤ MAX_FILE_SIZE and it does not already
	end with exactly one newline, rewrite it with exactly one newline at EOF.

	Returns True if the file was fixed, False otherwise.
	"""
	try:
		size = file_path.stat().st_size
	except OSError:
		return False

	if size > MAX_FILE_SIZE:
		return False

	try:
		content = file_path.read_text(encoding="utf-8")
	except (UnicodeDecodeError, OSError):
		return False

	new_content = RE_EOF.sub("\n", content)
	if new_content != content:
		try:
			file_path.write_text(new_content, encoding="utf-8")
		except OSError:
			return False
		return True

	return False


def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments:
		--root PATH    : override project root (skip package-lock.json search)
		--dry-run      : only show which files would be modified
		--verbose      : enable DEBUG logging (very verbose)
	"""
	p = argparse.ArgumentParser(
		description="Ensure each code file ends with exactly one newline (no extras)."
	)
	p.add_argument(
		"--root",
		type=Path,
		default=None,
		help=(
			"Explicit project root. If omitted, we look upward from this script’s folder "
			"for package-lock.json."
		),
	)
	p.add_argument(
		"--dry-run",
		action="store_true",
		help="Show summary without modifying any files.",
	)
	p.add_argument(
		"--verbose",
		action="store_true",
		help="Enable DEBUG logging (for troubleshooting).",
	)
	return p.parse_args()


def main():
	args = parse_args()

	# Configure logging
	if args.verbose:
		logger.setLevel(logging.DEBUG)
	else:
		logger.setLevel(logging.INFO)

	# Determine project root
	script_dir = Path(__file__).resolve().parent
	env_root = os.getenv(ENV_VAR)
	if env_root and Path(env_root).exists():
		project_root = Path(env_root).resolve()
	elif args.root is not None:
		project_root = args.root.resolve()
	else:
		try:
			project_root = find_project_root(script_dir)
			os.environ[ENV_VAR] = str(project_root)
		except FileNotFoundError as e:
			logger.error(f"ERROR: {e}")
			sys.exit(1)

	logger.info(f"[ Project root: {project_root} ]")

	ignore_spec = load_combined_ignore_spec(project_root)

	# ─────────────────────────────────────────────────────────────────────────
	# Phase 1: Scanning all filesystem entries under project_root
	# Show a progress bar while building the list of code files
	# ─────────────────────────────────────────────────────────────────────────
	all_entries: List[Path] = list(project_root.rglob("*"))
	total_entries = len(all_entries)
	code_files: List[Path] = []

	if total_entries == 0:
		logger.info("INFO: No entries found under project root.")
	else:
		bar_length = 40
		for idx, path in enumerate(all_entries):
			percent = (idx + 1) / total_entries
			filled = int(bar_length * percent)
			bar = "#" * filled + " " * (bar_length - filled)
			print(f"\rScanning entries: [{bar}] {percent * 100:5.1f}%", end="", flush=True)

			if not path.is_file():
				continue
			rel = path.relative_to(project_root)
			if ignore_spec.match_file(str(rel)):
				continue
			if is_code_file(path):
				code_files.append(path)

		print()  # Finish scanning progress bar

	logger.info(f"INFO: Found {len(code_files)} code file(s) to check.")

	# ─────────────────────────────────────────────────────────────────────────
	# Phase 2: Fixing each code file
	# Show a progress bar while applying ensure_single_final_newline()
	# ─────────────────────────────────────────────────────────────────────────
	fixed_count = 0
	total_files = len(code_files)

	if total_files == 0:
		logger.info("INFO: No code files to process.")
	else:
		bar_length = 40

		# Print an initial “0%” bar
		empty_bar = " " * bar_length
		print(f"\rProcessing files : [{empty_bar}]   0.0%", end="", flush=True)

		for idx, file_path in enumerate(code_files):
			percent = (idx + 1) / total_files
			filled = int(bar_length * percent)
			bar = "#" * filled + " " * (bar_length - filled)
			print(f"\rProcessing files : [{bar}] {percent * 100:5.1f}%", end="", flush=True)

			if not args.dry_run and ensure_single_final_newline(file_path):
				fixed_count += 1

		print()  # Finish fixing progress bar

		logger.info(f"\n[ Scanned {total_files} files; fixed {fixed_count} files ]")
		if args.dry_run:
			logger.info("[ Dry-run mode: no files were modified ]")


if __name__ == "__main__":
	main()
