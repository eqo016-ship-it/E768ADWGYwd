import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/health", "/ping"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        logger.debug("Health %s", args[0] if args else "")


def start_health_server(port: int) -> None:
    try:
        srv = HTTPServer(("0.0.0.0", int(port)), HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        logger.info("Health server on 0.0.0.0:%s", port)
    except Exception as e:
        logger.warning("Health server gagal: %s", e)
