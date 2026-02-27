"""
IRONCLAD v3 (desktop demo) engine.

Adds:
- origin classification (this work vs literature)
- table reconstruction + (optional) table-to-record extraction
- figure extraction + caption linking
- comparison table: this work vs cited literature vs external baseline
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import re
import time

from .pdf import open_pdf, iter_text_blocks, TextBlock
from .extractors import extract_from_textblock, infer_document_material
from .constraints import evaluate_constraints
from .tables import extract_tables
from .tables_caption import extract_caption_tables
from .table_extract import records_from_tables
from .figures import extract_figures_and_captions
from .compare import build_comparison_table
from .io import save_json, save_csv, load_baseline


HEADER_FOOTER_MARGIN = 60  # PDF points
DOI_RE = re.compile(r"\bdoi\b|10\.\d{4,9}/", flags=re.IGNORECASE)


def run(pdf_path: str | Path,
        doc_id: str,
        out_dir: str | Path,
        extract_images_flag: bool = True,
        reconstruct_tables_flag: bool = True,
        extract_table_records_flag: bool = True,
        baseline_path: Optional[str | Path] = None,
        table_fallback_mode: str = "none",
        vlm_model: str = "gpt-4o-mini",
        ) -> Dict[str, Any]:

    t0 = time.time()
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logs: List[str] = []
    logs.append(f"IRONCLAD run started: {pdf_path.name}")
    logs.append(f"Output dir: {out_dir}")

    doc = open_pdf(pdf_path)

    # Build filtered text blocks (exclude headers/footers and DOI noise)
    blocks = list(_iter_text_blocks_filtered(doc))
    logs.append(f"Parsed {len(blocks)} text blocks after header/footer filtering.")

    doc_text = "\n".join(b.text for b in blocks)
    default_material = infer_document_material(doc_text) or "UNKNOWN"
    logs.append(f"Default material guess: {default_material}")

    # Text extraction
    records: List[Dict[str, Any]] = []
    for tb in blocks:
        records.extend(extract_from_textblock(tb, doc_id=doc_id, default_material=default_material))
    logs.append(f"Extracted {len(records)} text-derived candidate records.")

    # Table reconstruction (caption-anchored, ACS-friendly)
    tables_out = []
    tables = []
    if reconstruct_tables_flag:
        # Preflight checks for optional table fallback modes.
        tfm = (table_fallback_mode or "none").strip().lower()
        if tfm == "ocr":
            try:
                from .ocr_tables import ocr_available
                if not ocr_available():
                    logs.append("Table fallback=OCR selected, but 'pytesseract' is not available. Install it or set Table fallback=None.")
                else:
                    try:
                        import pytesseract
                        _ = pytesseract.get_tesseract_version()
                    except Exception as e:
                        logs.append(
                            "Table fallback=OCR selected, but the Tesseract binary was not found/working. "
                            "Install Tesseract and ensure it is on PATH. "
                            f"(details: {e})"
                        )
            except Exception:
                # Never fail the run due to optional checks.
                pass
        elif tfm == "vlm":
            try:
                from .vlm_tables import openai_vlm_available
                import os
                if not openai_vlm_available():
                    logs.append("Table fallback=VLM selected, but the 'openai' package is not installed. Install it or set Table fallback=None.")
                elif not os.getenv("OPENAI_API_KEY"):
                    logs.append("Table fallback=VLM selected, but OPENAI_API_KEY is not set. Set it in your environment to enable VLM parsing.")
            except Exception:
                pass

        # Caption-anchored extraction is the primary strategy.
        # Optional fallback: OCR/VLM for image-based tables.
        ocr_dir = out_dir / "table_crops" if tfm in {"ocr", "vlm"} else None
        tables = extract_caption_tables(
            doc,
            fallback_mode=table_fallback_mode,
            ocr_out_dir=ocr_dir,
            vlm_model=vlm_model,
        )
        if not tables:
            # fallback to layout heuristic
            tables = extract_tables(doc)
            logs.append('Caption-anchored table extraction found no tables; fell back to layout heuristic.')
        logs.append(f"Detected {len(tables)} tables.")

        for i, t in enumerate(tables):
            tnum = None
            if getattr(t, 'meta', None) and isinstance(t.meta, dict):
                tnum = t.meta.get('table_number')
            tid = f"T{tnum}" if tnum is not None else f"T{i+1}"
            tables_out.append({
                'table_id': tid,
                'page': t.page,
                'bbox': t.bbox,
                'rows': t.rows,
                'header': t.header,
                'meta': t.meta or {},
            })

        if extract_table_records_flag and tables:
            t_recs = records_from_tables(tables, doc_id=doc_id, default_material=default_material)
            logs.append(f"Extracted {len(t_recs)} table-derived records.")
            records.extend(t_recs)

    # Figures/images
    figures_out = {}
    if extract_images_flag:
        fig_dir = out_dir / "images"
        figures_out = extract_figures_and_captions(doc, out_dir=fig_dir)
        logs.append(f"Extracted {len(figures_out.get('images', []))} embedded images.")

    # Constraints
    evaluate_constraints(records)
    hard_fail_count = sum(1 for r in records if r.get("constraints", {}).get("hard_fail"))
    logs.append(f"Constraint evaluation done. Records with hard-fails: {hard_fail_count}.")

    # External baseline loading
    baseline_records = load_baseline(baseline_path) if baseline_path else []
    if baseline_path:
        logs.append(f"Loaded baseline records: {len(baseline_records)} from {baseline_path}")

    # Comparison table
    comparison_rows = build_comparison_table(records, baseline_records=baseline_records)
    logs.append(f"Built comparison table with {len(comparison_rows)} rows.")

    # Persist outputs
    out_json = out_dir / "ironclad_output.json"
    save_json(out_json, {"doc_id": doc_id, "pdf": str(pdf_path), "records": records, "tables": tables_out, "figures": figures_out, "comparison": comparison_rows, "logs": logs})

    # Flat CSV summary
    csv_rows = [_flat_row(r) for r in records]
    out_csv = out_dir / "ironclad_summary.csv"
    save_csv(out_csv, csv_rows)

    out_cmp = out_dir / "ironclad_comparison.csv"
    save_csv(out_cmp, comparison_rows)

    # Save tables as JSON too
    if tables_out:
        save_json(out_dir / "ironclad_tables.json", tables_out)

    # Save figure manifest
    if figures_out:
        save_json(out_dir / "ironclad_figures.json", figures_out)

    elapsed = time.time() - t0
    logs.append(f"Run finished in {elapsed:.2f} s.")
    return {
        "records": records,
        "tables": tables_out,
        "figures": figures_out,
        "comparison": comparison_rows,
        "logs": logs,
        "output_json": str(out_json),
        "output_csv": str(out_csv),
        "output_comparison_csv": str(out_cmp),
    }


def _iter_text_blocks_filtered(doc) -> List[TextBlock]:
    """
    Filter out likely headers/footers and DOI strings.
    """
    # Compute repeated blocks (exact text) across pages -> headers
    per_page = {}
    for pno in range(len(doc)):
        page = doc[pno]
        blocks = page.get_text("blocks")
        page_h = float(page.rect.height)
        out = []
        for b in blocks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            if not text:
                continue
            t = " ".join(text.split())
            if not t or len(t) < 3:
                continue
            # Header/footer band
            if y0 < HEADER_FOOTER_MARGIN or y1 > (page_h - HEADER_FOOTER_MARGIN):
                continue
            if DOI_RE.search(t):
                continue
            out.append((x0,y0,x1,y1,t))
        per_page[pno+1] = out

    # Yield as TextBlock
    for p, items in per_page.items():
        for (x0,y0,x1,y1,t) in items:
            yield TextBlock(page=p, bbox=(x0,y0,x1,y1), text=t)


def _flat_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "material": r.get("material",""),
        "property": r.get("property",""),
        "category": r.get("category",""),
        "value_min": r.get("value_min",""),
        "value_max": r.get("value_max",""),
        "unit": r.get("unit_original",""),
        "page": r.get("provenance",{}).get("page",""),
        "origin": r.get("origin",""),
        "citations": ";".join(r.get("citations") or []),
        "confidence": r.get("confidence",""),
        "hard_fail": ";".join(r.get("constraints",{}).get("hard_fail",[]) or []),
    }
