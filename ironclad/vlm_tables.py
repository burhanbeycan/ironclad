"""ironclad.vlm_tables

Vision-Language Model (VLM) table parsing *plugin*.

This module is intentionally optional. IRONCLAD's default philosophy is
deterministic extraction with provenance. When a paper embeds a table as an
image, OCR can recover many tables, but it struggles with:
  - merged cells / multi-line headers
  - super/subscript typography
  - dense comparison tables with units in the header

A VLM can sometimes do better, especially when asked to output a structured CSV
or JSON. However, VLM calls require:
  - an API key (or a local VLM runtime);
  - network access (for hosted models);
  - careful prompt + post-validation.

Accordingly, this file provides a minimal, guarded implementation for the
OpenAI Python SDK (v1). If the dependency is not installed or the API key is
missing, the parser raises a clear error and the caller can fall back to OCR.

You can implement additional providers by following the same interface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import base64
import json
import os


def openai_vlm_available() -> bool:
    try:
        from openai import OpenAI  # noqa: F401
        return True
    except Exception:
        return False


def parse_table_with_openai(
    image_path: str,
    *,
    caption: str = "",
    model: str = "gpt-4o-mini",
    max_tokens: int = 800,
) -> Tuple[Optional[List[str]], List[List[str]], Dict[str, Any]]:
    """Parse a table image using an OpenAI vision-capable model.

    The model is asked to return a strict JSON object:
        {"header": [...], "rows": [[...], ...]}

    Returns (header, rows, meta).
    """

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(
            "OpenAI VLM parser requested, but the 'openai' package is not installed. "
            "Install it with: pip install openai"
        ) from e

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Set it in your environment to use VLM parsing.")

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    system = (
        "You are a scientific table extraction assistant. "
        "Return ONLY valid JSON; no commentary. "
        "Preserve minus signs, Greek letters, and units exactly as seen. "
        "If a header is not explicit, invent short column names (col1, col2, ...)."
    )

    user = (
        "Extract the table into a JSON object with keys 'header' and 'rows'. "
        "Header must be a list of strings. Rows must be a list of equal-length lists. "
        "Do not merge distinct columns. "
        f"\n\nCaption (if any): {caption.strip()}"
    )

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=int(max_tokens),
    )

    txt = (resp.choices[0].message.content or "").strip()
    try:
        obj = json.loads(txt)
        header = obj.get("header")
        rows = obj.get("rows")
        if not isinstance(rows, list):
            rows = []
        if header is not None and not isinstance(header, list):
            header = None
        # Coerce rows to list[list[str]]
        clean_rows: List[List[str]] = []
        for r in rows:
            if isinstance(r, list):
                clean_rows.append([str(x) for x in r])
        clean_header: Optional[List[str]] = None
        if header is not None:
            clean_header = [str(x) for x in header]
        meta = {
            "ok": True,
            "engine": "openai",
            "model": model,
            "raw_len": len(txt),
        }
        return clean_header, clean_rows, meta
    except Exception as e:
        return None, [], {
            "ok": False,
            "engine": "openai",
            "model": model,
            "error": f"Failed to parse JSON from model output: {e}",
            "raw": txt[:1200],
        }
