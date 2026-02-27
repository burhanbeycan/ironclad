"""ironclad.units

Unit parsing + SI normalization utilities.

Design principles
- Pragmatic rather than exhaustive (extend UNIT_DB as new domains are added).
- Deterministic and auditable: every conversion is explicit (factor/offset).
- Robust to common PDF text-extraction artifacts:
    * spaced thousands ("67 732")
    * broken scientific notation ("2.88 × 1010" meaning 2.88×10^10)
    * typography variants (µ/μ, −/–/—, middots)

Notes
- "SI" here means the canonical unit we normalize to *per dimension class*.
  For some chemistry dimensions (e.g., molecular weight in g/mol), the target
  unit is not strictly SI but is the standard reporting unit.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple, Dict, Any

# ---------
# Unit table
# ---------
# Each unit maps to:
#  - dimension class
#  - SI_unit: canonical target unit for the dimension
#  - factor: multiply value by factor to get SI (after offset if applicable)
#  - offset: add offset before factor (for temperatures, e.g., °C -> K: (v + 273.15))
UNIT_DB: Dict[str, Dict[str, Any]] = {
    # Temperature
    "K": {"dimension": "temperature", "SI_unit": "K", "factor": 1.0, "offset": 0.0},
    "°C": {"dimension": "temperature", "SI_unit": "K", "factor": 1.0, "offset": 273.15},
    "C": {"dimension": "temperature", "SI_unit": "K", "factor": 1.0, "offset": 273.15},

    # Pressure / modulus
    "Pa": {"dimension": "pressure", "SI_unit": "Pa", "factor": 1.0, "offset": 0.0},
    "kPa": {"dimension": "pressure", "SI_unit": "Pa", "factor": 1e3, "offset": 0.0},
    "MPa": {"dimension": "pressure", "SI_unit": "Pa", "factor": 1e6, "offset": 0.0},
    "GPa": {"dimension": "pressure", "SI_unit": "Pa", "factor": 1e9, "offset": 0.0},

    # Viscosity
    "Pa·s": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1.0, "offset": 0.0},
    "Pa*s": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1.0, "offset": 0.0},
    "mPa·s": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1e-3, "offset": 0.0},
    "mPa*s": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1e-3, "offset": 0.0},
    "cP": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1e-3, "offset": 0.0},
    "cPs": {"dimension": "viscosity", "SI_unit": "Pa·s", "factor": 1e-3, "offset": 0.0},

    # Conductivity
    "S/m": {"dimension": "conductivity", "SI_unit": "S/m", "factor": 1.0, "offset": 0.0},
    "S·m−1": {"dimension": "conductivity", "SI_unit": "S/m", "factor": 1.0, "offset": 0.0},
    "S/cm": {"dimension": "conductivity", "SI_unit": "S/m", "factor": 100.0, "offset": 0.0},  # 1 S/cm = 100 S/m
    "mS/cm": {"dimension": "conductivity", "SI_unit": "S/m", "factor": 0.1, "offset": 0.0},  # 1 mS/cm = 0.1 S/m
    "µS/cm": {"dimension": "conductivity", "SI_unit": "S/m", "factor": 1e-4, "offset": 0.0},

    # Frequency
    "Hz": {"dimension": "frequency", "SI_unit": "Hz", "factor": 1.0, "offset": 0.0},
    "kHz": {"dimension": "frequency", "SI_unit": "Hz", "factor": 1e3, "offset": 0.0},
    "MHz": {"dimension": "frequency", "SI_unit": "Hz", "factor": 1e6, "offset": 0.0},
    "GHz": {"dimension": "frequency", "SI_unit": "Hz", "factor": 1e9, "offset": 0.0},
    "rad/s": {"dimension": "frequency", "SI_unit": "rad/s", "factor": 1.0, "offset": 0.0},

    # Voltage
    "V": {"dimension": "voltage", "SI_unit": "V", "factor": 1.0, "offset": 0.0},
    "kV": {"dimension": "voltage", "SI_unit": "V", "factor": 1e3, "offset": 0.0},

    # Resistance
    "Ω": {"dimension": "resistance", "SI_unit": "Ω", "factor": 1.0, "offset": 0.0},
    "kΩ": {"dimension": "resistance", "SI_unit": "Ω", "factor": 1e3, "offset": 0.0},
    "MΩ": {"dimension": "resistance", "SI_unit": "Ω", "factor": 1e6, "offset": 0.0},

    # Energy
    "J": {"dimension": "energy", "SI_unit": "J", "factor": 1.0, "offset": 0.0},
    "J/mol": {"dimension": "energy", "SI_unit": "J/mol", "factor": 1.0, "offset": 0.0},
    "kJ/mol": {"dimension": "energy", "SI_unit": "J/mol", "factor": 1e3, "offset": 0.0},
    "eV": {"dimension": "energy", "SI_unit": "J", "factor": 1.602176634e-19, "offset": 0.0},
    "meV": {"dimension": "energy", "SI_unit": "J", "factor": 1.602176634e-22, "offset": 0.0},

    # Molecular weight (canonical in g/mol)
    "g/mol": {"dimension": "molecular_weight", "SI_unit": "g/mol", "factor": 1.0, "offset": 0.0},
    "kg/mol": {"dimension": "molecular_weight", "SI_unit": "g/mol", "factor": 1e3, "offset": 0.0},
    "Da": {"dimension": "molecular_weight", "SI_unit": "g/mol", "factor": 1.0, "offset": 0.0},  # 1 Da ≈ 1 g/mol
    "kDa": {"dimension": "molecular_weight", "SI_unit": "g/mol", "factor": 1e3, "offset": 0.0},

    # Time
    "s": {"dimension": "time", "SI_unit": "s", "factor": 1.0, "offset": 0.0},
    "min": {"dimension": "time", "SI_unit": "s", "factor": 60.0, "offset": 0.0},
    "h": {"dimension": "time", "SI_unit": "s", "factor": 3600.0, "offset": 0.0},

    # Rate
    "s−1": {"dimension": "rate", "SI_unit": "s^-1", "factor": 1.0, "offset": 0.0},
    "s^-1": {"dimension": "rate", "SI_unit": "s^-1", "factor": 1.0, "offset": 0.0},
    "min−1": {"dimension": "rate", "SI_unit": "s^-1", "factor": 1/60.0, "offset": 0.0},
    "min^-1": {"dimension": "rate", "SI_unit": "s^-1", "factor": 1/60.0, "offset": 0.0},

    # Concentration (molar)
    "M": {"dimension": "concentration", "SI_unit": "mol/L", "factor": 1.0, "offset": 0.0},
    "mM": {"dimension": "concentration", "SI_unit": "mol/L", "factor": 1e-3, "offset": 0.0},
    "mol/L": {"dimension": "concentration", "SI_unit": "mol/L", "factor": 1.0, "offset": 0.0},
    "mol·L−1": {"dimension": "concentration", "SI_unit": "mol/L", "factor": 1.0, "offset": 0.0},

    # Length (useful for morphology/process settings)
    "m": {"dimension": "length", "SI_unit": "m", "factor": 1.0, "offset": 0.0},
    "cm": {"dimension": "length", "SI_unit": "m", "factor": 1e-2, "offset": 0.0},
    "mm": {"dimension": "length", "SI_unit": "m", "factor": 1e-3, "offset": 0.0},
    "µm": {"dimension": "length", "SI_unit": "m", "factor": 1e-6, "offset": 0.0},
    "um": {"dimension": "length", "SI_unit": "m", "factor": 1e-6, "offset": 0.0},
    "nm": {"dimension": "length", "SI_unit": "m", "factor": 1e-9, "offset": 0.0},

    # Process / misc
    "rpm": {"dimension": "rotation_rate", "SI_unit": "rpm", "factor": 1.0, "offset": 0.0},
    "W": {"dimension": "power", "SI_unit": "W", "factor": 1.0, "offset": 0.0},
    "%": {"dimension": "dimensionless", "SI_unit": "%", "factor": 1.0, "offset": 0.0},
    "1": {"dimension": "dimensionless", "SI_unit": "1", "factor": 1.0, "offset": 0.0},
}


# Normalize a few typography variants (minus signs, middots, superscripts)
MINUS_CHARS = "−–—"  # minus/en-dash/em-dash


def normalize_unit_str(u: str) -> str:
    u = (u or "").strip()

    # micro symbol normalization
    u = u.replace("μ", "µ")

    for mc in MINUS_CHARS:
        u = u.replace(mc, "−")

    u = u.replace(" ", "")

    # Common equivalences
    u = u.replace("S·cm−1", "S/cm")
    u = u.replace("S·m−1", "S/m")
    u = u.replace("Pa.s", "Pa·s")
    u = u.replace("mPa.s", "mPa·s")
    u = u.replace("Ohm", "Ω").replace("ohm", "Ω")

    # Viscosity shorthand in many experimental papers
    if u.lower() == "cps":
        u = "cP"

    # Concentration typography
    if u == "molL−1" or u == "molL-1":
        u = "mol/L"

    return u


def unit_lookup(u: str) -> Optional[Dict[str, Any]]:
    u_norm = normalize_unit_str(u)
    if u_norm in UNIT_DB:
        return UNIT_DB[u_norm]
    if u in UNIT_DB:
        return UNIT_DB[u]
    return None


def to_si(value: float, unit: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """Convert to canonical unit for the unit's dimension class."""
    info = unit_lookup(unit)
    if not info:
        return None, None, None
    dim = info["dimension"]
    si_unit = info["SI_unit"]
    offset = float(info.get("offset", 0.0))
    factor = float(info.get("factor", 1.0))
    v_si = (value + offset) * factor
    return v_si, si_unit, dim


