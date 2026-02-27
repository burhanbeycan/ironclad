"""
Ontology-lite resources for IRONCLAD (polymer rheology + battery electrolytes).

This file intentionally keeps a compact, editable knowledge base:
- property canonicalization
- category assignment
- expected dimension class (for unit compatibility checks)
- method lexicon (for optional method extraction)
"""

from __future__ import annotations

import re
from typing import Dict, List, Pattern


# -----------------------------
# Property ontology (canonical)
# -----------------------------

# Each canonical property maps to list of regex patterns (case-insensitive)
PROPERTY_PATTERNS: Dict[str, List[str]] = {
    # Electrolytes / battery
    "ionic_conductivity": [
        r"\bionic conductivity\b",
        r"\bconductivity\b",
        r"\bσ\b", r"\bsigma\b",
    ],
    "li_transference_number": [
        r"\btransference number\b",
        r"\bt\+?\b", r"\bt\+?_(?:Li)?\b",
        r"\btLi\+?\b", r"\bt\s*_\s*Li\+?\b",
    ],
    "electrochemical_stability_window": [
        r"\bstability window\b",
        r"\belectrochemical stability\b",
        r"\bESW\b",
    ],
    "activation_energy": [
        r"\bactivation energy\b",
        r"\bE_a\b",
    ],
    "interfacial_resistance": [
        r"\binterfacial resistance\b",
        r"\bR_ct\b", r"\bcharge transfer resistance\b",
    ],
    "concentration": [
        r"\bconcentration\b",
        r"\bmolarity\b",
    ],


    # Polymer thermal
    "glass_transition_temperature": [
        r"\bglass transition temperature\b",
        r"\bglass transition\b",
        r"\bTg\b", r"\bT_g\b",
    ],
    "melting_temperature": [
        r"\bmelting temperature\b",
        r"\bTm\b", r"\bT_m\b",
    ],

    # Polymer molecular weights
    "number_average_molecular_weight": [
        r"\bnumber[-\s]average molecular weight\b",
        r"\bM_n\b", r"\bMn\b",
    ],
    "weight_average_molecular_weight": [
        r"\bweight[-\s]average molecular weight\b",
        r"\bM_w\b", r"\bMw\b",
    ],
    "z_average_molecular_weight": [
        r"\bz[-\s]average molecular weight\b",
        r"\bM_z\b", r"\bMz\b",
    ],
    "viscosity_average_molecular_weight": [
        r"\bviscosity[-\s]average molecular weight\b",
        r"\bM_v\b", r"\bMv\b",
    ],
    "dispersity": [
        r"\bdispersity\b",
        r"\bpolydispersity\b",
        r"\bĐ\b", r"\bPDI\b",
    ],

    # Polymer mechanical + rheology
    "youngs_modulus": [
        r"\byoung'?s modulus\b",
        r"\bmodulus\b",
        r"\bE\b",
    ],
    "storage_modulus": [
        r"\bstorage modulus\b",
        r"\bG'\b",
        r"\bG\s*′\b",
    ],
    "loss_modulus": [
        r"\bloss modulus\b",
        r"\bG''\b",
        r"\bG\s*″\b",
    ],
    "complex_modulus": [
        r"\bcomplex modulus\b",
        r"\bG\*\b",
    ],
    "viscosity": [
        r"\bviscosity\b",
        r"\bη\b", r"\beta\b",
    ],
    "complex_viscosity": [
        r"\bcomplex viscosity\b",
        r"\b\|η\*\|\b", r"\bη\*\b",
    ],
    "zero_shear_viscosity": [
        r"\bzero[-\s]shear viscosity\b",
        r"\bη_0\b", r"\beta_0\b",
    ],
    "shear_rate": [
        r"\bshear rate\b",
        r"\bγ̇\b", r"\bgamma dot\b",
    ],
    "frequency": [
        r"\bfrequency\b",
        r"\bω\b", r"\bangular frequency\b",
    ],
    "strain_rate": [
        r"\bstrain rate\b",
    ],
    "stress": [
        r"\bstress\b",
        r"\bσ\b",
    ],
    "strain": [
        r"\bstrain\b",
        r"\bε\b",
    ],
}

