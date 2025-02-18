#!/bin/bash
set -e

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 'commit message'"
    exit 1
fi

COMMIT_MSG="$1"
SUBMODULE_DIR="autoppia_iwa_module"

# Enter submodule, switch to main, commit & push changes.
cd "$SUBMODULE_DIR" || { echo "Submodule directory not found"; exit 1; }
git checkout main
git add .
git commit -m "$COMMIT_MSG"
git push origin main
cd ..

# Update submodule commit ref in parent, commit & push.
git add "$SUBMODULE_DIR"
git commit -m "Update submodule autoppia_iwa_module to latest commit"
git push
