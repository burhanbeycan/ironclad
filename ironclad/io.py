"""
I/O utilities for IRONCLAD desktop demo.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import csv


def save_json(path: str | Path, obj: Any) -> None:
    # IMPORTANT (Windows): never rely on the system default codepage.
    # Many chemistry PDFs contain Unicode minus (\u2212), Greek letters, µ, etc.
    # Writing JSON with the locale encoding (e.g., cp1254/cp1252) can crash.
    Path(path).write_text(
        json.dumps(obj, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_csv(path: str | Path, rows: List[Dict[str, Any]], fieldnames: Optional[List[str]] = None) -> None:
    path = Path(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    if fieldnames is None:
        # union keys
        keys = set()
        for r in rows:
            keys.update(r.keys())
        fieldnames = sorted(keys)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def load_baseline(path: str | Path) -> List[Dict[str, Any]]:
    """
    Load baseline literature records.

    Supported:
      - .json   : list of dicts
      - .jsonl  : one dict per line
      - .csv    : columns include material, property, value, unit (others optional)
    """
    path = Path(path)
    if not path.exists():
        return []
    suf = path.suffix.lower()
    if suf == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suf == ".jsonl":
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
        return out
    if suf == ".csv":
        out = []
        with path.open("r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                out.append(row)
        return out
    return []
