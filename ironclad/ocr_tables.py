"""ironclad.ocr_tables

OCR-based table extraction utilities.

Why we need this
----------------
Caption-anchored parsing (``tables_caption.py``) works well when the table
exists in the PDF text layer. However, many chemistry papers embed tables as
images (scans, rasterized exports, or vector objects without selectable text).

This module provides a **deterministic, auditable** OCR fallback:
1) render a page region to an image (handled upstream);
2) run OCR (Tesseract via ``pytesseract``);
3) reconstruct a row/column grid using only geometry (word bounding boxes).

Design goals
------------
- No silent failures: return structured diagnostics in ``meta``.
- Robust to ACS-style tables with compact spacing.
- Keep dependencies optional: if OCR is not available, callers can skip.

Notes
-----
- ``pytesseract`` requires the *Tesseract* binary to be installed and on PATH.
- This code intentionally avoids heavy ML table-structure models; users can
  swap in a VLM parser (see ``vlm_tables.py``) when desired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import re
import statistics


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        return True
    except Exception:
        return False


_HAS_DIGIT = re.compile(r"\d")
_HAS_ALPHA = re.compile(r"[A-Za-z]")


@dataclass
class OCRWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float

    @property
    def x0(self) -> int:
        return self.left

    @property
    def x1(self) -> int:
        return self.left + self.width

    @property
    def y0(self) -> int:
        return self.top

    @property
    def y1(self) -> int:
        return self.top + self.height

    @property
    def y_center(self) -> float:
        return self.top + 0.5 * self.height


def ocr_table_from_image(
    pil_image,
    *,
    min_conf: int = 35,
    psm: int = 6,
) -> Tuple[Optional[List[str]], List[List[str]], Dict[str, Any]]:
    """OCR a table image and reconstruct a (header, rows) grid.

    Returns
    -------
    header : Optional[List[str]]
        Column headers if detected, else ``None``.
    rows : List[List[str]]
        Data rows (excluding header).
    meta : Dict[str, Any]
        Diagnostics: OCR stats, inferred columns, etc.
    """

    try:
        import pytesseract
    except Exception as e:
        return None, [], {
            "ok": False,
            "error": f"pytesseract not available: {e}",
        }

    # Collect words with bounding boxes.
    try:
        data = pytesseract.image_to_data(
            pil_image,
            output_type=pytesseract.Output.DICT,
            config=f"--psm {int(psm)}",
        )
    except Exception as e:
        return None, [], {
            "ok": False,
            "error": f"OCR engine error. Is Tesseract installed and on PATH? ({e})",
        }

    words: List[OCRWord] = []
    n = len(data.get("text", []))
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        try:
            conf = float(data.get("conf", ["-1"])[i])
        except Exception:
            conf = -1.0
        if conf < float(min_conf):
            continue
        words.append(
            OCRWord(
                text=txt,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                conf=conf,
            )
        )

    if not words:
        return None, [], {
            "ok": False,
            "error": "No OCR words above confidence threshold.",
            "min_conf": min_conf,
        }

    heights = [w.height for w in words]
    widths = [w.width for w in words]
    med_h = statistics.median(heights) if heights else 10
    med_w = statistics.median(widths) if widths else 10

    row_tol = max(6.0, 0.7 * float(med_h))
    gap_tol = max(18.0, 1.8 * float(med_w))
    col_tol = max(20.0, 2.2 * float(med_w))

    # Group words into rows by y_center proximity.
    words_sorted = sorted(words, key=lambda w: (w.y_center, w.x0))
    row_groups: List[List[OCRWord]] = []
    cur: List[OCRWord] = []
    cur_y: Optional[float] = None
    for w in words_sorted:
        if cur_y is None:
            cur = [w]
            cur_y = w.y_center
            continue
        if abs(w.y_center - cur_y) <= row_tol:
            cur.append(w)
            # running average for stability
            cur_y = (cur_y * (len(cur) - 1) + w.y_center) / float(len(cur))
        else:
            row_groups.append(cur)
            cur = [w]
            cur_y = w.y_center
    if cur:
        row_groups.append(cur)

    # Convert each row group to (cell_x, cell_text) by splitting on large x-gaps.
    rows_cells: List[List[Tuple[float, str]]] = []
    for rg in row_groups:
        rg = sorted(rg, key=lambda w: w.x0)
        if not rg:
            continue
        cells: List[Tuple[float, str]] = []
        buf = [rg[0]]
        for w in rg[1:]:
            prev = buf[-1]
            gap = float(w.x0 - prev.x1)
            if gap > gap_tol:
                text = " ".join(b.text for b in buf).strip()
                if text:
                    cells.append((float(min(b.x0 for b in buf)), text))
                buf = [w]
            else:
                buf.append(w)
        text = " ".join(b.text for b in buf).strip()
        if text:
            cells.append((float(min(b.x0 for b in buf)), text))

        # Discard trivially short lines that are unlikely to be table rows.
        if len(cells) >= 2:
            rows_cells.append(cells)

    if len(rows_cells) < 2:
        return None, [], {
            "ok": False,
            "error": "OCR produced too few structured rows.",
            "row_count": len(rows_cells),
        }

    # Infer global columns from cell x-positions.
    xs = sorted({round(x, 1) for row in rows_cells for x, _ in row})
    col_x: List[float] = []
    for x in xs:
        if not col_x or abs(x - col_x[-1]) > col_tol:
            col_x.append(float(x))

    # Align rows to columns.
    grid: List[List[str]] = []
    for row in rows_cells:
        out = ["" for _ in range(len(col_x))]
        for x, txt in row:
            j = min(range(len(col_x)), key=lambda k: abs(x - col_x[k]))
            out[j] = (out[j] + " " + txt).strip() if out[j] else txt
        # Trim trailing empties
        while out and out[-1] == "":
            out.pop()
        if out:
            grid.append(out)

    if len(grid) < 2:
        return None, [], {
            "ok": False,
            "error": "OCR grid alignment failed.",
        }

    # Heuristic header detection.
    def row_stats(r: List[str]) -> Tuple[int, int]:
        # (alpha_count, digit_count)
        a = sum(1 for c in r if _HAS_ALPHA.search(c or ""))
        d = sum(1 for c in r if _HAS_DIGIT.search(c or ""))
        return a, d

    a0, d0 = row_stats(grid[0])
    a1, d1 = row_stats(grid[1])
    header: Optional[List[str]] = None
    data_rows = grid
    if a0 >= 2 and d0 <= max(1, a0) and d1 >= d0:
        header = grid[0]
        data_rows = grid[1:]

    meta: Dict[str, Any] = {
        "ok": True,
        "engine": "tesseract",
        "psm": int(psm),
        "min_conf": int(min_conf),
        "words": len(words),
        "row_groups": len(row_groups),
        "grid_rows": len(grid),
        "grid_cols": len(col_x),
        "column_x": col_x,
        "row_tol": row_tol,
        "gap_tol": gap_tol,
        "col_tol": col_tol,
        "conf_mean": sum(w.conf for w in words) / float(len(words)),
    }
    return header, data_rows, meta
