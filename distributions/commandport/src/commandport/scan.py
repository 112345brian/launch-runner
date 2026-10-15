"""Self-enforcement: fail when code starts a process by any route other than the process adapters.

Importing ``commandport`` gives a project the contract (``domain``, ``ports``); this module is what makes the
contract hold. It reads a small config, walks the project's Python files, and reports every direct use of a
raw process API (``subprocess.run`` / ``Popen`` / ..., ``os.system`` / ``os.popen`` / ``os.spawn*`` /
``os.exec*``, ``asyncio.create_subprocess_*``) outside the modules the config names as adapters. The usual
cost of such a call on Windows is a console window flashing whenever the caller has no console of its own
(a tracker under ``pythonw``, a scheduled task); the other costs are an unbounded wait, a leaked child and
mojibake from the locale code page. A project that adopts this scan and routes every process through the
ports cannot reintroduce them without a failing check.

Configuration, in the project's ``pyproject.toml``::

    [tool.commandport]
    roots = ["myapp", "tracker", "scripts"]        # directories (or single .py files) to scan
    allow = ["lifecycle_runner.adapters", "proclaunch.adapters"]   # module prefixes that MAY use raw APIs
    baseline = "tests/commandport_baseline.json"   # optional: legacy findings, shrink-only
    exclude_dirs = ["tests", ".venv"]              # optional: directory names never scanned
    fix_hint = "use myapp.procs.run(...)"          # optional: what the failure message tells the developer
    source_roots = ["src"]                         # optional: import roots (a src layout); also scanned

A directory named in ``source_roots`` is both scanned and the root module names are taken relative to, so
``allow = ["myapp.adapters"]`` matches ``src/myapp/adapters/x.py`` in a ``src`` layout (or one ``src`` directory
per distribution in a monorepo). Without it, module names are relative to the project root.

``allow`` defaults to the two reference implementations' adapters (``lifecycle_runner.adapters``,
``proclaunch.adapters``) when the key is omitted; an explicit ``allow = []`` means no module may use a raw
API, and a project with its own adapters lists them.

    [[tool.commandport.exempt]]                    # optional: roots that run only in a developer's terminal
    path = "githooks"
    reason = "git hooks run in the developer's console and must work before the venv exists"

Run it::

    python -m commandport.scan                     # exit 1 and list findings
    python -m commandport.scan --print-baseline    # today's findings as baseline JSON (redirect it to the file)

or assert it from a test with :func:`assert_clean`. Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: Attributes of ``subprocess`` that start a process.
SUBPROCESS_APIS = frozenset({
    "run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput",
})
#: ``os`` functions that start a process (``os.startfile`` opens a document, not a command, and is not one).
OS_APIS = frozenset({
    "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "posix_spawn", "posix_spawnp",
})
ASYNCIO_APIS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})

DEFAULT_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "build", "dist", "site", ".claude",
})
DEFAULT_CONFIG_FILE = "pyproject.toml"
BASELINE_KEY = "findings"

#: The reference implementations' adapter modules: the only places allowed to use a raw process API unless
#: the project's config says otherwise.
DEFAULT_ALLOW = ("lifecycle_runner.adapters", "proclaunch.adapters")

DEFAULT_FIX_HINT = (
    "run it through the command ports instead (lifecycle_runner's CommandCapturer / CommandStreamer / "
    "CommandRunner for a command, proclaunch's BackgroundLauncher for a detached process; or a narrow local "
    "port that one of them satisfies)"
)


class ConfigError(ValueError):
    """The ``[tool.commandport]`` table is missing or malformed."""


@dataclass(frozen=True)
class Exemption:
    path: str
    reason: str


@dataclass(frozen=True)
class ScanConfig:
    root: Path
    roots: tuple[str, ...]
    allow: tuple[str, ...] = ()
    exempt: tuple[Exemption, ...] = ()
    baseline: Path | None = None
    exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS
    fix_hint: str | None = None
    source_roots: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class Finding:
    path: str      # posix path relative to the config root
    line: int
    kind: str      # e.g. "subprocess.run", "from subprocess import Popen", "os.system"
    module: str = field(default="", compare=False)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: raw process call {self.kind}"


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...]          # everything found outside the allowed adapters and exemptions
    new: tuple[Finding, ...]               # findings the baseline does not cover
    stale: tuple[str, ...]                 # baseline entries no longer present (the baseline may only shrink)
    hint: str = DEFAULT_FIX_HINT           # what a failure tells the developer to do instead

    @property
    def ok(self) -> bool:
        return not self.new and not self.stale


# --------------------------------------------------------------------------------------------- configuration
def load_config(root: Path | str | None = None, *, config_file: str = DEFAULT_CONFIG_FILE) -> ScanConfig:
    """Read ``[tool.commandport]`` from *config_file* under *root* (default: the current directory)."""
    base = Path(root) if root is not None else Path.cwd()
    path = base / config_file
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    table = data.get("tool", {}).get("commandport")
    if not isinstance(table, dict):
        raise ConfigError(f"{path} has no [tool.commandport] table")
    return config_from_table(base, table)


def config_from_table(base: Path, table: dict) -> ScanConfig:
    def strings(key: str, *, required: bool = False) -> tuple[str, ...]:
        value = table.get(key, None if required else [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ConfigError(f"[tool.commandport].{key} must be a list of non-empty strings")
        return tuple(value)

    roots = strings("roots", required="source_roots" not in table)
    if not roots and not table.get("source_roots"):
        raise ConfigError("[tool.commandport].roots must name at least one directory")
    exempt: list[Exemption] = []
    for entry in table.get("exempt", []) or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            raise ConfigError("each [[tool.commandport.exempt]] needs a `path`")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError(
                f"[[tool.commandport.exempt]] {entry['path']!r} needs a `reason`: an exemption nobody explains is a hole"
            )
        exempt.append(Exemption(entry["path"].replace("\\", "/").strip("/"), reason.strip()))
    baseline = table.get("baseline")
    if baseline is not None and not isinstance(baseline, str):
        raise ConfigError("[tool.commandport].baseline must be a path string")
    excluded = DEFAULT_EXCLUDE_DIRS | frozenset(strings("exclude_dirs"))
    fix_hint = table.get("fix_hint")
    if fix_hint is not None and (not isinstance(fix_hint, str) or not fix_hint.strip()):
        raise ConfigError("[tool.commandport].fix_hint must be a non-empty string")
    source_roots = tuple(p.replace("\\", "/").strip("/") for p in strings("source_roots"))
    return ScanConfig(
        root=base, roots=tuple(dict.fromkeys((*roots, *source_roots))),
        allow=strings("allow") if "allow" in table else DEFAULT_ALLOW,
        exempt=tuple(exempt), baseline=(base / baseline) if baseline else None, exclude_dirs=excluded,
        fix_hint=fix_hint.strip() if fix_hint else None, source_roots=source_roots,
    )


# --------------------------------------------------------------------------------------------- scanning
def _module_for(rel: str, source_roots: tuple[str, ...]) -> str:
    """The dotted module a root-relative path imports as: relative to the longest source root containing it."""
    best = ""
    for source_root in source_roots:
        if rel.startswith(source_root + "/") and len(source_root) > len(best):
            best = source_root
    return _module_name(rel[len(best) + 1:] if best else rel)


def _module_name(rel: str) -> str:
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _allowed(module: str, allow: tuple[str, ...]) -> bool:
    return any(module == a or module.startswith(a + ".") for a in allow)


def _exempt(rel: str, exempt: tuple[Exemption, ...]) -> bool:
    return any(rel == e.path or rel.startswith(e.path + "/") for e in exempt)


def _findings_in(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, kind) for every raw process API reference in *tree*, through any import alias."""
    subprocess_names: set[str] = set()   # names bound to the subprocess module
    os_names: set[str] = set()           # names bound to os
    asyncio_names: set[str] = set()      # names bound to asyncio
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if alias.name == "subprocess":
                    subprocess_names.add(bound)
                elif alias.name == "os":
                    os_names.add(bound)
                elif alias.name == "asyncio":
                    asyncio_names.add(bound)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            apis = {"subprocess": SUBPROCESS_APIS, "os": OS_APIS, "asyncio": ASYNCIO_APIS}.get(node.module)
            if apis:
                for alias in node.names:
                    if alias.name in apis:
                        found.append((node.lineno, f"from {node.module} import {alias.name}"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner, attr = node.value.id, node.attr
            if owner in subprocess_names and attr in SUBPROCESS_APIS:
                found.append((node.lineno, f"subprocess.{attr}"))
            elif owner in os_names and attr in OS_APIS:
                found.append((node.lineno, f"os.{attr}"))
            elif owner in asyncio_names and attr in ASYNCIO_APIS:
                found.append((node.lineno, f"asyncio.{attr}"))
    return sorted(set(found))


def _python_files(config: ScanConfig) -> list[Path]:
    files: list[Path] = []
    for root_name in config.roots:
        start = config.root / root_name
        if start.is_file() and start.suffix == ".py":
            files.append(start)
            continue
        if not start.is_dir():
            continue
        for path in sorted(start.rglob("*.py")):
            if any(part in config.exclude_dirs for part in path.relative_to(config.root).parts[:-1]):
                continue
            files.append(path)
    return files


def collect(config: ScanConfig) -> tuple[Finding, ...]:
    """Every raw process reference outside the allowed adapters and the exempt roots."""
    out: list[Finding] = []
    for path in _python_files(config):
        rel = path.relative_to(config.root).as_posix()
        module = _module_for(rel, config.source_roots)
        if _allowed(module, config.allow) or _exempt(rel, config.exempt):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue  # not this scan's concern; the project's own syntax/compile checks report it
        out.extend(Finding(rel, line, kind, module) for line, kind in _findings_in(tree))
    return tuple(sorted(out))


def _baseline_counts(config: ScanConfig) -> dict[str, int]:
    if config.baseline is None or not config.baseline.is_file():
        return {}
    data = json.loads(config.baseline.read_text(encoding="utf-8"))
    entries = data.get(BASELINE_KEY, {})
    if not isinstance(entries, dict):
        raise ConfigError(f"{config.baseline}: `{BASELINE_KEY}` must be an object of 'path::kind' -> count")
    return {str(k): int(v) for k, v in entries.items()}


def _counts(findings: tuple[Finding, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        key = f"{f.path}::{f.kind}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def scan(config: ScanConfig) -> ScanReport:
    findings = collect(config)
    allowed = _baseline_counts(config)
    seen = _counts(findings)
    seen_so_far: dict[str, int] = {}
    new: list[Finding] = []
    for f in findings:
        key = f"{f.path}::{f.kind}"
        seen_so_far[key] = seen_so_far.get(key, 0) + 1
        if seen_so_far[key] > allowed.get(key, 0):
            new.append(f)
    stale = tuple(sorted(
        f"{key} (baseline allows {allowed[key]}, found {seen.get(key, 0)})"
        for key in allowed if seen.get(key, 0) < allowed[key]
    ))
    return ScanReport(findings, tuple(new), stale, config.fix_hint or DEFAULT_FIX_HINT)


def baseline_text(config: ScanConfig) -> str:
    """The current findings as baseline JSON. The scan never writes files itself (so the contract package
    stays free of filesystem side effects); redirect this into the configured baseline file."""
    counts = _counts(collect(config))
    return json.dumps({BASELINE_KEY: dict(sorted(counts.items()))}, indent=2) + "\n"


# --------------------------------------------------------------------------------------------- reporting
def format_report(report: ScanReport) -> str:
    lines: list[str] = []
    if report.new:
        lines.append(f"{len(report.new)} raw process call(s) outside the process adapters:")
        lines.extend(f"  {f}" for f in report.new)
        lines.append(f"Fix: {report.hint}.")
    if report.stale:
        lines.append("Baseline entries that are no longer needed (it may only shrink; regenerate with --print-baseline):")
        lines.extend(f"  {s}" for s in report.stale)
    return "\n".join(lines)


def assert_clean(root: Path | str | None = None, *, config_file: str = DEFAULT_CONFIG_FILE) -> ScanReport:
    """For a test: raise ``AssertionError`` listing every violation of the configured contract."""
    report = scan(load_config(root, config_file=config_file))
    assert report.ok, "\n" + format_report(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m commandport.scan", description="Fail on raw process calls.")
    parser.add_argument("--root", default=".", help="project root holding the config file (default: .)")
    parser.add_argument("--config-file", default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--print-baseline", action="store_true", help="print current findings as baseline JSON")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.root, config_file=args.config_file)
        if args.print_baseline:
            print(baseline_text(config), end="")
            return 0
        report = scan(config)
    except ConfigError as exc:
        print(f"commandport: configuration error: {exc}", file=sys.stderr)
        return 2
    if report.ok:
        print(f"commandport: ok ({len(report.findings)} baselined, 0 new)")
        return 0
    print(format_report(report), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
