#!/usr/bin/env bash
# Pull the latest stevejcl/astro_dwarf_session into this fork.
#
#   tools/sync-upstream.sh          merge upstream into the smartscope branch
#   tools/sync-upstream.sh --deps   ...and also refresh dwarf_python_api
#   tools/sync-upstream.sh --push   ...and push smartscope + the mirror branch to origin
#
# Branch model:
#   NiceGui_V3_multi  pure mirror of upstream - never commit to it
#   smartscope        upstream + our additions (smartscopes/ package + 2 hooks)
set -euo pipefail

UPSTREAM_URL="https://github.com/stevejcl/astro_dwarf_session.git"
UPSTREAM_BRANCH="NiceGui_V3_multi"
WORK_BRANCH="smartscope"

cd "$(git rev-parse --show-toplevel)"

deps=false push=false
for arg in "$@"; do
  case "$arg" in
    --deps) deps=true ;;
    --push) push=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git config rerere.enabled true      # replay conflict resolutions we already made once
git config rerere.autoupdate true

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Working tree has uncommitted changes - commit or stash them first." >&2
  exit 1
fi

git fetch upstream
git switch "$WORK_BRANCH"

new=$(git rev-list --count "HEAD..upstream/$UPSTREAM_BRANCH")
if [[ "$new" == 0 ]]; then
  echo "Already up to date with upstream/$UPSTREAM_BRANCH."
else
  echo "Merging $new new upstream commit(s):"
  git log --oneline --no-decorate "HEAD..upstream/$UPSTREAM_BRANCH" | head -20
  if ! git merge --no-edit "upstream/$UPSTREAM_BRANCH"; then
    echo
    echo "Merge conflict. Our code only touches upstream files at lines marked"
    echo "'smartscopes hook' (astro_dwarf_ui.py, pages/dashboard.py):"
    git diff --name-only --diff-filter=U
    echo "Resolve, 'git add' the files, then 'git merge --continue'."
    echo "git rerere will remember the resolution for next time."
    exit 1
  fi
fi

if $deps; then
  python -m pip install --upgrade -r requirements-local.txt --target . --no-deps
fi

if [[ -x venv/bin/python ]]; then PY=venv/bin/python; else PY=python; fi
"$PY" -m pytest smartscopes/tests -q

if $push; then
  git push origin "upstream/$UPSTREAM_BRANCH:refs/heads/$UPSTREAM_BRANCH"
  git push origin "$WORK_BRANCH"
fi