PROPERTY_CATEGORY: Dict[str, str] = {
    # Electrolytes / battery
    "ionic_conductivity": "Electrochemical",
    "li_transference_number": "Electrochemical",
    "electrochemical_stability_window": "Electrochemical",
    "activation_energy": "Electrochemical",
    "interfacial_resistance": "Electrochemical",

    # Thermal
    "glass_transition_temperature": "Thermal",
    "melting_temperature": "Thermal",

    # Polymer chemistry / mol wt
    "concentration": "Chemical",
    "number_average_molecular_weight": "Chemical",
    "weight_average_molecular_weight": "Chemical",
    "z_average_molecular_weight": "Chemical",
    "viscosity_average_molecular_weight": "Chemical",
    "dispersity": "Chemical",

    # Mechanical / rheology
    "youngs_modulus": "Mechanical",
    "storage_modulus": "Rheology",
    "loss_modulus": "Rheology",
    "complex_modulus": "Rheology",
    "viscosity": "Rheology",
    "complex_viscosity": "Rheology",
    "zero_shear_viscosity": "Rheology",
    "shear_rate": "Rheology",
    "frequency": "Rheology",
    "strain_rate": "Mechanical",
    "stress": "Mechanical",
    "strain": "Mechanical",
}

# Dimension classes are used for unit compatibility checks
PROPERTY_DIMENSION: Dict[str, str] = {
    # Electrochemical
    "ionic_conductivity": "conductivity",
    "li_transference_number": "dimensionless",
    "electrochemical_stability_window": "voltage",
    "activation_energy": "energy",
    "interfacial_resistance": "resistance",

    # Thermal
    "glass_transition_temperature": "temperature",
    "melting_temperature": "temperature",

    # Formulation
    "concentration": "concentration",

    # Polymer molecular weights
    "number_average_molecular_weight": "molecular_weight",
    "weight_average_molecular_weight": "molecular_weight",
    "z_average_molecular_weight": "molecular_weight",
    "viscosity_average_molecular_weight": "molecular_weight",
    "dispersity": "dimensionless",

    # Mechanical + rheology
    "youngs_modulus": "pressure",
    "storage_modulus": "pressure",
    "loss_modulus": "pressure",
    "complex_modulus": "pressure",

    "viscosity": "viscosity",
    "complex_viscosity": "viscosity",
    "zero_shear_viscosity": "viscosity",

    "shear_rate": "rate",
    "frequency": "frequency",
    "strain_rate": "rate",
    "stress": "pressure",
    "strain": "dimensionless",
}


# -----------------------------
# Method lexicon (expandable)
# -----------------------------
METHOD_PATTERNS: List[str] = [
    # Thermal / polymers
    r"\bDSC\b", r"\bDMA\b", r"\bTGA\b",
    r"\bGPC\b", r"\bSEC\b",
    # Electrochemistry
    r"\bEIS\b", r"\belectrochemical impedance\b", r"\bLSV\b", r"\bCV\b",
    # Spectroscopy / structure
    r"\bNMR\b", r"\bFTIR\b", r"\bRaman\b",
    r"\bXRD\b", r"\bSEM\b", r"\bTEM\b", r"\bAFM\b",
    # Rheology
    r"\brheometer\b", r"\brheology\b", r"\boscilatory shear\b", r"\boss?cillatory\b",
]


def compile_property_regex() -> Dict[str, List[Pattern]]:
    out: Dict[str, List[Pattern]] = {}
    for k, pats in PROPERTY_PATTERNS.items():
        out[k] = [re.compile(p, flags=re.IGNORECASE) for p in pats]
    return out

def compile_method_regex() -> List[Pattern]:
    return [re.compile(p, flags=re.IGNORECASE) for p in METHOD_PATTERNS]
