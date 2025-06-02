#!/usr/bin/env python3
import os
import json
import subprocess
from pathlib import Path

def find_project_root(start_path: Path) -> Path:
    """Find the project root by locating package-lock.json upward."""
    current = start_path.resolve()
    while current != current.parent:
        if (current / 'package-lock.json').exists():
            return current
        current = current.parent
    raise FileNotFoundError("No package-lock.json found in any parent directory.")

def extract_gitignore_patterns(gitignore_path: Path) -> set:
    """Extract base names from .gitignore file to ignore in tree."""
    patterns = set()
    if not gitignore_path.exists():
        return patterns

    for line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("./").lstrip("/")
        if line.endswith("/"):
            line = line.rstrip("/")
        basename = os.path.basename(line)
        if basename:
            patterns.add(basename)

    return patterns

def count_files_and_dirs(tree_data):
    """Recursively count files and directories from tree JSON."""
    files = 0
    dirs = 0
    def recurse(node):
        nonlocal files, dirs
        if node["type"] == "directory":
            dirs += 1
            for child in node.get("contents", []):
                recurse(child)
        elif node["type"] == "file":
            files += 1
    recurse(tree_data)
    return files, dirs

def main():
    script_path = Path(__file__).resolve()
    script_folder = script_path.parent
    output_dir = script_folder / "struct_report"
    output_dir.mkdir(exist_ok=True)

    try:
        project_root = find_project_root(script_path)
    except FileNotFoundError as e:
        print(e)
        return

    gitignore_path = project_root / ".gitignore"
    ignore_patterns = extract_gitignore_patterns(gitignore_path)

    # Add default folder ignores (safe to skip)
    default_ignores = {"node_modules", ".git"}
    ignore_patterns.update(default_ignores)

    ignore_arg = "|".join(sorted(ignore_patterns))

    txt_out = output_dir / "project_struct.txt"
    json_out = output_dir / "project_struct.json"

    # --- Generate Text Output ---
    try:
        txt_result = subprocess.run(
            ["tree", "-a", "-I", ignore_arg],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True
        )
        txt_out.write_text(txt_result.stdout, encoding="utf-8")
        print(f"Project structure (.txt) saved to: {txt_out}")
    except FileNotFoundError:
        print("'tree' command not found. Install it with: sudo apt install tree")
        return
    except subprocess.CalledProcessError as e:
        print("Error running tree for text output:", e)
        return

    # --- Generate JSON Output ---
    try:
        json_result = subprocess.run(
            ["tree", "-a", "-I", ignore_arg, "-J"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True
        )
        tree_json = json.loads(json_result.stdout)
        json_out.write_text(json.dumps(tree_json, indent=2), encoding="utf-8")
        print(f"Project structure (.json) saved to: {json_out}")

        total_files, total_dirs = count_files_and_dirs(tree_json[0])
        print(f"Summary: {total_dirs} folders, {total_files} files")

    except subprocess.CalledProcessError as e:
        print("Error running tree for JSON output:", e)
    except json.JSONDecodeError:
        print("Failed to parse JSON from tree command.")

if __name__ == "__main__":
    main()

