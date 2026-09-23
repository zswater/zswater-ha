"""Shared fixtures for the zswater tests.

``pytest_homeassistant_custom_component`` supplies the ``hass`` fixture and the
``enable_custom_integrations`` switch that lets Home Assistant load the
integration from ``custom_components/``. It is loaded conditionally so the
dependency-free tests still run in an environment where the harness is absent.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

# Make ``custom_components.zswater`` importable however pytest was invoked.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HAS_HA_HARNESS = (
    importlib.util.find_spec("pytest_homeassistant_custom_component") is not None
)

if HAS_HA_HARNESS:
    pytest_plugins = ("pytest_homeassistant_custom_component",)

if sys.platform == "win32" and HAS_HA_HARNESS:
    # The harness calls pytest_socket.disable_socket() from pytest_runtest_setup,
    # which runs before fixtures and cannot be re-enabled from a conftest hook in
    # time. Allowing only AF_UNIX is enough for asyncio on Linux, but the Windows
    # event loop builds its self-pipe from an AF_INET socketpair, so every async
    # test dies while its fixtures are being set up. Neutralise the call on
    # Windows only; the harness's socket_allow_hosts(["127.0.0.1"]) still stands,
    # no test here needs the network (the client is faked in all of them), and on
    # Linux the block stays in place.
    import pytest_socket

    pytest_socket.disable_socket = lambda *_args, **_kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Let Home Assistant load ``custom_components/zswater`` when the harness is present."""
    if HAS_HA_HARNESS:
        request.getfixturevalue("enable_custom_integrations")
    yield
