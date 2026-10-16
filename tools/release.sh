#!/usr/bin/env bash
# Build, check and (with --upload) publish every distribution, in dependency order, then tag and push the tags.
#
#   tools/release.sh            # dry run: gates, build, `twine check`; uploads and tags nothing
#   tools/release.sh --upload   # the same, then upload to PyPI, tag <dist>-v<version>, push the tags
#
# Run it from a clean checkout of main that equals origin/main (merge the PR first). Credentials come from
# twine's usual sources (~/.pypirc, or TWINE_USERNAME=__token__ and TWINE_PASSWORD=pypi-...).
# A version already on PyPI is skipped, so the script is safe to re-run after a partial failure.
# Set PYTHON to choose the interpreter (it needs: build, twine, pytest, psutil, setuptools, ruff, import-linter).
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
UPLOAD=0
[[ "${1:-}" == "--upload" ]] && UPLOAD=1

# dependency order: the meta-package pins the others, so it goes last
DISTS=(commandport proclaunch lifecycle-runner ensure-running launch-runner)
# RELEASE_SKIP="ensure-running ..." leaves distributions out of this release
if [[ -n "${RELEASE_SKIP:-}" ]]; then
    KEEP=()
    for dist in "${DISTS[@]}"; do
        [[ " $RELEASE_SKIP " == *" $dist "* ]] || KEEP+=("$dist")
    done
    DISTS=("${KEEP[@]}")
fi

die() { echo "release: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

# the gates import the libraries from the checkout, not from site-packages
SRC=""
for dist in "${DISTS[@]}"; do SRC="$SRC:$PWD/distributions/$dist/src"; done
export PYTHONPATH="${SRC#:}${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

step "preconditions"
if [[ "${RELEASE_ALLOW_ANY_BRANCH:-}" != "1" ]]; then
    [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || die "not on main (merge the PR first)"
    git fetch -q origin
    [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || die "main differs from origin/main"
fi
git diff --quiet && git diff --cached --quiet || die "the working tree is not clean"
[[ -z "$(git ls-files --others --exclude-standard)" ]] || die "there are untracked files"
for module in build twine pytest psutil; do
    "$PYTHON" -c "import $module" 2>/dev/null || die "$PYTHON cannot import $module"
done

step "gates (vendored copies, lint, import contracts, scan, full test suite)"
"$PYTHON" tools/sync_vendored.py --check
"$PYTHON" -m ruff check .
"$PYTHON" -c "import sys; from importlinter.cli import lint_imports_command; sys.argv = ['lint-imports']; lint_imports_command()"
"$PYTHON" -m commandport.scan
"$PYTHON" -m pytest -q -p no:cacheprovider

version_of() {
    "$PYTHON" -c "import tomllib,sys; print(tomllib.load(open('distributions/$1/pyproject.toml','rb'))['project']['version'])"
}
on_pypi() {  # name version -> 0 when that exact version is already published
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "https://pypi.org/pypi/$1/$2/json") || code=000
    [[ "$code" == "200" ]]
}

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

step "build and check"
TO_UPLOAD=()
for dist in "${DISTS[@]}"; do
    version="$(version_of "$dist")"
    if on_pypi "$dist" "$version"; then
        echo "$dist $version: already on PyPI, skipping"
        continue
    fi
    echo "$dist $version: building"
    "$PYTHON" -m build --outdir "$OUT/$dist" "distributions/$dist" >/dev/null
    "$PYTHON" -m twine check "$OUT/$dist"/*
    TO_UPLOAD+=("$dist")
done

if [[ ${#TO_UPLOAD[@]} -eq 0 ]]; then
    echo "nothing to publish"
    exit 0
fi

if [[ $UPLOAD -eq 0 ]]; then
    echo
    echo "dry run: would upload, in this order: ${TO_UPLOAD[*]}"
    echo "re-run with --upload to publish, tag and push the tags"
    exit 0
fi

step "upload"
for dist in "${TO_UPLOAD[@]}"; do
    echo "uploading $dist $(version_of "$dist")"
    "$PYTHON" -m twine upload --non-interactive "$OUT/$dist"/*
done

step "tag"
TAGS=()
for dist in "${TO_UPLOAD[@]}"; do
    tag="$dist-v$(version_of "$dist")"
    git tag -a "$tag" -m "$dist $(version_of "$dist")"
    TAGS+=("$tag")
    echo "tagged $tag"
done
git push origin "${TAGS[@]}"
echo
echo "published: ${TO_UPLOAD[*]}"
