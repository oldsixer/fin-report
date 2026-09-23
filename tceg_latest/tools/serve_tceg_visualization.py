#!/usr/bin/env python3
"""Serve the TCEG frontend with a live JSON endpoint backed by current artifacts."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from build_tceg_visualization_data import DEFAULT_EXPERIMENT, build_payload


class TCEGHandler(SimpleHTTPRequestHandler):
    experiment: Path
    visualization: Path
    report_pdf: Path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.visualization), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/data":
            try:
                payload = build_payload(self.experiment)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_bytes(body, "application/json; charset=utf-8")
            except (OSError, ValueError, KeyError) as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if path == "/api/health":
            body = json.dumps({"status": "ok", "experiment": str(self.experiment)}).encode("utf-8")
            self.send_bytes(body, "application/json; charset=utf-8")
            return
        if path == "/api/report.pdf":
            if not self.report_pdf.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "report PDF not found")
                return
            payload = self.report_pdf.read_bytes()
            self.send_bytes(payload, mimetypes.guess_type(self.report_pdf.name)[0] or "application/pdf")
            return
        super().do_GET()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    args = parser.parse_args()

    experiment = args.experiment.resolve()
    visualization = experiment / "visualization"
    payload = build_payload(experiment)
    report_pdf = Path(payload["document"]["local_path"]).resolve()

    handler = type(
        "ConfiguredTCEGHandler",
        (TCEGHandler,),
        {"experiment": experiment, "visualization": visualization, "report_pdf": report_pdf},
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"TCEG viewer: http://{args.host}:{args.port}/")
    print("Live graph endpoint: /api/data (reloads artifacts on every request)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