# ------------------------
# Numeric parsing helpers
# ------------------------

# Captures:
#  - value: decimal/scientific (supports ×10^, ×10, and e/E)
#  - unit: common patterns (letters, %, /, ·, −, ^, Ω)
VALUE_UNIT_RE = re.compile(
    r"(?P<val>[+-]?\d+(?:\.\d+)?(?:\s*×\s*10\s*(?:\^)?\s*[+-]?\d+)?(?:[eE][+-]?\d+)?)\s*(?P<unit>[A-Za-z°Ω%μµ·\*/\-\−\^0-9]+)",
    flags=re.UNICODE,
)

RANGE_RE = re.compile(
    r"(?P<min>[+-]?\d+(?:\.\d+)?)\s*[-–—−]\s*(?P<max>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z°Ω%μµ·\*/\-\−\^0-9]+)?"
)

NUM_TOKEN_RE = re.compile(
    r"[+-]?(?:\d{1,3}(?:[\s,]\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s*×\s*10\s*(?:\^)?\s*[+-]?\d+)?"
    r"(?:[eE][+-]?\d+)?"
)


def parse_float(s: str) -> Optional[float]:
    """Parse a float from PDF-extracted text.

    Handles artifacts such as:
    - thousands separated by spaces: "67 732" -> 67732
    - broken scientific notation: "2.88 × 1010" -> 2.88e10
    - unicode minus: "−" -> "-"
    """
    if s is None:
        return None

    s = str(s).strip()
    if not s:
        return None

    # normalize unicode minus
    s = s.replace("−", "-")

    # remove thousands separators (spaces or commas between digits)
    s = re.sub(r"(?<=\d)[\s,](?=\d{3}\b)", "", s)

    # Handle "× 10^n" and the common PDF artifact "× 10n" (e.g., "× 1010")
    m = re.search(r"×\s*10\s*(?:\^)?\s*([+-]?\d+)", s)
    if m:
        try:
            exp = int(m.group(1))
            base_txt = re.sub(r"×\s*10\s*(?:\^)?\s*[+-]?\d+", "", s).strip()
            base = float(base_txt) if base_txt else 1.0
            return base * (10 ** exp)
        except Exception:
            return None

    # Fall back to Python float (handles e/E)
    try:
        return float(s)
    except Exception:
        return None


