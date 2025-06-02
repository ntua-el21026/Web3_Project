#!/usr/bin/env bash
# Run all update scripts in sequence: global npm tools, Python, Node, Node modules

set -euo pipefail

section() {
	printf "\n==============================\n%s\n==============================\n" "$1"
}

# Move into the directory containing this script (update_env/)
cd "$(dirname "$0")"

# 1. Update or install global npm packages
section "Running update_global.sh"
./update_global.sh

# 2. Update Python packages/env (if applicable)
section "Running update_python.sh"
./update_python.sh

# 3. Update Node.js version or core Node tools
section "Running update_node.sh"
./update_node.sh

# 4. Update project‐level node_modules based on package.json
section "Running update_node_modules.sh"
./update_node_modules.sh

section "All updates completed successfully"

