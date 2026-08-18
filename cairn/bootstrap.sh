#!/usr/bin/env bash
# Creates the Cairn repo on your GitHub and pushes this scaffold.
# Requires the GitHub CLI, authenticated: gh auth login
set -euo pipefail

REPO_NAME="${1:-cairn}"
VISIBILITY="${2:-private}"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install it: https://cli.github.com"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Not authenticated. Run: gh auth login"
  exit 1
fi

git init -b main
git add .
git commit -m "Initial scaffold: project docs, schema plan, Phase 0 handoff"

gh repo create "$REPO_NAME" --"$VISIBILITY" --source=. --remote=origin --push

echo ""
echo "Done. Repo created and pushed."
gh repo view --web
