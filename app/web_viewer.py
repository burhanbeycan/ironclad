from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import posixpath
import shutil
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ironclad.engine import run as ironclad_run

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DEFAULT_OUT = ROOT / "outputs" / "web"


class IroncladWebHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, out_dir: Path | None = None, **kwargs):
        self.out_dir = out_dir or DEFAULT_OUT
        super().__init__(*args, directory=directory or str(DOCS_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok"})
            return

        if parsed.path.startswith("/api/files/"):
            self._serve_generated_file(parsed.path)
            return

        if parsed.path == "/":
            self.path = "/viewer.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._handle_pdf_analysis()
            self._send_json(payload)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_pdf_analysis(self) -> dict:
        ctype = self.headers.get("content-type", "")
        if "multipart/form-data" not in ctype:
            raise ValueError("Expected multipart/form-data with a 'pdf' file field.")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": ctype,
            },
        )

        pdf_field = form["pdf"] if "pdf" in form else None
        if pdf_field is None or not getattr(pdf_field, "file", None):
            raise ValueError("Missing PDF file field named 'pdf'.")

        filename = Path(pdf_field.filename or "paper.pdf").name
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Uploaded file must be a .pdf")

        doc_id = str(form.getfirst("doc_id", Path(filename).stem or "local:paper"))

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.out_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = job_dir / filename
        with pdf_path.open("wb") as f:
            shutil.copyfileobj(pdf_field.file, f)

        result = ironclad_run(
            pdf_path=pdf_path,
            doc_id=doc_id,
            out_dir=job_dir,
            extract_images_flag=True,
            reconstruct_tables_flag=True,
            extract_table_records_flag=True,
            baseline_path=None,
            table_fallback_mode="none",
        )

        output_json_path = Path(result["output_json"])
        payload = json.loads(output_json_path.read_text(encoding="utf-8"))

        for img in payload.get("figures", {}).get("images", []):
            path_value = img.get("path")
            if not path_value:
                continue
            try:
                rel = Path(path_value).resolve().relative_to(job_dir.resolve())
            except Exception:  # noqa: BLE001
                continue
            img["path"] = f"/api/files/{job_id}/{rel.as_posix()}"

        payload["_job_id"] = job_id
        return payload

    def _serve_generated_file(self, request_path: str):
        base = "/api/files/"
        tail = request_path[len(base):]
        parts = [p for p in tail.split("/") if p]
        if len(parts) < 2:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid file path")
            return

        job_id, rel_parts = parts[0], parts[1:]
        safe_rel = Path(posixpath.normpath("/".join(rel_parts)).lstrip("/"))
        full_path = (self.out_dir / job_id / safe_rel).resolve()

        expected_root = (self.out_dir / job_id).resolve()
        if not str(full_path).startswith(str(expected_root)):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not full_path.exists() or not full_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        self.send_response(HTTPStatus.OK)
        mime, _ = mimetypes.guess_type(str(full_path))
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(full_path.stat().st_size))
        self.end_headers()
        with full_path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description="Run local IRONCLAD viewer with PDF upload API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT), help="Output folder for analyzed PDFs")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    handler = lambda *h_args, **h_kwargs: IroncladWebHandler(  # noqa: E731
        *h_args,
        directory=str(DOCS_DIR),
        out_dir=out_dir,
        **h_kwargs,
    )

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"IRONCLAD web viewer running at http://{args.host}:{args.port}")
    print("Open /viewer.html, upload a PDF, and inspect results interactively.")
    server.serve_forever()


if __name__ == "__main__":
    main()
