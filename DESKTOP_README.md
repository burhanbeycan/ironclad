# IRONCLAD Desktop (Native) — v5

This is a **native desktop GUI** (Tkinter + ttkbootstrap) for demonstrating **IRONCLAD** as a
*proof-carrying chemical/materials information extractor*.

## What v5 adds

### 1) "This work" vs "Literature" differentiation (within the same uploaded paper)
Each extracted record is labeled:

- `this_work` — likely measured/reported by the authors (e.g., “in this work…”, “we measured…”)
- `literature` — likely quoted from prior work (explicit citations like `[12]`, `Ref. 3`, or “reported previously…”)
- `mixed` — both signals present in the same snippet
- `unclear` — no strong cues

This is implemented as a **citation- and rhetoric-aware deterministic classifier** (auditable, no LLM required).

### 2) Comparison table after analysis
The GUI builds a paper-centric comparison table:

- **This work** (records labeled this_work)
- **Cited literature inside the same paper** (records labeled literature)
- **External baseline DB** (optional; you can load `.json/.jsonl/.csv`)

It highlights whether this paper is:
- comparing against literature (common in experimental papers),
- within baseline range,
- or a potential *new regime*.

### 3) Table reconstruction + (optional) table-to-record extraction
IRONCLAD detects table-like regions using span x-positions, reconstructs rows/columns, and can also extract
records from tables (especially useful for comparison tables).

### 4) Figure extraction + caption linking
Embedded figures are exported into `outputs/images/` and shown in the GUI with detected captions.

> Plot digitization remains a **beta hook** (manual ROI + axis calibration). v5 focuses on
> robust paper-centric provenance and comparison, and improves table support.

### 5) Image-based tables: caption-anchored OCR/VLM fallback (optional)
Some chemistry PDFs embed tables as images (scans / rasterized exports). In such cases
the PDF text layer contains the caption (e.g., "Table 2."), but the table body has no
selectable text.

v5 adds a **caption-anchored fallback**:

- `None`: only parse tables available in the PDF text layer.
- `OCR (Tesseract)`: crop the region below each detected caption and OCR it.
- `VLM (OpenAI)`: crop the region and ask a vision-language model to return JSON.

In the GUI, use the **Table fallback** dropdown.

#### OCR prerequisite
OCR uses `pytesseract`, which requires the *Tesseract* binary to be installed and on your PATH.
If you enable OCR without Tesseract installed, IRONCLAD will report a clear error in the Log tab
and continue without OCR tables.

#### VLM prerequisite (optional)
VLM fallback is a guarded plugin:
1) `pip install openai`
2) set `OPENAI_API_KEY`
3) select **VLM (OpenAI)** in the GUI

## Run (Windows)
Double click or run:

```powershell
.\run_tk_desktop.bat
```

## Run (macOS/Linux)
```bash
chmod +x run_tk_desktop.sh
./run_tk_desktop.sh
```

## Optional baseline DB
A small demo baseline is included:

`examples/literature_baseline.jsonl`

Load it in the GUI to see external-baseline comparison.

## Outputs
In your chosen output folder:

- `ironclad_output.json` (full proof-carrying records)
- `ironclad_summary.csv` (flat record table)
- `ironclad_comparison.csv` (this work vs literature vs baseline)
- `ironclad_tables.json` (table regions)
- `ironclad_figures.json` + `images/` (embedded figures)


## Plot digitization (beta)
In the **Figures** tab, select an image and click **Digitize plot (beta)**.
You will manually click the plot ROI (bottom-left then top-right) and provide axis min/max values.
IRONCLAD will export an approximate single-curve CSV to `outputs/digitized/`.

Supports optional log-x and log-y axes.
