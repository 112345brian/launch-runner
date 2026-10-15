"""commandport: the check that keeps a codebase from starting processes outside its adapters, and the old home
of the command and launch contract.

The contract itself now belongs to the libraries that provide it:

- ``lifecycle_runner`` -- ``CaptureSpec`` / ``RunSpec`` / ``StreamSpec``, their results with an explicit
  ``RunOutcome``, the ``CommandCapturer`` / ``CommandStreamer`` / ``CommandRunner`` / ``LineStream`` ports and
  ``lifecycle_runner.testing.FakeCommandRunner``;
- ``proclaunch`` -- ``ProcessSpec`` / ``LaunchResult`` / ``LaunchMethod`` / ``EndResult``, the
  ``BackgroundLauncher`` / ``Supervisor`` ports and ``proclaunch.testing.FakeLauncher`` / ``FakeSupervisors``.

``commandport.domain``, ``commandport.ports`` and ``commandport.testing`` still answer to the old names: each
forwards lazily to the provider and returns the provider's own object, so nothing is imported (and nothing is
installed) until a moved name is used, and a missing provider is an ``ImportError`` that names it. A library
that wants its own vocabulary should not import these; it defines a narrow local protocol and lets a provider
satisfy it structurally.

What lives here:

- **The enforcement** (``scan``): an AST scan, configured from ``[tool.commandport]`` in the project's
  ``pyproject.toml``, that fails when code reaches for ``subprocess`` / ``os.system`` / ... outside the
  adapters. ``python -m commandport.scan`` for a hook or CI, ``commandport.scan.assert_clean()`` for a test.

Standard library only; no dependencies.
"""

__version__ = "0.1.1"
