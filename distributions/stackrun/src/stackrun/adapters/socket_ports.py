"""``Ports`` on loopback sockets, with the OS's own tools to name the holder."""

from __future__ import annotations

import os
import socket
import subprocess

__all__ = ["SocketPorts"]


class SocketPorts:
    """Is something listening? Tries IPv4 and IPv6 loopback, since dev servers bind either."""

    def in_use(self, port: int) -> bool:
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.5)
                    if probe.connect_ex((host, port)) == 0:
                        return True
            except OSError:
                continue  # this address family is not available here
        return False

    def owner(self, port: int) -> str | None:
        """"name (pid N)" for the listener on ``port``: PowerShell on Windows, ``lsof`` elsewhere (macOS and
        Linux: reasoned, not run on this author's machine). None when it cannot be found."""
        port = int(port)  # it is interpolated into a command line below
        if os.name == "nt":
            query = (
                f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue"
                " | Select-Object -First 1; if ($c) { $p = Get-Process -Id $c.OwningProcess"
                ' -ErrorAction SilentlyContinue; "$($p.ProcessName) (pid $($c.OwningProcess))" }'
            )
            argv = ["powershell", "-NoProfile", "-Command", query]
        else:
            argv = ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if os.name == "nt":
            return done.stdout.strip() or None
        fields = {line[0]: line[1:] for line in done.stdout.splitlines() if line}
        return f"{fields['c']} (pid {fields['p']})" if "p" in fields and "c" in fields else None
