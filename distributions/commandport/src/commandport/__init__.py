"""commandport: keep a codebase from starting processes outside its adapters.

An AST scan, configured from ``[tool.commandport]`` in the project's ``pyproject.toml``, that fails when code
reaches for ``subprocess`` / ``os.system`` / ... outside the modules allowed to (by default the adapters of
``lifecycle_runner`` and ``proclaunch``). ``python -m commandport.scan`` for a hook or CI,
``commandport.scan.assert_clean()`` for a test.

It used to be the shared home of the command and launch contract. That contract belongs to the libraries that
provide it: ``lifecycle_runner.domain`` / ``.ports`` / ``.testing`` for run, capture and stream, and
``proclaunch.domain`` / ``.ports`` / ``.testing`` for launching. The ``commandport.domain`` / ``.ports`` /
``.testing`` modules were removed; there are no forwarders.

Standard library only; no dependencies; imports none of the libraries it checks.
"""

__version__ = "0.2.0"
