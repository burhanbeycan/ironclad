"""
Constraint checks for IRONCLAD proof-carrying records.

The goal is NOT to be an exhaustive chemistry rules engine, but to:
- prevent obviously invalid record construction
- create an auditable constraint report
"""

from __future__ import annotations

from typing import Dict, List, Any, Tuple
from collections import defaultdict

from .ontology import PROPERTY_DIMENSION
from .units import unit_lookup


def _dim_compatible(expected: str, observed: str) -> bool:
    """
    Small compatibility mapping.
    """
    if expected == observed:
        return True
    # Some acceptable equivalences
    if expected == "frequency" and observed in {"frequency"}:
        return True
    if expected == "dimensionless" and observed in {"dimensionless"}:
        return True
    # Allow % as dimensionless
    if expected == "dimensionless" and observed == "dimensionless":
        return True
    return False


def evaluate_constraints(records: List[Dict[str, Any]]) -> None:
    """
    In-place update:
      record["constraints"] = {"hard_pass": [...], "hard_fail": [...], "soft_warn": [...]}
    """
    for r in records:
        hard_pass: List[str] = []
        hard_fail: List[str] = []
        soft_warn: List[str] = []

        prop = r.get("property")
        unit = r.get("unit_original") or r.get("unit") or ""
        expected_dim = PROPERTY_DIMENSION.get(prop)

        if expected_dim:
            info = unit_lookup(unit) if unit else None
            if expected_dim == "dimensionless":
                # allow empty unit, %, or any explicitly dimensionless unit
                if unit in ("", None):
                    hard_pass.append("unit_dimension_compatible")
                elif info and info.get("dimension") == "dimensionless":
                    hard_pass.append("unit_dimension_compatible")
                elif unit == "%":
                    hard_pass.append("unit_dimension_compatible")
                else:
                    soft_warn.append(f"unit_unexpected_for_dimensionless:{unit}")
            else:
                if not info:
                    hard_fail.append("unit_unknown")
                else:
                    observed_dim = info.get("dimension")
                    if _dim_compatible(expected_dim, observed_dim):
                        hard_pass.append("unit_dimension_compatible")
                    else:
                        hard_fail.append(f"unit_dimension_mismatch:{expected_dim}!={observed_dim}")

        # Polymer cross-record constraints will be evaluated later
        r["constraints"] = {"hard_pass": hard_pass, "hard_fail": hard_fail, "soft_warn": soft_warn}

    _polymer_cross_constraints(records)


def _polymer_cross_constraints(records: List[Dict[str, Any]]) -> None:
    """
    Cross-record constraints for polymers:
      Mw >= Mn
      dispersity >= 1
    """
    by_material: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_material[str(r.get("material", "UNKNOWN"))].append(r)

    for mat, recs in by_material.items():
        # Collect Mn/Mw
        mn = [r for r in recs if r.get("property") == "number_average_molecular_weight"]
        mw = [r for r in recs if r.get("property") == "weight_average_molecular_weight"]
        dispers = [r for r in recs if r.get("property") == "dispersity"]

        # Compare Mw vs Mn if both exist (use SI values if present)
        if mn and mw:
            # pick max-confidence record of each
            mn_best = sorted(mn, key=lambda x: x.get("confidence", 0.0), reverse=True)[0]
            mw_best = sorted(mw, key=lambda x: x.get("confidence", 0.0), reverse=True)[0]
            mn_val = mn_best.get("value_si_min") or mn_best.get("value_min")
            mw_val = mw_best.get("value_si_min") or mw_best.get("value_min")
            if mn_val is not None and mw_val is not None:
                if mw_val + 1e-12 >= mn_val:
                    mn_best["constraints"]["hard_pass"].append("mw_ge_mn_consistent")
                    mw_best["constraints"]["hard_pass"].append("mw_ge_mn_consistent")
                else:
                    mn_best["constraints"]["soft_warn"].append("mw_lt_mn_anomaly")
                    mw_best["constraints"]["soft_warn"].append("mw_lt_mn_anomaly")

        # Dispersity >= 1
        for r in dispers:
            v = r.get("value_min")
            if v is not None and v < 1.0:
                r["constraints"]["soft_warn"].append("dispersity_lt_1_anomaly")
