# IRONCLAD — Proof-carrying polymer & materials information extraction

IRONCLAD is a **native desktop GUI** (Tkinter + ttkbootstrap) that demonstrates a *proof-carrying* extraction workflow for polymer / materials papers:

- extracts property records with **page + snippet provenance**
- keeps **unit normalization traces** (original → SI when possible)
- runs **constraint checks** (unit/dimension consistency + simple polymer cross-checks)
- labels records as **this work vs cited literature vs mixed/unclear**
- reconstructs tables, extracts figures, and builds a **paper-centric comparison table**

> A static **interactive web viewer** is included in `docs/` so you can explore `ironclad_output.json` in the browser (perfect for GitHub Pages).

---

## Interactive GitHub Pages site

After you push this repository to GitHub, enable GitHub Pages with:

1) **Settings → Pages**
2) **Source:** “Deploy from a branch”
3) **Branch:** `main`
4) **Folder:** `/docs`

Your site will be published at:

- `https://<username>.github.io/ironclad/`
- Viewer: `https://<username>.github.io/ironclad/viewer.html`

The viewer is **client-side only**: it visualizes IRONCLAD JSON outputs; it does **not** parse PDFs in the browser.

---

## Quickstart (desktop)

### Install
```bash
pip install -r requirements.txt
```

### Run

**Windows**
```powershell
.un_tk_desktop.bat
```

**macOS / Linux**
```bash
chmod +x run_tk_desktop.sh
./run_tk_desktop.sh
```

### Optional baseline DB
A small polymer/electrolyte demo baseline is included:

- `examples/literature_baseline.jsonl`

Load it in the GUI to populate the **external baseline** column in the comparison table.

---

## Outputs

In your chosen output folder IRONCLAD writes:

- `ironclad_output.json` — full proof-carrying export (records + tables + figures + comparison + logs)
- `ironclad_summary.csv` — flat records table
- `ironclad_comparison.csv` — this work vs cited lit vs baseline
- `ironclad_tables.json` — table regions (if enabled)
- `ironclad_figures.json` + `images/` — embedded figures + captions (if enabled)

---

## Table fallback modes (optional)

Some chemistry PDFs embed tables as images. IRONCLAD supports a caption-anchored fallback:

- **None**: parse only tables present in the PDF text layer
- **OCR (Tesseract)**: crop below each detected caption and OCR it
- **VLM (OpenAI)**: crop and ask a vision-language model to return JSON

### OCR prerequisite
`pytesseract` requires the **Tesseract** binary installed and available on your PATH.

### VLM prerequisite (optional)
1) `pip install openai`
2) set `OPENAI_API_KEY`
3) choose **VLM (OpenAI)** in the GUI

---

## Repository layout

- `ironclad/` — core extraction engine (PDF parsing, ontology, units, constraints, compare, tables, figures)
- `app/` — Tkinter GUI
- `examples/` — demo baseline DB
- `docs/` — GitHub Pages site (landing page + interactive JSON viewer)
- `DESKTOP_README.md` — original desktop-focused notes

---

## License

Add a license that matches your intended use (MIT/Apache-2.0/etc.).  
(At the moment this repo is provided as a demonstration skeleton.)
