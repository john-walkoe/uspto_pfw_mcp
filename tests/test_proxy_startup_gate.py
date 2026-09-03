"""A TCP listener on the proxy port is not proof that OUR proxy is there.

`_ensure_proxy_server_running` used to set `_proxy_server_running = True` on a
bare `connect_ex` success. The document tools then mint
`/document/persistent/{hash}` URLs — which are tokenless bearer credentials —
addressed to whatever holds the port, and POST the download registration plus
X-Proxy-Token to it. This mirrors uspto_ptab_mcp's own gate.
"""

import inspect
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from patent_filewrapper_mcp import server_bootstrap


class _Handler(BaseHTTPRequestHandler):
    body = b'{"service": "Something Else"}'

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def imposter():
    """A local HTTP server that answers 200 but is not a PFW proxy."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def dead_port():
    """A port with nothing listening on it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return port


class TestHealthyProxyProbe:
    def test_nothing_listening_is_not_a_healthy_proxy(self, dead_port):
        assert server_bootstrap._port_serves_healthy_proxy(dead_port) is False

    def test_a_foreign_http_service_is_not_a_healthy_proxy(self, imposter):
        assert server_bootstrap._port_serves_healthy_proxy(imposter) is False

    def test_a_pfw_proxy_root_payload_is_recognized(self, imposter, monkeypatch):
        monkeypatch.setattr(
            _Handler, "body", b'{"service": "USPTO Document Proxy"}', raising=False
        )
        assert server_bootstrap._port_serves_healthy_proxy(imposter) is True

    def test_the_expected_name_matches_what_the_proxy_actually_serves(self):
        """If the proxy's root payload is renamed, this gate silently starts
        refusing every reuse; pin the two together."""
        from patent_filewrapper_mcp.proxy.routes import admin

        source = inspect.getsource(admin)
        assert f'"{server_bootstrap._PROXY_SERVICE_NAME}"' in source


class TestBusyPortBranch:
    def test_the_busy_branch_verifies_the_service(self):
        """Source-level, in the spirit of test_identifier_resolution_order.py:
        the busy-port branch must consult the probe rather than adopt a bare
        connect."""
        source = inspect.getsource(server_bootstrap._ensure_proxy_server_running)
        assert "_port_serves_healthy_proxy(port)" in source, (
            "the port-busy branch adopts a listener without verifying it is a "
            "PFW proxy"
        )

    @pytest.mark.asyncio
    async def test_a_foreign_listener_does_not_mark_the_proxy_running(
        self, imposter, monkeypatch
    ):
        monkeypatch.setattr(server_bootstrap, "_proxy_server_running", False)
        await server_bootstrap._ensure_proxy_server_running(imposter)
        assert server_bootstrap._proxy_server_running is False, (
            "a foreign service holding the port was adopted as our proxy"
        )

    @pytest.mark.asyncio
    async def test_a_healthy_listener_is_reused_without_starting_a_second(
        self, imposter, monkeypatch
    ):
        monkeypatch.setattr(
            _Handler, "body", b'{"service": "USPTO Document Proxy"}', raising=False
        )
        monkeypatch.setattr(server_bootstrap, "_proxy_server_running", False)
        monkeypatch.setattr(server_bootstrap, "_proxy_server_task", None)

        await server_bootstrap._ensure_proxy_server_running(imposter)

        assert server_bootstrap._proxy_server_running is True
        assert server_bootstrap._proxy_server_task is None, (
            "a second proxy was started over a healthy one"
        )
