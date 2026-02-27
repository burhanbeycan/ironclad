"""
Simple plot digitization (beta).

This provides a pragmatic "in-app" digitization method for common scientific plots:
- user selects plot region (bottom-left, top-right)
- user supplies axis calibration values (x_min, x_max, y_min, y_max)
- optional log-x and log-y scaling
- algorithm thresholds dark pixels and extracts an approximate curve by x-binning

Limitations (intentional for v3):
- works best for single dark curve on light background
- does not automatically detect axes or multiple curves
"""

from __future__ import annotations

from typing import Tuple, List, Dict
from pathlib import Path
import math

from PIL import Image


def digitize_single_curve(
    image_path: str | Path,
    roi_bl: Tuple[int, int],   # bottom-left pixel (x0,y0)
    roi_tr: Tuple[int, int],   # top-right pixel (x1,y1)
    x_min: float, x_max: float,
    y_min: float, y_max: float,
    log_x: bool = False,
    log_y: bool = False,
    threshold: int = 80,       # 0..255 grayscale; lower = darker
    bins: int = 250,
) -> List[Dict[str, float]]:
    """
    Returns list of points: [{"x":..., "y":...}, ...]
    """
    img = Image.open(str(image_path)).convert("L")  # grayscale
    w, h = img.size
    x0, y0 = roi_bl
    x1, y1 = roi_tr
    # Normalize ROI to image bounds
    x0 = max(0, min(w-1, x0)); x1 = max(0, min(w-1, x1))
    y0 = max(0, min(h-1, y0)); y1 = max(0, min(h-1, y1))
    if x1 <= x0 or y0 <= y1:
        raise ValueError("Invalid ROI: ensure you clicked bottom-left then top-right.")

    # Precompute axis transforms
    def x_map(px: int) -> float:
        t = (px - x0) / max(1e-12, (x1 - x0))
        if log_x:
            return 10 ** (math.log10(x_min) + t * (math.log10(x_max) - math.log10(x_min)))
        return x_min + t * (x_max - x_min)

    def y_map(py: int) -> float:
        # y decreases upward in pixel coords
        t = (y0 - py) / max(1e-12, (y0 - y1))
        if log_y:
            return 10 ** (math.log10(y_min) + t * (math.log10(y_max) - math.log10(y_min)))
        return y_min + t * (y_max - y_min)

    # Extract dark pixels in ROI
    pix = img.load()
    # bin x in pixel space for speed
    bin_w = (x1 - x0) / bins
    ys_per_bin: List[List[int]] = [[] for _ in range(bins)]
    for px in range(x0, x1 + 1):
        b = int((px - x0) / max(1e-12, bin_w))
        if b < 0: b = 0
        if b >= bins: b = bins - 1
        for py in range(y1, y0 + 1):
            if pix[px, py] <= threshold:
                ys_per_bin[b].append(py)

    points: List[Dict[str, float]] = []
    for b, ys in enumerate(ys_per_bin):
        if not ys:
            continue
        # robust: median y
        ys_sorted = sorted(ys)
        py_med = ys_sorted[len(ys_sorted)//2]
        px_center = int(x0 + (b + 0.5) * bin_w)
        points.append({"x": float(x_map(px_center)), "y": float(y_map(py_med))})

    return points
