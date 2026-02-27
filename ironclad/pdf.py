"""
IRONCLAD PDF utilities (PyMuPDF-based).

Design goals:
- layout-anchored provenance: every text block has page + bbox
- deterministic extraction: avoid OCR; prefer PDF text layer
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Tuple, Optional, Dict, Any
from pathlib import Path

import fitz  # PyMuPDF


@dataclass(frozen=True)
class TextBlock:
    page: int
    bbox: Tuple[float, float, float, float]  # (x0,y0,x1,y1)
    text: str


@dataclass(frozen=True)
class Span:
    text: str
    bbox: Tuple[float, float, float, float]
    size: float
    font: str


@dataclass(frozen=True)
class Line:
    page: int
    bbox: Tuple[float, float, float, float]
    spans: Tuple[Span, ...]


def open_pdf(pdf_path: str | Path) -> fitz.Document:
    return fitz.open(str(pdf_path))


def iter_text_blocks(doc: fitz.Document, min_len: int = 3) -> Iterator[TextBlock]:
    """
    Yield layout blocks with bbox provenance.
    """
    for pno in range(len(doc)):
        page = doc[pno]
        blocks = page.get_text("blocks")  # list: (x0,y0,x1,y1,text,block_no,block_type)
        for b in blocks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            if not text:
                continue
            t = " ".join(text.split())
            if len(t) < min_len:
                continue
            yield TextBlock(page=pno + 1, bbox=(x0, y0, x1, y1), text=t)


def get_page_lines(doc: fitz.Document, page_no_1idx: int) -> List[Line]:
    """
    Reconstruct lines from PDF span-level layout to support table reconstruction and section heuristics.
    """
    pno = page_no_1idx - 1
    page = doc[pno]
    d = page.get_text("dict")
    lines_out: List[Line] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for ln in block.get("lines", []):
            spans: List[Span] = []
            for sp in ln.get("spans", []):
                txt = sp.get("text", "")
                if not txt or not txt.strip():
                    continue
                spans.append(Span(
                    text=txt,
                    bbox=tuple(sp.get("bbox", (0, 0, 0, 0))),
                    size=float(sp.get("size", 0.0)),
                    font=str(sp.get("font", "")),
                ))
            if not spans:
                continue
            # line bbox is union of spans
            x0 = min(s.bbox[0] for s in spans); y0 = min(s.bbox[1] for s in spans)
            x1 = max(s.bbox[2] for s in spans); y1 = max(s.bbox[3] for s in spans)
            lines_out.append(Line(page=page_no_1idx, bbox=(x0, y0, x1, y1), spans=tuple(spans)))
    return lines_out


def extract_images(doc: fitz.Document, out_dir: str | Path, prefix: str = "img") -> List[Dict[str, Any]]:
    """
    Extract embedded images from a PDF.
    Returns list with {page, path, width, height, xref}.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[Dict[str, Any]] = []
    for pno in range(len(doc)):
        page = doc[pno]
        for idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base = doc.extract_image(xref)
            ext = base.get("ext", "png")
            img_bytes = base.get("image")
            if not img_bytes:
                continue
            fname = f"{prefix}_p{pno+1}_{idx}.{ext}"
            fpath = out_dir / fname
            fpath.write_bytes(img_bytes)
            extracted.append({
                "page": pno + 1,
                "path": str(fpath),
                "width": base.get("width"),
                "height": base.get("height"),
                "xref": xref,
                "ext": ext,
            })
    return extracted
