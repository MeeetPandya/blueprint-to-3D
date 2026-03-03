from __future__ import annotations

import argparse
import json
import mimetypes
import re
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .pipeline import BlueprintTo3DConfig, process_blueprint_to_obj

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
UPLOAD_DIR = OUTPUT_DIR / "uploads"
FRONTEND_DIR = ROOT_DIR / "frontend"


class BlueprintRequestHandler(BaseHTTPRequestHandler):
    server_version = "BlueprintTo3D/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: Path, content_type: str | None = None) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        data = file_path.read_bytes()
        guessed = content_type or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_config(self, params: dict[str, list[str]]) -> BlueprintTo3DConfig:
        def get_float(name: str, default: float) -> float:
            values = params.get(name)
            if not values:
                return default
            return float(values[0])

        def get_int(name: str, default: int) -> int:
            values = params.get(name)
            if not values:
                return default
            return int(values[0])

        return BlueprintTo3DConfig(
            wall_height_m=get_float("wall_height", 3.0),
            meters_per_pixel=get_float("scale", 0.02),
            min_component_area_px=get_int("min_area", 200),
            binarization_threshold=get_int("threshold", 180),
            min_wall_span_px=get_int("min_wall_span", 20),
            min_wall_thickness_px=get_int("min_wall_thickness", 2),
            min_component_density=get_float("min_density", 0.08),
            cleanup_iterations=get_int("cleanup_iterations", 1),
        )

    def _detect_extension(self, raw: bytes, content_type: str) -> str:
        lowered = content_type.lower()
        if raw.startswith(b"\x89PNG\r\n\x1a\n") or "png" in lowered:
            return ".png"
        if raw.startswith(b"P2") or raw.startswith(b"P5") or "pgm" in lowered or "portable-graymap" in lowered:
            return ".pgm"
        raise ValueError("Unsupported image upload. Use PNG or PGM.")

    def _list_models(self) -> list[dict[str, str | int]]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        models = []
        for model_path in sorted(OUTPUT_DIR.glob("*.obj"), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = model_path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            models.append(
                {
                    "name": model_path.name,
                    "size_bytes": stat.st_size,
                    "modified_utc": modified,
                    "download_url": f"/api/models/{model_path.name}",
                }
            )
        return models

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return

        if path == "/api/models":
            self._send_json(HTTPStatus.OK, {"models": self._list_models()})
            return

        if path.startswith("/api/models/"):
            name = path.removeprefix("/api/models/")
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.obj", name):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid model name."})
                return
            file_path = OUTPUT_DIR / name
            if not file_path.exists():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Model not found."})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            data = file_path.read_bytes()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/":
            self._serve_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
            return

        asset_path = (FRONTEND_DIR / path.lstrip("/")).resolve()
        if asset_path.exists() and asset_path.is_file() and FRONTEND_DIR in asset_path.parents:
            self._serve_file(asset_path)
            return

        self._serve_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path != "/api/convert":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Empty request body."})
            return

        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "application/octet-stream")

        try:
            config = self._parse_config(parse_qs(parsed.query, keep_blank_values=False))
            extension = self._detect_extension(raw, content_type)
        except (ValueError, TypeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        image_path = UPLOAD_DIR / f"upload-{timestamp}{extension}"
        output_path = OUTPUT_DIR / f"model-{timestamp}.obj"

        image_path.write_bytes(raw)

        try:
            process_blueprint_to_obj(image_path, output_path, config)
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "model": output_path.name,
                "download_url": f"/api/models/{output_path.name}",
            },
        )


def run_server(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), BlueprintRequestHandler)
    print(f"Server running at http://{host}:{port}")
    httpd.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Blueprint-to-3D HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
