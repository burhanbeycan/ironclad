"""
Table reconstruction (lightweight, layout-based).

Goal:
- detect "table-like" regions in PDFs without heavy dependencies.
- reconstruct row/column cell text using span x-positions.
- identify common comparison-table patterns: "This work" vs "Literature/Ref"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path

import statistics

from .pdf import get_page_lines, Line


@dataclass
class Table:
    page: int
    bbox: Tuple[float, float, float, float]
    rows: List[List[str]]
    column_x: List[float]
    header: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None


def _line_to_cells(line: Line) -> List[Tuple[float, str]]:
    spans = sorted(line.spans, key=lambda s: s.bbox[0])
    cells = []
    for sp in spans:
        txt = sp.text.strip()
        if not txt:
            continue
        cells.append((sp.bbox[0], txt))
    return cells


def _is_table_like(cells: List[Tuple[float, str]]) -> bool:
    if len(cells) < 3:
        return False
    # Heuristic: multiple short-ish tokens in aligned columns
    lengths = [len(t) for _, t in cells]
    if statistics.mean(lengths) > 80:
        return False
    return True


def extract_tables(doc) -> List[Table]:
    tables: List[Table] = []
    # Very simple segmentation: consecutive table-like lines grouped
    for p in range(1, len(doc) + 1):
        lines = get_page_lines(doc, p)
        groups: List[List[Line]] = []
        current: List[Line] = []
        for ln in lines:
            cells = _line_to_cells(ln)
            if _is_table_like(cells):
                current.append(ln)
            else:
                if len(current) >= 4:  # require at least 4 lines to reduce false positives
                    groups.append(current)
                current = []
        if len(current) >= 4:
            groups.append(current)

        for grp in groups:
            # Build row data and table bbox
            row_cells: List[List[Tuple[float, str]]] = [_line_to_cells(ln) for ln in grp]
            x0 = min(ln.bbox[0] for ln in grp); y0 = min(ln.bbox[1] for ln in grp)
            x1 = max(ln.bbox[2] for ln in grp); y1 = max(ln.bbox[3] for ln in grp)

            # Determine global columns by clustering x positions
            xs = sorted({round(x, 1) for row in row_cells for x, _ in row})
            # Merge close x positions
            col_x: List[float] = []
            for x in xs:
                if not col_x or abs(x - col_x[-1]) > 18:  # threshold in PDF points
                    col_x.append(x)
                else:
                    # keep earlier representative
                    continue

            # Convert each row to aligned cells
            rows: List[List[str]] = []
            for row in row_cells:
                out = [""] * len(col_x)
                for x, txt in row:
                    # assign to nearest column
                    j = min(range(len(col_x)), key=lambda k: abs(x - col_x[k]))
                    if out[j]:
                        out[j] += " " + txt
                    else:
                        out[j] = txt
                # Trim trailing empties
                while out and out[-1] == "":
                    out.pop()
                rows.append(out)

            header = rows[0] if rows else None
            meta = _infer_table_meta(header, rows)
            tables.append(Table(page=p, bbox=(x0, y0, x1, y1), rows=rows, column_x=col_x, header=header, meta=meta))
    return tables


def _infer_table_meta(header: Optional[List[str]], rows: List[List[str]]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    htxt = " ".join(header).lower() if header else ""
    # Detect common comparison table cues
    if "this work" in htxt or "present work" in htxt:
        meta["has_this_work_column"] = True
    if "literature" in htxt or "ref" in htxt or "reference" in htxt:
        meta["has_literature_column"] = True
    # If no explicit header cues, look for a ref-like column in body
    # (e.g., [12] or (12))
    ref_hits = 0
    for r in rows[:8]:
        for c in r:
            if "[" in c and "]" in c:
                ref_hits += 1
    if ref_hits >= 2:
        meta["likely_contains_citations"] = True
    return meta
