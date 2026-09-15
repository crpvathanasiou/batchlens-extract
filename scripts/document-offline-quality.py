"""Run tests with IP networking forbidden and sandbox proxy settings isolated.

Optional verification helper for environments injecting proxy schemes unsupported
by the unchanged baseline HTTPX version. This does not change application/network
configuration outside this test process. Normal development uses scripts/quality.ps1.
"""

import os
import socket
import sys
from typing import Any

_original_connect = socket.socket.connect


def offline_connect(connection: socket.socket, address: Any) -> None:
    if connection.family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError("IP networking is forbidden during offline verification")
    _original_connect(connection, address)


def main() -> None:
    import pytest

    # Pytest fakes/Stubber must never contact a live provider. Unix-domain IPC remains
    # available for the explicitly tested multiprocessing page-render pool.
    socket.socket.connect = offline_connect
    for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        os.environ.pop(key, None)
    sys.exit(pytest.main(["tests", "-o", "addopts=", "-q"]))


if __name__ == "__main__":
    main()
