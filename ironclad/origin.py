"""
Origin classification: did the extracted value correspond to "this work" or cited literature?

We treat this as a *document rhetoric* / provenance classification task. In a paper, numbers appear in at least
three rhetorical roles:
  (i) this_work: values measured/reported by the authors
 (ii) literature: values quoted from prior work (usually with citations)
(iii) unclear: ambiguous snippets (no explicit cues)

This module provides a deterministic, auditable classifier using:
  - explicit citation markers
  - rhetorical cue verbs/phrases
  - lightweight section cues (optional)
"""

from __future__ import annotations

import re
from typing import List, Tuple, Dict, Any, Optional


# Numeric citation styles: [12], [12,13], [12-15]
CIT_NUM_BRACKETS = re.compile(r"\[\s*\d+(?:\s*[-,]\s*\d+)*\s*\]")
# Parenthetical numeric citations: (12) or (12,13)
CIT_NUM_PARENS = re.compile(r"\(\s*\d+(?:\s*[-,]\s*\d+)*\s*\)")
# Author-year citations: (Smith et al., 2020) / (Smith, 2020)
CIT_AUTHOR_YEAR = re.compile(r"\(\s*[A-Z][A-Za-z\-]+(?:\s+et\s+al\.)?(?:,\s*)?\d{4}\s*\)")
# "Ref. 12", "Refs. 12-14"
CIT_REF = re.compile(r"\bRefs?\.?\s*\d+(?:\s*[-,]\s*\d+)*", flags=re.IGNORECASE)

# Rhetorical cues
LIT_CUES = re.compile(
    r"\b(previously|reported|literature|in\s+the\s+literature|has\s+been\s+reported|as\s+reported|according\s+to|"
    r"as\s+shown\s+in|consistent\s+with|similar\s+to|in\s+Ref\.?|in\s+Refs\.?)\b",
    flags=re.IGNORECASE,
)
THISWORK_CUES = re.compile(
    r"\b(this\s+work|in\s+this\s+work|herein|in\s+this\s+study|we\s+report|we\s+measured|we\s+observe|"
    r"our\s+results|the\s+present\s+work|this\s+study\s+demonstrates)\b",
    flags=re.IGNORECASE,
)

# Section priors (optional)
LIT_SECTIONS = {"introduction", "background", "related work", "literature review"}
THIS_SECTIONS = {"experimental", "materials and methods", "methods", "results", "discussion", "results and discussion"}


def detect_citations(text: str) -> List[str]:
    t = text or ""
    cits: List[str] = []
    for pat in (CIT_NUM_BRACKETS, CIT_NUM_PARENS, CIT_AUTHOR_YEAR, CIT_REF):
        cits.extend(pat.findall(t))
    # Deduplicate, keep order
    seen = set()
    out = []
    for c in cits:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def classify_origin(text: str, section_hint: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (origin_label, rationale_dict)
    origin_label ∈ {"this_work","literature","unclear","mixed"}

    mixed: both explicit this-work cues and literature cues/citations are present.
    """
    t = text or ""
    t_norm = " ".join(t.split())

    citations = detect_citations(t_norm)
    has_cit = len(citations) > 0
    has_lit_cue = bool(LIT_CUES.search(t_norm))
    has_this_cue = bool(THISWORK_CUES.search(t_norm))

    # Section prior
    section_vote = None
    if section_hint:
        s = section_hint.strip().lower()
        if s in LIT_SECTIONS:
            section_vote = "literature"
        elif s in THIS_SECTIONS:
            section_vote = "this_work"

    # Decision logic (auditable)
    if has_this_cue and (has_cit or has_lit_cue):
        label = "mixed"
    elif has_cit or has_lit_cue:
        label = "literature"
    elif has_this_cue:
        label = "this_work"
    else:
        # fall back to section prior if any
        label = section_vote or "unclear"

    rationale = {
        "citations": citations,
        "has_citation": has_cit,
        "has_lit_cue": has_lit_cue,
        "has_thiswork_cue": has_this_cue,
        "section_hint": section_hint,
        "section_vote": section_vote,
    }
    return label, rationale


def classify_origin_near_value(full_text: str, start: int, end: int, section_hint: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """
    A more granular origin classifier for a specific numeric mention located at [start:end].

    Key heuristic:
    - If a citation marker occurs *immediately after* the value (within ~40 chars), treat as literature.
    - If literature cue verbs appear immediately before the value, treat as literature.
    - Otherwise fall back to the generic classify_origin(window).
    """
    t = full_text or ""
    pre = t[max(0, start-80):start]
    post = t[end:min(len(t), end+80)]
    post_near = t[end:min(len(t), end+45)]
    pre_near = t[max(0, start-45):start]

    post_cits = detect_citations(post_near)
    pre_cits = detect_citations(pre_near)
    has_post_cit = bool(post_cits)
    has_pre_cit = bool(pre_cits)

    has_lit_near = bool(LIT_CUES.search(pre_near)) or bool(LIT_CUES.search(post_near))
    has_this_near = bool(THISWORK_CUES.search(pre)) or bool(THISWORK_CUES.search(pre_near))

    window = (pre + t[start:end] + post)
    label, rationale = classify_origin(window, section_hint=section_hint)
    rationale["proximity"] = {
        "pre_near": pre_near.strip(),
        "post_near": post_near.strip(),
        "post_citations": post_cits,
        "pre_citations": pre_cits,
        "has_lit_cue_near": has_lit_near,
        "has_thiswork_cue_near": has_this_near,
    }

    # Override with proximity rule
    if has_post_cit or (has_pre_cit and has_lit_near):
        label = "literature"
    elif has_this_near and not has_post_cit and not has_lit_near:
        label = "this_work"

    return label, rationale
