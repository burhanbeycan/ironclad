"""
Figure extraction + caption detection.

This module currently:
- extracts embedded images to disk (PyMuPDF)
- detects caption strings containing "Figure"/"Fig."
- heuristically labels figure type (plot vs micrograph vs schematic) from caption keywords

Plot digitization is left as a "hook" for future versions (VLM/axis calibration).
"""

from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from .pdf import extract_images, iter_text_blocks

CAPTION_RE = re.compile(r"\b(Fig\.?|Figure)\s*\d+\b.*", flags=re.IGNORECASE)

PLOT_KEYWORDS = re.compile(
    r"\b(viscosity|modulus|nyquist|cole-cole|conductivity|tauc|stress[-\s]strain|frequency|shear rate|"
    r"arrhenius|impedance|EIS|G'|G''|tan\s*δ)\b",
    flags=re.IGNORECASE,
)
MICRO_KEYWORDS = re.compile(r"\b(SEM|TEM|AFM|micrograph|morphology|cross-section|cross section)\b", flags=re.IGNORECASE)


def extract_figures_and_captions(doc, out_dir: str | Path, prefix: str = "fig") -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    images = extract_images(doc, out_dir=out_dir, prefix=prefix)
    captions = find_figure_captions(doc)
    # Link by page
    for img in images:
        page = img["page"]
        cap = _best_caption_for_page(captions, page)
        img["caption"] = cap["text"] if cap else None
        img["caption_page"] = cap["page"] if cap else None
        img["figure_type"] = infer_figure_type(img.get("caption") or "")
        img["plot_like"] = bool(PLOT_KEYWORDS.search((img.get("caption") or "")))
    return {"images": images, "captions": captions}


def find_figure_captions(doc) -> List[Dict[str, Any]]:
    caps: List[Dict[str, Any]] = []
    for tb in iter_text_blocks(doc, min_len=5):
        m = CAPTION_RE.search(tb.text)
        if m:
            caps.append({"page": tb.page, "bbox": tb.bbox, "text": tb.text})
    return caps


def _best_caption_for_page(captions: List[Dict[str, Any]], page: int) -> Optional[Dict[str, Any]]:
    # Prefer caption on same page; else nearest subsequent page (common in two-column layouts)
    same = [c for c in captions if c["page"] == page]
    if same:
        # pick the longest caption on the page
        return sorted(same, key=lambda x: len(x["text"]), reverse=True)[0]
    after = [c for c in captions if c["page"] in (page + 1, page - 1)]
    if after:
        return sorted(after, key=lambda x: abs(x["page"] - page))[0]
    return None


def infer_figure_type(caption: str) -> str:
    c = caption or ""
    if MICRO_KEYWORDS.search(c):
        return "micrograph"
    if PLOT_KEYWORDS.search(c):
        return "plot"
    if "scheme" in c.lower() or "schematic" in c.lower():
        return "schematic"
    return "unknown"
