"""ironclad.tables_caption

Caption-anchored table reconstruction.

Why this exists
- Layout-based heuristics can misfire on dense reference sections.
- Many ACS-style PDFs contain explicit "Table X" captions in the text layer,
  even when the table grid is drawn.

Strategy
1) Scan each page's extracted *text lines* for "Table <n>" captions.
2) Collect subsequent lines until a stopping marker (next Table/Figure/Scheme)
   or obvious footer/header noise.
3) Reconstruct a simple row/column structure using deterministic heuristics.

This is intentionally conservative; if parsing fails, return no table.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import re

from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .tables import Table
from .ocr_tables import ocr_table_from_image
from .vlm_tables import parse_table_with_openai


CAPTION_RE = re.compile(r"^\s*Table\s+(\d+)\s*\.?\s*(.*)$", flags=re.IGNORECASE)
STOP_RE = re.compile(r"^\s*(Figure|Scheme|Table)\s+\d+\b", flags=re.IGNORECASE)

# Common ACS footer/header artefacts
NOISE_RE = re.compile(
    r"(pubs\.acs\.org|https?://doi\.org|Ind\.\s*Eng\.\s*Chem\.\s*Res\.|Industrial\s*&\s*Engineering\s*Chemistry\s*Research)",
    flags=re.IGNORECASE,
)

HEADER_STOPWORDS = {
    "sample", "samples", "electrolyte", "electrolytes", "property", "value", "unit",
    "viscosity", "conductivity", "concentration", "ref", "reference", "literature",
    "this work", "present work", "mn", "mw", "mz", "mv", "pdi", "dispersity",
}


def extract_caption_tables(
    doc,
    *,
    fallback_mode: str = "none",
    ocr_out_dir: Optional[str | Path] = None,
    vlm_model: str = "gpt-4o-mini",
) -> List[Table]:
    """Extract tables anchored by explicit 'Table <n>' captions.

    Parameters
    ----------
    fallback_mode:
        "none" (default): only parse tables that exist in the PDF text layer.
        "ocr": when caption parsing fails, rasterize the region below the caption
               and OCR it (Tesseract via pytesseract).
        "vlm": use a vision-language model (OpenAI) as a fallback instead of OCR.
    ocr_out_dir:
        If provided, saves cropped table images for reproducibility.
    """

    tables: List[Table] = []

    fallback_mode = (fallback_mode or "none").strip().lower()
    if fallback_mode not in {"none", "ocr", "vlm"}:
        fallback_mode = "none"

    if ocr_out_dir is not None:
        ocr_out_dir = Path(ocr_out_dir)
        ocr_out_dir.mkdir(parents=True, exist_ok=True)

    for p in range(len(doc)):
        page = doc[p]
        raw_text = page.get_text("text")
        if not raw_text:
            continue

        lines = [ln.rstrip() for ln in raw_text.splitlines()]
        i = 0
        while i < len(lines):
            line = (lines[i] or "").strip()
            m = CAPTION_RE.match(line)
            if not m:
                i += 1
                continue

            rest = (m.group(2) or "").strip()
            if rest:
                first = rest.split()[0].lower()
                if rest[:1].islower() or first in {"shows","presents","summarizes","lists","reports","depicts","discloses"}:
                    i += 1
                    continue

            table_number = _safe_int(m.group(1))
            caption = line

            # Caption can wrap to the next line(s). We'll join a small number of continuation lines
            # until we reach something that looks like a column header or the first data row.
            j = i + 1
            cont_count = 0
            while j < len(lines) and cont_count < 3:
                nxt = (lines[j] or "").strip()
                if not nxt:
                    j += 1
                    continue
                if STOP_RE.match(nxt):
                    break

                # If the caption line is clearly unfinished (common in two-line captions),
                # keep joining even if the next token *looks* like data (e.g., "and" + "WBPU7").
                tail = (caption.strip().split()[-1].lower() if caption.strip() else "")
                if tail in {"and", "or", "of", "for", "with", "in"}:
                    caption += " " + nxt
                    cont_count += 1
                    j += 1
                    continue

                if _looks_like_header_or_data_start(nxt):
                    break

                caption += " " + nxt
                cont_count += 1
                j += 1

            # Collect table body lines
            body: List[str] = []
            k = j
            while k < len(lines):
                cur = (lines[k] or "").strip()
                if not cur:
                    # allow occasional blanks inside; don't stop immediately
                    k += 1
                    continue
                if STOP_RE.match(cur):
                    break
                if NOISE_RE.search(cur):
                    # stop if we already started collecting content
                    if body:
                        break
                    k += 1
                    continue
                # Page numbers / running headers at bottom
                if body and re.fullmatch(r"\d{4,}", cur):
                    break

                body.append(cur)
                k += 1

            parsed_text = _parse_table_from_lines(body)

            parsed: Optional[Tuple[List[str], List[List[str]], Tuple[float, float, float, float], dict]] = None
            if parsed_text is not None:
                header0, rows0 = parsed_text
                parsed = (
                    header0,
                    rows0,
                    (0.0, 0.0, 0.0, 0.0),
                    {"source": "caption_text"},
                )

            if parsed is None and fallback_mode in {"ocr", "vlm"}:
                # OCR/VLM fallback for image-based tables.
                cap_bbox = _find_caption_bbox(page, table_number)
                stop_y = _find_stop_y(page, cap_bbox)
                parsed = _fallback_table_parse(
                    page,
                    table_number=table_number,
                    caption=caption,
                    cap_bbox=cap_bbox,
                    stop_y=stop_y,
                    mode=fallback_mode,
                    out_dir=ocr_out_dir,
                    vlm_model=vlm_model,
                )

            if parsed is not None:
                header, rows, bbox, extra_meta = parsed
                if rows:
                    meta = {
                        "caption": caption,
                        "table_number": table_number,
                    }
                    meta.update(extra_meta or {})
                    tables.append(
                        Table(
                            page=p + 1,
                            bbox=bbox,
                            rows=rows,
                            column_x=[],
                            header=header,
                            meta=meta,
                        )
                    )

            i = k  # jump past the body

    return tables


def _find_caption_bbox(page, table_number: Optional[int]) -> Optional[Tuple[float, float, float, float]]:
    """Return bbox for the line containing 'Table <n>' if available."""
    if table_number is None:
        return None
    try:
        d = page.get_text("dict")
    except Exception:
        return None
    target = f"table {table_number}"
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for ln in block.get("lines", []):
            spans = ln.get("spans", [])
            if not spans:
                continue
            txt = "".join(sp.get("text", "") for sp in spans).strip()
            if not txt:
                continue
            if txt.lower().startswith(target):
                # union bbox
                xs0 = [sp.get("bbox", (0, 0, 0, 0))[0] for sp in spans]
                ys0 = [sp.get("bbox", (0, 0, 0, 0))[1] for sp in spans]
                xs1 = [sp.get("bbox", (0, 0, 0, 0))[2] for sp in spans]
                ys1 = [sp.get("bbox", (0, 0, 0, 0))[3] for sp in spans]
                return (float(min(xs0)), float(min(ys0)), float(max(xs1)), float(max(ys1)))
    return None


def _find_stop_y(page, cap_bbox: Optional[Tuple[float, float, float, float]]) -> float:
    """Find a reasonable lower bound for the caption-anchored region."""
    rect = page.rect
    y_start = cap_bbox[3] if cap_bbox else 0.0
    y_candidates: List[float] = []
    try:
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for ln in block.get("lines", []):
                spans = ln.get("spans", [])
                if not spans:
                    continue
                txt = "".join(sp.get("text", "") for sp in spans).strip()
                if not txt:
                    continue
                if STOP_RE.match(txt):
                    # union bbox of the line
                    ys0 = [sp.get("bbox", (0, 0, 0, 0))[1] for sp in spans]
                    y0 = float(min(ys0))
                    if y0 > y_start + 10:
                        y_candidates.append(y0)
    except Exception:
        pass

    if y_candidates:
        return float(min(y_candidates))
    # Default: until the bottom (minus small footer margin)
    return float(rect.height - 20)


def _fallback_table_parse(
    page,
    *,
    table_number: Optional[int],
    caption: str,
    cap_bbox: Optional[Tuple[float, float, float, float]],
    stop_y: float,
    mode: str,
    out_dir: Optional[Path],
    vlm_model: str,
) -> Optional[Tuple[List[str], List[List[str]], Tuple[float, float, float, float], dict]]:
    """OCR/VLM fallback for a caption-anchored table.

    Returns (header, rows, bbox, meta) or None.
    """
    rect = page.rect
    y0 = float(cap_bbox[3]) if cap_bbox else 0.0

    # Try to find an embedded image block below the caption.
    clip_bbox: Tuple[float, float, float, float] = (0.0, y0, float(rect.width), float(stop_y))
    try:
        d = page.get_text("dict")
        img_blocks = [b for b in d.get("blocks", []) if b.get("type") == 1 and b.get("bbox")]
        best = None
        best_area = 0.0
        for b in img_blocks:
            bx0, by0, bx1, by1 = map(float, b.get("bbox"))
            if by0 < y0 - 5:
                continue
            if by0 > stop_y:
                continue
            area = max(0.0, (bx1 - bx0)) * max(0.0, (by1 - by0))
            if area > best_area:
                best_area = area
                best = (bx0, by0, bx1, by1)
        if best is not None and best_area > 1.0:
            # Expand slightly for OCR robustness.
            bx0, by0, bx1, by1 = best
            clip_bbox = (
                max(0.0, bx0 - 8),
                max(0.0, by0 - 6),
                min(float(rect.width), bx1 + 8),
                min(float(rect.height), by1 + 6),
            )
    except Exception:
        pass

    clip = fitz.Rect(*clip_bbox)
    # Render region
    try:
        pix = page.get_pixmap(clip=clip, dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except Exception as e:
        return None

    img_path = None
    if out_dir is not None and table_number is not None:
        img_path = out_dir / f"table{table_number}_p{page.number+1}.png"
        try:
            img.save(img_path)
        except Exception:
            img_path = None

    meta: dict = {
        "source": f"caption_{mode}",
        "caption": caption,
        "crop_bbox": clip_bbox,
    }
    if img_path is not None:
        meta["crop_path"] = str(img_path)

    if mode == "ocr":
        header, rows, ocr_meta = ocr_table_from_image(img)
        meta.update({"ocr": ocr_meta})
        if header and rows:
            return header, rows, clip_bbox, meta
        return None

    if mode == "vlm":
        if img_path is None:
            # Save to temp path in-memory is more complex; require disk for now.
            return None
        try:
            header, rows, vlm_meta = parse_table_with_openai(str(img_path), caption=caption, model=vlm_model)
            meta.update({"vlm": vlm_meta})
            if header and rows:
                return header, rows, clip_bbox, meta
        except Exception as e:
            meta.update({"vlm": {"ok": False, "error": str(e), "model": vlm_model}})
        return None

    return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _looks_like_header_or_data_start(line: str) -> bool:
    l = line.strip()
    if not l:
        return False

    # Column headers often are short tokens (Mn, Mw, PDI) or contain units (g/mol).
    if "(" in l and ")" in l:
        return True
    if len(l) <= 6 and any(ch.isalpha() for ch in l):
        return True

    # Data starts with row labels: digits (trial number) or token-like sample names.
    if re.fullmatch(r"\d+", l):
        return True
    if _is_token_like_name(l):
        # Stronger signal for a data-row label: digits/hyphens or all-caps tokens.
        if any(ch.isdigit() for ch in l) or "-" in l or "−" in l or l.isupper():
            return True

    return False


def _is_token_like_name(s: str) -> bool:
    ss = s.strip()
    low = ss.lower()
    if low in HEADER_STOPWORDS:
        return False
    if "(" in ss or ")" in ss:
        return False
    if len(ss) > 35:
        return False
    # A row label tends to have at least one capital, digit, or hyphen.
    if any(ch.isdigit() for ch in ss):
        return True
    if "-" in ss or "−" in ss:
        return True
    if any(ch.isupper() for ch in ss) and any(ch.isalpha() for ch in ss):
        return True
    return False


def _parse_table_from_lines(lines: List[str]) -> Optional[Tuple[List[str], List[List[str]]]]:
    """Heuristically reconstruct header + rows from a list of extracted lines."""

    if not lines or len(lines) < 3:
        return None

    # Split into header segment and data segment.
    first_data_idx = None
    for idx, ln in enumerate(lines):
        if _is_token_like_name(ln) or re.fullmatch(r"\d+", ln):
            first_data_idx = idx
            break

    if first_data_idx is None or first_data_idx == 0:
        return None

    header_lines = [ln.strip() for ln in lines[:first_data_idx] if ln.strip()]
    data_lines = [ln.strip() for ln in lines[first_data_idx:] if ln.strip()]

    if not header_lines or not data_lines:
        return None

    header = _merge_header_lines(header_lines)

    # If header does not include an explicit sample/electrolyte column, prepend a generic one.
    header_joined = " ".join(header).lower()
    if not ("sample" in header_joined or "electrolyte" in header_joined or "trial" in header_joined):
        header = ["sample"] + header

    n_cols = len(header)
    n_vals = n_cols - 1

    # Parse rows in a strict, deterministic way: label + fixed number of following cells.
    rows: List[List[str]] = []
    i = 0
    while i < len(data_lines):
        label = data_lines[i]
        # Stop if we hit something clearly not part of the table
        if STOP_RE.match(label) or NOISE_RE.search(label):
            break
        row = [label]
        for _ in range(n_vals):
            i += 1
            if i >= len(data_lines):
                break
            row.append(data_lines[i])
        if len(row) == n_cols:
            rows.append(row)
        i += 1

    if not rows:
        return None

    return header, rows


def _merge_header_lines(header_lines: List[str]) -> List[str]:
    """Merge stacked header tokens into column labels.

    Example:
        ["Mn", "(g/mol)", "Mw", "(g/mol)", "PDI"]
    ->  ["Mn (g/mol)", "Mw (g/mol)", "PDI"]
    """

    out: List[str] = []
    for ln in header_lines:
        if ln.startswith("(") and ln.endswith(")") and out:
            out[-1] = f"{out[-1]} {ln}"
            continue
        # Common case: unit line is just "(g/mol)" or similar.
        if ln.lower() in {"(g/mol)", "(mol/l)", "(ms/cm)", "(s/cm)", "(pa·s)", "(pa*s)"} and out:
            out[-1] = f"{out[-1]} {ln}"
            continue
        out.append(ln)

    # Drop obvious single-word fillers if present
    out2 = []
    for c in out:
        if c.strip().lower() in {"sample", "samples"}:
            out2.append("sample")
        else:
            out2.append(c.strip())
    return out2
