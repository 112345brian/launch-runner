"""Run a group of local services as one foreground stack: single instance, port-clash check, clean shutdown.

Onion rings (enforced by ``tests/test_stackrun_architecture.py`` and import-linter contracts):

- ``domain``      -- ``Stack``, ``ServiceSpec``, ``Identity``, messages. Pure.
- ``ports``       -- ``typing.Protocol`` ports the core owns.
- ``launcher``    -- the ``Launcher`` use case, against ports only.
- ``declarative`` -- ``stackrun.toml`` -> ``Stack`` (pure).
- ``adapters``    -- the real world (processes, files, sockets, signals); stdlib, plus psutil/proclaunch lazily.
- ``testing``     -- fakes for every port and the conformance kit.
- ``api`` / ``cli`` -- composition roots; the only modules that join the rings.
"""

__version__ = "0.1.0"