def parse_numeric_only(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Parse a numeric value (or range) with no explicit unit."""
    t = " ".join((text or "").split())
    m = RANGE_RE.search(t)
    if m and m.group("unit") is None:
        vmin = parse_float(m.group("min"))
        vmax = parse_float(m.group("max"))
        return vmin, vmax

    m2 = NUM_TOKEN_RE.search(t)
    if m2:
        v = parse_float(m2.group(0))
        return v, v

    return None, None


def parse_value_and_unit(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Return (min, max, unit). For single value, min==max."""
    t = " ".join((text or "").split())

    # Range with optional unit
    m = RANGE_RE.search(t)
    if m and m.group("unit"):
        vmin = parse_float(m.group("min"))
        vmax = parse_float(m.group("max"))
        unit = (m.group("unit") or "").strip()
        # Guard: digits-only "units" are almost always spaced-thousands artifacts.
        if unit and unit.isdigit():
            vmin2, vmax2 = parse_numeric_only(t)
            return vmin2, vmax2, None
        if vmin is not None and vmax is not None:
            return vmin, vmax, unit

    m2 = VALUE_UNIT_RE.search(t)
    if m2:
        v = parse_float(m2.group(0))
        unit = (m2.group("unit") or "").strip()
        if unit and unit.isdigit():
            vmin2, vmax2 = parse_numeric_only(t)
            return vmin2, vmax2, None
        if v is not None:
            return v, v, unit

    return None, None, None
