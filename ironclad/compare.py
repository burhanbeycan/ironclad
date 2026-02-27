"""
Comparison utilities.

Goal: produce a paper-centric comparison table that highlights:
- values measured in "this work"
- values cited from prior literature inside the same paper
- optional external baseline literature database values
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
import math


def build_comparison_table(records: List[Dict[str, Any]], baseline_records: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    baseline_records = baseline_records or []

    # index baseline by (material, property) and also property-only fallback
    base_by_key = defaultdict(list)
    base_by_prop = defaultdict(list)
    for r in baseline_records:
        k = (str(r.get("material","UNKNOWN")), str(r.get("property","unknown")))
        base_by_key[k].append(r)
        base_by_prop[str(r.get("property","unknown"))].append(r)

    groups = defaultdict(list)
    for r in records:
        k = (str(r.get("material","UNKNOWN")), str(r.get("property","unknown")))
        groups[k].append(r)

    rows: List[Dict[str, Any]] = []
    for (material, prop), recs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if prop == "unknown":
            continue

        this_recs = [r for r in recs if r.get("origin") == "this_work"]
        lit_recs = [r for r in recs if r.get("origin") == "literature"]

        base = base_by_key.get((material, prop), [])
        if not base:
            base = base_by_prop.get(prop, [])

        this_sum = summarize_numeric(this_recs)
        lit_sum = summarize_numeric(lit_recs)
        base_sum = summarize_numeric(base)

        novelty = classify_novelty(this_sum, lit_sum, base_sum)

        rows.append({
            "material": material,
            "property": prop,
            "category": _first_nonempty(recs, "category") or "Other",
            "this_work": this_sum["display"],
            "paper_cited_literature": lit_sum["display"],
            "external_baseline": base_sum["display"],
            "novelty_flag": novelty,
            "paper_citations": ", ".join(sorted(set(c for r in lit_recs for c in (r.get("citations") or []))))[:120],
        })

    return rows


def summarize_numeric(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarize a set of records as a range (min..max) in SI if possible.
    """
    if not recs:
        return {"display": "", "min": None, "max": None, "unit": None}

    # prefer SI values if available
    vals = []
    unit = None
    for r in recs:
        v = r.get("value_si_min")
        v2 = r.get("value_si_max")
        u = r.get("unit_si")
        if v is not None and u is not None:
            vals.append(float(v))
            if v2 is not None:
                vals.append(float(v2))
            unit = u
        else:
            v = r.get("value_min")
            v2 = r.get("value_max")
            u = r.get("unit_original")
            if v is not None and u is not None:
                vals.append(float(v))
                if v2 is not None:
                    vals.append(float(v2))
                unit = u

    if not vals:
        return {"display": "", "min": None, "max": None, "unit": None}

    vmin = min(vals); vmax = max(vals)
    if unit is None:
        return {"display": f"{_fmt(vmin)}–{_fmt(vmax)}", "min": vmin, "max": vmax, "unit": None}

    if abs(vmax - vmin) < 1e-12:
        disp = f"{_fmt(vmin)} {unit}"
    else:
        disp = f"{_fmt(vmin)}–{_fmt(vmax)} {unit}"
    return {"display": disp, "min": vmin, "max": vmax, "unit": unit}


def classify_novelty(this_sum: Dict[str, Any], lit_sum: Dict[str, Any], base_sum: Dict[str, Any]) -> str:
    """
    Very conservative novelty labeling.
    """
    if this_sum["min"] is None:
        return ""

    # If the paper itself already cites literature values for the same prop, it's usually "comparison" rather than new property
    if lit_sum["min"] is not None:
        # still allow "new regime" if far outside cited range
        if _outside_range(this_sum, lit_sum):
            return "new_regime_vs_cited_lit"
        return "compared_to_cited_lit"

    if base_sum["min"] is None:
        return "potentially_new_property"
    # compare to baseline range
    if _outside_range(this_sum, base_sum):
        return "new_regime_vs_baseline"
    return "within_baseline_range"


def _outside_range(a: Dict[str, Any], b: Dict[str, Any], tol: float = 0.05) -> bool:
    """
    Return True if range a lies outside range b by a relative tolerance.
    """
    if a["min"] is None or b["min"] is None:
        return False
    amin, amax = a["min"], a["max"]
    bmin, bmax = b["min"], b["max"]
    # expand baseline by tol
    span = max(1e-12, abs(bmax - bmin), abs(bmax), abs(bmin))
    bmin2 = bmin - tol * span
    bmax2 = bmax + tol * span
    return (amax < bmin2) or (amin > bmax2)


def _fmt(x: float) -> str:
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1e4 or ax < 1e-3:
        return f"{x:.3e}"
    if ax >= 100:
        return f"{x:.2f}"
    if ax >= 1:
        return f"{x:.3f}"
    return f"{x:.4f}"


def _first_nonempty(recs: List[Dict[str, Any]], key: str) -> Optional[str]:
    for r in recs:
        v = r.get(key)
        if v:
            return v
    return None
