import os
import sys
import re
from pathlib import Path

try:
    from pathspec import PathSpec
except ImportError:
    print("You need to install the pathspec module: pip install pathspec")
    sys.exit(1)

# === Configuration ===
CODE_EXTENSIONS = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.html', '.css', '.scss',
    '.sql', '.md', '.sh', '.yaml', '.yml', '.env', '.xml',
    '.sol', '.go', '.rs', '.c', '.cpp', '.h', '.hpp',
    '.java', '.kt', '.swift', '.dart', '.txt', '.cfg', '.ini'
}

IGNORE_FILES = ['.gitignore', '.eslintignore', '.prettierignore']
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ENV_VAR = "PROJECT_ROOT_CACHE"

# === Utilities ===

def find_project_root(start_path: Path) -> Path:
    """Search upward for package.json and return its directory."""
    current = start_path.resolve()
    while current != current.parent:
        if (current / 'package.json').exists():
            return current
        current = current.parent
    raise FileNotFoundError("No package.json found in any parent directory.")

def load_combined_ignore_spec(path: Path) -> PathSpec:
    """Parse all relevant ignore files and return a combined PathSpec."""
    patterns = []
    for fname in IGNORE_FILES:
        ignore_file = path / fname
        if ignore_file.exists():
            with ignore_file.open(encoding="utf-8") as f:
                patterns.extend(f.read().splitlines())
    return PathSpec.from_lines('gitwildmatch', patterns)

def ensure_single_final_newline(file_path: Path):
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE:
            return
        with file_path.open('r+', encoding='utf-8') as f:
            content = f.read()
            new_content = re.sub(r'\n*\Z', '\n', content)
            if content != new_content:
                f.seek(0)
                f.write(new_content)
                f.truncate()
                print(f"Fixed EOF newline in: {file_path}")
    except (UnicodeDecodeError, OSError):
        print(f"Skipping binary or unreadable file: {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def main():
    script_dir = Path(__file__).resolve().parent

    # Cache-aware root detection
    env_root = os.getenv(ENV_VAR)
    if env_root and Path(env_root).exists():
        project_root = Path(env_root)
    else:
        try:
            project_root = find_project_root(script_dir)
            os.environ[ENV_VAR] = str(project_root)  # Note: only for subprocesses
        except FileNotFoundError as e:
            print(e)
            sys.exit(1)

    print(f"Scanning project from: {project_root}\n")

    spec = load_combined_ignore_spec(project_root)

    try:
        for root, _, files in os.walk(project_root):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(project_root)
                if spec.match_file(str(rel_path)):
                    continue
                if file_path.suffix.lower() in CODE_EXTENSIONS:
                    ensure_single_final_newline(file_path)
    except Exception as e:
        print(f"Error while walking directories: {e}")

    print("\nDone checking all code files.")

if __name__ == "__main__":
    main()

