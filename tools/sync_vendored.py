"""Copy the shared sources in ``vendored/`` into the distributions that vendor them.

    python tools/sync_vendored.py          # write the copies
    python tools/sync_vendored.py --check  # exit 1 if any copy differs from its source (CI, tests)

A distribution must build from its own directory (an sdist cannot reach outside it), so each carries a checked-in
copy under ``<package>/_vendor/``. The copies are generated: edit ``vendored/<module>.py`` and re-run this.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "vendored"

#: module in vendored/ -> the package directories (relative to the repo root) that carry a copy
TARGETS = {
    "proctree.py": (
        "distributions/lifecycle-runner/src/lifecycle_runner/_vendor",
        "distributions/proclaunch/src/proclaunch/_vendor",
    ),
}

HEADER = (
    "# VENDORED COPY -- generated from vendored/{name} by tools/sync_vendored.py.\n"
    "# Do not edit here: change the source and re-run the tool (tests/test_vendored.py fails on drift).\n"
)
INIT = '"""Private, vendored helpers (see tools/sync_vendored.py). Not part of the public API."""\n'


def expected() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for name, directories in TARGETS.items():
        body = (SOURCE / name).read_text(encoding="utf-8")
        for directory in directories:
            files[ROOT / directory / name] = HEADER.format(name=name) + body
            files[ROOT / directory / "__init__.py"] = INIT
    return files


def main(argv: list[str]) -> int:
    check = "--check" in argv
    drift = []
    for path, text in expected().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        drift.append(path.relative_to(ROOT).as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if drift and check:
        print("vendored copies differ from vendored/: run python tools/sync_vendored.py\n  " + "\n  ".join(drift))
        return 1
    if drift:
        print("updated:\n  " + "\n  ".join(drift))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
