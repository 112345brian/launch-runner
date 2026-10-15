"""Lazy forwarding for names that moved to the library that provides them.

``commandport.domain.RunSpec`` and friends now live in ``lifecycle_runner`` / ``proclaunch``. This keeps the old
import path working without making ``commandport`` import (or depend on) either library: the provider is
imported only when a moved name is first asked for, and the object returned is the provider's own class (same
identity, so ``isinstance`` and pickles agree). A provider that is not installed gives an ``ImportError`` that
names the distribution to install.
"""
from __future__ import annotations

import importlib


def forward(module_globals: dict, moved: dict[str, str], distributions: dict[str, str]) -> None:
    """Install module-level ``__getattr__`` / ``__dir__`` that resolve *moved* (name -> providing module).

    *distributions* maps a providing module's top-level package to the distribution that supplies it."""
    module_name = module_globals["__name__"]

    def __getattr__(name: str):
        target = moved.get(name)
        if target is None:
            raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
        root = target.split(".")[0]
        try:
            module = importlib.import_module(target)
        except ModuleNotFoundError as exc:
            if exc.name == root:
                raise ImportError(
                    f"{module_name}.{name} moved to {target}; install {distributions.get(root, root)!r}"
                ) from exc
            raise
        value = getattr(module, name)
        module_globals[name] = value
        return value

    module_globals["__getattr__"] = __getattr__
    module_globals["__dir__"] = lambda: sorted({*module_globals, *moved})
