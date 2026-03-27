"""HTTP server that serves workspace files as API responses.

Reads files from disk on EVERY request (no caching), so poisoning a file
on disk immediately changes the HTTP response. This is the key mechanism
for tool scenarios: the poisoner updates workspace files, and the
agent's web_fetch tool gets poisoned data from this server.
"""

import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger(__name__)


def _make_handler(serve_dir: str, routes: dict[str, str]):
    """Create a request handler class bound to a serve directory and route table."""

    class WorkspaceHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Strip query string
            path = self.path.split("?")[0]

            file_rel = routes.get(path)
            if file_rel is None:
                self.send_error(404, f"No route for {path}")
                return

            file_path = Path(serve_dir) / file_rel
            try:
                content = file_path.read_text()
            except FileNotFoundError:
                self.send_error(404, f"Data file not found: {file_rel}")
                return
            except Exception as e:
                self.send_error(500, str(e))
                return

            self.send_response(200)
            if file_rel.endswith(".json"):
                self.send_header("Content-Type", "application/json")
            elif file_rel.endswith(".csv"):
                self.send_header("Content-Type", "text/csv")
            elif file_rel.endswith(".html"):
                self.send_header("Content-Type", "text/html")
            else:
                self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def log_message(self, format, *args):
            # Suppress default stderr logging, use our logger
            logger.debug(f"HTTP: {args[0] if args else ''}")

    return WorkspaceHandler


class WorkspaceHTTPServer:
    """HTTP server that serves workspace files via route mapping.

    Args:
        serve_dir: Absolute path to the workspace directory.
        routes: Map of URL paths to workspace-relative file paths.
                e.g. {"/api/products": "api_data/products.json"}
        port: Port to listen on. 0 = OS picks a free port.
    """

    def __init__(self, serve_dir: str, routes: dict[str, str], port: int = 0):
        self.serve_dir = serve_dir
        self.routes = routes
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        """Start the server in a daemon thread. Returns the actual port."""
        handler = _make_handler(self.serve_dir, self.routes)
        self._server = HTTPServer(("127.0.0.1", self.port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"workspace-http-{self.port}",
        )
        self._thread.start()
        logger.info(f"Workspace HTTP server started on port {self.port}")
        return self.port

    def stop(self) -> None:
        """Shut down the server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("Workspace HTTP server stopped")
