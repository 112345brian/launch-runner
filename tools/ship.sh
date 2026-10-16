#!/usr/bin/env bash
# Everything from "the PR is ready" to "it is on PyPI", in one command:
#
#   tools/ship.sh              # wait for CI, merge PR #1, build a clean clone of main, publish, tag, push tags
#   tools/ship.sh --dry-run    # the same gates and builds on a clean clone, but no merge, no upload, no tags
#
# It needs: gh (logged in), git, python3 with venv/pip, network. It asks once for a PyPI API token unless
# TWINE_PASSWORD is already set. It works in a throw-away clone and a throw-away virtualenv, so it does not
# touch any checkout you have. RELEASE_SKIP="ensure-running" leaves a distribution out; SHIP_BRANCH=<branch>
# (with --dry-run) tests the pipeline on a branch instead of main.
set -euo pipefail

REPO="112345brian/launch-runner"
PR="${SHIP_PR:-1}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1
BRANCH="${SHIP_BRANCH:-main}"

die() { echo "ship: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

command -v gh >/dev/null || die "gh is not installed"
command -v git >/dev/null || die "git is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not logged in (run: gh auth login)"

if [[ $DRY -eq 0 ]]; then
    [[ "$BRANCH" == "main" ]] || die "SHIP_BRANCH is only for --dry-run"
    state="$(gh pr view "$PR" --repo "$REPO" --json state -q .state)"
    if [[ "$state" == "OPEN" ]]; then
        step "wait for CI on PR #$PR"
        gh pr checks "$PR" --repo "$REPO" --watch || die "CI is not green on PR #$PR"
        step "merge PR #$PR"
        gh pr merge "$PR" --repo "$REPO" --merge
    elif [[ "$state" == "MERGED" ]]; then
        echo "PR #$PR is already merged"
    else
        die "PR #$PR is $state"
    fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

step "clean clone of $BRANCH"
git clone -q --branch "$BRANCH" "https://github.com/$REPO.git" "$WORK/repo"

step "build tooling (throw-away virtualenv)"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" -q install --disable-pip-version-check build twine pytest psutil setuptools ruff import-linter

cd "$WORK/repo"
export PYTHON="$WORK/venv/bin/python"
export PATH="$WORK/venv/bin:$PATH"
[[ "$BRANCH" == "main" ]] || export RELEASE_ALLOW_ANY_BRANCH=1

if [[ $DRY -eq 1 ]]; then
    step "dry run: gates, builds, twine check (nothing is uploaded or tagged)"
    tools/release.sh
    exit 0
fi

if [[ -z "${TWINE_PASSWORD:-}" ]]; then
    read -r -s -p "PyPI API token (input hidden): " TWINE_PASSWORD
    echo
    export TWINE_PASSWORD
fi
export TWINE_USERNAME="${TWINE_USERNAME:-__token__}"

step "gates, build, upload, tag"
tools/release.sh --upload
echo
echo "shipped."
