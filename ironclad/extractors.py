"""
Candidate extraction (text-focused).

This module turns layout blocks into candidate "records" that later
get filtered / constrained / categorized.

For v3 we add:
- origin classification ("this work" vs "literature")
- domain ontology mapping (rheology + electrolytes)
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import re

from .ontology import compile_property_regex, compile_method_regex, PROPERTY_CATEGORY
from .units import parse_value_and_unit, to_si, normalize_unit_str, UNIT_DB
from .origin import classify_origin, classify_origin_near_value

_PROP_REGEX = compile_property_regex()
_METHOD_REGEX = compile_method_regex()

# Lightweight material lexicon (extend as needed)
MATERIAL_LEXICON = [
    "PEO", "PEG", "PVDF", "PAN", "PMMA", "PS", "PLA", "PCL", "PVA", "PAA",
    "LiTFSI", "LiPF6", "LiFSI", "LiClO4", "LiBF4",
    "ZnO", "SiO2", "Al2O3", "TiO2",
]

MAT_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in MATERIAL_LEXICON) + r")\b")


def infer_document_material(text: str) -> Optional[str]:
    """
    Infer a 'default material' for the document by frequency.
    """
    hits = MAT_RE.findall(text or "")
    if not hits:
        return None
    # choose most common
    counts = {}
    for h in hits:
        counts[h] = counts.get(h, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]


def extract_from_textblock(tb, doc_id: str, default_material: str = "UNKNOWN") -> List[Dict[str, Any]]:
    """
    Extract candidate records from a single text block.
    """
    text = tb.text
    records: List[Dict[str, Any]] = []

    # Identify methods mentioned in block
    method = None
    for m in _METHOD_REGEX:
        if m.search(text):
            method = m.pattern.strip("\\b")
            break

    # Determine local material mention if any
    mat = None
    m2 = MAT_RE.search(text)
    if m2:
        mat = m2.group(1)
    material = mat or default_material or "UNKNOWN"

    # Extract multiple (value, unit) mentions by scanning the text with a sliding regex.
    # We keep it conservative: only keep mentions with a known unit OR strong property cue nearby.
    idx = 0
    # We'll scan using a broad regex and then use parse_value_and_unit on each matched snippet.
    token_re = re.compile(r"([+-]?\d+(?:\.\d+)?(?:\s*[-–—−]\s*\d+(?:\.\d+)?)?)\s*[A-Za-z°Ω%μµ·\*/\-\−\^0-9]{1,12}")
    for m in token_re.finditer(text):
        span = text[max(0, m.start()-80):min(len(text), m.end()+80)]
        vmin, vmax, unit = parse_value_and_unit(span)
        if unit is None or vmin is None:
            continue

        unit_norm = normalize_unit_str(unit)
        # Determine property by searching within the local window
        prop = _infer_property(span)
        category = PROPERTY_CATEGORY.get(prop, "Other") if prop != "unknown" else "Other"

        # Drop obvious narrative false positives when property is unknown and unit is not recognized.
        if prop == "unknown" and unit_norm not in UNIT_DB:
            if re.fullmatch(r"[A-Za-z]{5,}", unit_norm):
                continue

        # Conservative filtering: ignore ultra-short ambiguous units unless property is known
        if prop == "unknown" and unit_norm in {"m", "M", "s", "h"}:
            continue

        v_si_min, si_unit, dim = to_si(vmin, unit_norm) if vmin is not None else (None, None, None)
        v_si_max, _, _ = to_si(vmax, unit_norm) if vmax is not None else (None, None, None)

        origin, rationale = classify_origin_near_value(text, m.start(), m.end())

        # Confidence heuristic
        conf = 0.50
        if prop != "unknown":
            conf += 0.20
        if si_unit is not None:
            conf += 0.15
        if origin in {"this_work", "literature"}:
            conf += 0.05
        conf = min(conf, 0.99)

        rec = {
            "doc_id": doc_id,
            "source_type": "text",
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
            "method": method,
            "origin": origin,
            "origin_rationale": rationale,
            "citations": rationale.get("citations", []),
            "confidence": round(conf, 3),
            "provenance": {
                "page": tb.page,
                "bbox": tb.bbox,
                "snippet": " ".join(span.split()),
            },
            "normalization_traces": _make_norm_trace(vmin, vmax, unit_norm, v_si_min, v_si_max, si_unit, dim),
        }
        records.append(rec)

    return records


def _infer_property(context: str) -> str:
    ctx = context or ""
    # Try to find the most specific property by matching patterns; prefer longer matched strings
    best = ("unknown", 0)
    for prop, pats in _PROP_REGEX.items():
        for pat in pats:
            m = pat.search(ctx)
            if m:
                score = len(m.group(0))
                if score > best[1]:
                    best = (prop, score)
    return best[0]


def _make_norm_trace(vmin, vmax, u, vmin_si, vmax_si, si_u, dim):
    if vmin_si is None or si_u is None:
        return []
    if vmin == vmax:
        return [{
            "from": f"{vmin} {u}",
            "to": f"{vmin_si} {si_u}",
            "dimension": dim,
        }]
    return [{
        "from": f"{vmin}-{vmax} {u}",
        "to": f"{vmin_si}-{vmax_si} {si_u}",
        "dimension": dim,
    }]
