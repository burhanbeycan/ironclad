"""ironclad.table_extract

Table → record extraction.

This is a heuristic layer that complements text extraction.
It is especially useful for:
- comparison tables with "This work" vs "Literature/Ref"
- polymer/electrolyte property tables (conductivity, Tg, modulus, etc.)

Key design choice
- In experimental chemistry papers, many tables report *unitless cells* because the
  unit is specified in the header. Therefore, this module supports parsing:
    (i) value+unit inside the cell, and
    (ii) numeric-only cells using the unit inferred from the header.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
import re

from .ontology import compile_property_regex, PROPERTY_CATEGORY, PROPERTY_DIMENSION
from .units import (
    parse_value_and_unit,
    parse_numeric_only,
    normalize_unit_str,
    to_si,
)
from .origin import classify_origin, detect_citations

_PROP_REGEX = compile_property_regex()

UNIT_IN_PARENS = re.compile(r"\(([^)]+)\)")
REF_WORD = re.compile(r"\b(ref\.?|reference|literature)\b", flags=re.IGNORECASE)
THIS_WORD = re.compile(r"\b(this\s+work|present\s+work)\b", flags=re.IGNORECASE)


def records_from_tables(tables, doc_id: str, default_material: str = "UNKNOWN") -> List[Dict[str, Any]]:
    """Convert extracted tables into normalized record dicts."""

    out: List[Dict[str, Any]] = []

    for t in tables:
        if not getattr(t, "rows", None):
            continue

        header = t.header or t.rows[0]
        header_text = " | ".join([h for h in header if h])
        caption_text = ""
        if getattr(t, "meta", None) and isinstance(t.meta, dict):
            caption_text = (t.meta.get("caption") or "")

        # Default origin assumption: caption-anchored tables in experimental sections
        # usually represent this paper's measurements unless explicitly marked as literature.
        table_default_origin = "this_work"
        if REF_WORD.search(caption_text) and not THIS_WORD.search(caption_text):
            table_default_origin = "literature"

        # Infer per-column roles
        col_props: List[Optional[str]] = []
        col_units: List[Optional[str]] = []
        ref_col_idx: Optional[int] = None
        thiswork_col_idx: Optional[int] = None

        for j, h in enumerate(header):
            prop = _infer_property(h)
            col_props.append(prop if prop != "unknown" else None)
            col_units.append(_infer_unit_from_header(h))
            if REF_WORD.search(h or ""):
                ref_col_idx = j
            if THIS_WORD.search(h or ""):
                thiswork_col_idx = j

        # Parse each row
        rows_iter = t.rows[1:] if t.header is None else t.rows
        for row in rows_iter:
            row_text = " | ".join(row)
            citations = detect_citations(row_text)

            # Start with a sane default (this_work), then override if evidence suggests literature.
            origin_hint = table_default_origin
            if citations:
                origin_hint = "literature"
            if THIS_WORD.search(row_text):
                origin_hint = "this_work"
            if ref_col_idx is not None and ref_col_idx < len(row):
                if detect_citations(row[ref_col_idx] or ""):
                    origin_hint = "literature"

            # Material guess: first non-empty cell if it looks like a token-like name, else default.
            material = _infer_material_from_row(row, default_material)

            # Extract each property column
            for j, prop in enumerate(col_props):
                if prop is None or j >= len(row):
                    continue

                cell = row[j] or ""
                vmin, vmax, unit = parse_value_and_unit(cell)

                # Many tables omit units in cells; fall back to numeric-only parsing + header unit.
                if vmin is None:
                    vmin, vmax = parse_numeric_only(cell)

                unit2 = unit or col_units[j]

                # Allow dimensionless properties without an explicit unit.
                dim_required = PROPERTY_DIMENSION.get(prop)
                if unit2 is None and dim_required == "dimensionless":
                    unit2 = "1"

                if vmin is None or unit2 is None:
                    continue

                unit_norm = normalize_unit_str(unit2)

                v_si_min, si_unit, dim = to_si(vmin, unit_norm)
                v_si_max, _, _ = to_si(vmax, unit_norm) if vmax is not None else (None, None, None)

                category = PROPERTY_CATEGORY.get(prop, "Other")

                # Column-specific overrides: if a column explicitly says "This work" or "Ref".
                origin2 = origin_hint
                if thiswork_col_idx is not None and j == thiswork_col_idx:
                    origin2 = "this_work"
                if ref_col_idx is not None and j == ref_col_idx:
                    origin2 = "literature"

                # Rationale from local row text
                origin_label, rationale = classify_origin(row_text)

                # Merge: keep strongest
                if origin2 != "unclear":
                    origin_label = origin2

                # If we still cannot normalize the unit, keep the record but mark it later via constraints.
                conf = 0.55
                conf += 0.20  # table structure already suggests factual data
                if si_unit is not None:
                    conf += 0.15
                if origin_label in {"this_work", "literature"}:
                    conf += 0.05
                conf = min(conf, 0.99)

                out.append(
                    {
                        "doc_id": doc_id,
                        "source_type": "table",
                        "material": material,
                        "property": prop,
                        "category": category,
                        "value_min": vmin,
                        "value_max": vmax,
                        "unit_original": unit_norm,
                        "value_si_min": v_si_min,
                        "value_si_max": v_si_max,
                        "unit_si": si_unit,
                        "dimension": dim,
                        "method": None,
                        "origin": origin_label,
                        "origin_rationale": rationale,
                        "citations": list(set(citations + (rationale.get("citations") or []))),
                        "confidence": round(conf, 3),
                        "provenance": {
                            "page": getattr(t, "page", None),
                            "bbox": getattr(t, "bbox", None),
                            "snippet": (caption_text + " | " + row_text)[:500],
                            "table_caption": caption_text[:200],
                        },
                        "normalization_traces": _make_norm_trace(vmin, vmax, unit_norm, v_si_min, v_si_max, si_unit, dim),
                    }
                )

    return out


def _infer_property(text: str) -> str:
    best = ("unknown", 0)
    for prop, pats in _PROP_REGEX.items():
        for pat in pats:
            m = pat.search(text or "")
            if m:
                score = len(m.group(0))
                if score > best[1]:
                    best = (prop, score)
    return best[0]


def _infer_unit_from_header(h: str) -> Optional[str]:
    if not h:
        return None
    m = UNIT_IN_PARENS.search(h)
    if m:
        cand = m.group(1).strip()
        if any(ch.isalpha() for ch in cand) and len(cand) <= 20:
            return cand
    return None


def _infer_material_from_row(row: List[str], default_material: str) -> str:
    for cell in row[:2]:
        c = (cell or "").strip()
        if 1 <= len(c) <= 25 and any(ch.isalpha() for ch in c):
            if not REF_WORD.search(c):
                return c
    return default_material or "UNKNOWN"


def _make_norm_trace(vmin, vmax, u, vmin_si, vmax_si, si_u, dim):
    if vmin_si is None or si_u is None:
        return []
    if vmin == vmax:
        return [{"from": f"{vmin} {u}", "to": f"{vmin_si} {si_u}", "dimension": dim}]
    return [{"from": f"{vmin}-{vmax} {u}", "to": f"{vmin_si}-{vmax_si} {si_u}", "dimension": dim}]
