"""
IRONCLAD Desktop (Native) — Tkinter/ttkbootstrap GUI

Features (v3):
- Upload PDF + Analyze
- Extracts "proof-carrying" records with provenance + unit normalization traces + constraints
- Classifies each record as:
    this_work / literature / mixed / unclear
  using citation- and cue-aware heuristics
- Reconstructs table-like regions and (optionally) extracts records from comparison tables
- Extracts embedded images and links figure captions
- Builds a comparison table:
    this work vs cited literature in the paper vs external baseline DB
"""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Optional: modern styling
try:
    import ttkbootstrap as tb
    BOOTSTRAP_OK = True
except Exception:
    BOOTSTRAP_OK = False

from PIL import Image, ImageTk

from ironclad.engine import run as ironclad_run
from ironclad.digitize import digitize_single_curve


class IroncladApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("IRONCLAD Desktop (Native) — This Work vs Literature Comparator")
        self.root.geometry("1250x760")

        # State
        self.pdf_path = tk.StringVar(value="")
        self.doc_id = tk.StringVar(value="local:paper")
        self.out_dir = tk.StringVar(value=str(Path.cwd() / "outputs"))
        self.baseline_path = tk.StringVar(value="")

        self.flag_images = tk.BooleanVar(value=True)
        self.flag_tables = tk.BooleanVar(value=True)
        self.flag_table_records = tk.BooleanVar(value=True)

        # Optional fallback for image-based tables
        #   none : parse only tables with selectable PDF text
        #   ocr  : caption-anchored crop + Tesseract OCR
        #   vlm  : caption-anchored crop + VLM (OpenAI) extraction
        self.table_fallback = tk.StringVar(value="None")
        self.vlm_model = tk.StringVar(value="gpt-4o-mini")

        self.records: List[Dict[str, Any]] = []
        self.tables: List[Dict[str, Any]] = []
        self.figures: Dict[str, Any] = {}
        self.comparison: List[Dict[str, Any]] = []

        self._img_cache: Dict[str, ImageTk.PhotoImage] = {}  # prevent GC

        self._build_ui()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="PDF:").grid(row=0, column=0, sticky="w")
        self.pdf_entry = ttk.Entry(top, textvariable=self.pdf_path, width=72)
        self.pdf_entry.grid(row=0, column=1, padx=6, sticky="we")

        ttk.Button(top, text="Upload…", command=self.on_upload).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="Analyze", command=self.on_analyze).grid(row=0, column=3, padx=4)

        ttk.Label(top, text="Doc ID:").grid(row=0, column=4, padx=(10,2), sticky="e")
        ttk.Entry(top, textvariable=self.doc_id, width=18).grid(row=0, column=5, sticky="w")

        # Options row
        opt = ttk.Frame(self.root)
        opt.pack(fill="x", padx=10)

        ttk.Checkbutton(opt, text="Extract embedded images (figures)", variable=self.flag_images).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(opt, text="Reconstruct tables", variable=self.flag_tables).grid(row=0, column=1, padx=12, sticky="w")
        ttk.Checkbutton(opt, text="Extract records from tables", variable=self.flag_table_records).grid(row=0, column=2, padx=12, sticky="w")

        ttk.Label(opt, text="Table fallback:").grid(row=0, column=3, padx=(18, 2), sticky="e")
        self.fallback_combo = ttk.Combobox(
            opt,
            textvariable=self.table_fallback,
            values=["None", "OCR (Tesseract)", "VLM (OpenAI)"],
            width=16,
            state="readonly",
        )
        self.fallback_combo.grid(row=0, column=4, padx=4, sticky="w")

        ttk.Label(opt, text="VLM model:").grid(row=0, column=5, padx=(18, 2), sticky="e")
        ttk.Entry(opt, textvariable=self.vlm_model, width=16).grid(row=0, column=6, padx=4, sticky="w")

        

        # Output + baseline selectors
        io = ttk.Frame(self.root)
        io.pack(fill="x", padx=10, pady=(6, 8))

        ttk.Label(io, text="Output folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(io, textvariable=self.out_dir, width=55).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(io, text="Choose…", command=self.on_choose_outdir).grid(row=0, column=2, padx=4)
        ttk.Button(io, text="Open", command=self.on_open_outdir).grid(row=0, column=3, padx=4)

        ttk.Label(io, text="Literature baseline DB (optional):").grid(row=0, column=4, padx=(12,2), sticky="e")
        ttk.Entry(io, textvariable=self.baseline_path, width=36).grid(row=0, column=5, padx=6, sticky="we")
        ttk.Button(io, text="Load…", command=self.on_load_baseline).grid(row=0, column=6, padx=4)

        for frame in (top, io):
            frame.columnconfigure(1, weight=1)
            frame.columnconfigure(5, weight=0)

        # Main split: left table + right tabs
        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=3)
        main.add(right, weight=2)

        # Results table
        ttk.Label(left, text="Extracted Records (click a row to view JSON / provenance)").pack(anchor="w")
        self.tree = ttk.Treeview(left, columns=("material","category","property","value","unit","page","origin","confidence","hard_fail"), show="headings", height=22)
        for c, w in [
            ("material",110), ("category",105), ("property",190), ("value",110), ("unit",70),
            ("page",45), ("origin",80), ("confidence",80), ("hard_fail",220)
        ]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(4, 0))

        self.tree.tag_configure("this_work", background="#eaffea")
        self.tree.tag_configure("literature", background="#eaf2ff")
        self.tree.tag_configure("mixed", background="#f5eaff")
        self.tree.tag_configure("unclear", background="#f6f6f6")

        self.tree.bind("<<TreeviewSelect>>", self.on_select_record)

        # Status line
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(left, textvariable=self.status).pack(anchor="w", pady=(6,0))

        # Right tabs
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)

        # Record JSON tab (key/value)
        self.json_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.json_frame, text="Record JSON")

        self.json_tree = ttk.Treeview(self.json_frame, columns=("key","value"), show="headings")
        self.json_tree.heading("key", text="key")
        self.json_tree.heading("value", text="value")
        self.json_tree.column("key", width=160, anchor="w")
        self.json_tree.column("value", width=520, anchor="w")
        self.json_tree.pack(fill="both", expand=True)

        # Comparison tab
        self.cmp_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.cmp_frame, text="Comparison")

        ttk.Label(self.cmp_frame, text="This paper vs cited literature vs external baseline").pack(anchor="w", padx=4, pady=(4,0))
        self.cmp_tree = ttk.Treeview(self.cmp_frame, columns=("material","property","category","this_work","paper_cited_literature","external_baseline","novelty_flag"), show="headings", height=18)
        for c,w in [
            ("material",105), ("property",190), ("category",95),
            ("this_work",150), ("paper_cited_literature",160), ("external_baseline",150), ("novelty_flag",150)
        ]:
            self.cmp_tree.heading(c, text=c)
            self.cmp_tree.column(c, width=w, anchor="w")
        self.cmp_tree.pack(fill="both", expand=True, padx=4, pady=4)

        # Tables tab
        self.tbl_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.tbl_frame, text="Tables")

        tbl_top = ttk.Frame(self.tbl_frame)
        tbl_top.pack(fill="x", padx=4, pady=4)
        ttk.Label(tbl_top, text="Detected table regions:").pack(side="left")
        ttk.Button(tbl_top, text="Export tables JSON", command=self.on_export_tables).pack(side="right")

        tbl_body = ttk.Panedwindow(self.tbl_frame, orient=tk.HORIZONTAL)
        tbl_body.pack(fill="both", expand=True, padx=4, pady=4)
        self.tbl_list = tk.Listbox(tbl_body, height=12)
        self.tbl_text = ScrolledText(tbl_body, wrap="word")
        tbl_body.add(self.tbl_list, weight=1)
        tbl_body.add(self.tbl_text, weight=3)
        self.tbl_list.bind("<<ListboxSelect>>", self.on_select_table)

        # Figures tab
        self.fig_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.fig_frame, text="Figures")

        fig_body = ttk.Panedwindow(self.fig_frame, orient=tk.HORIZONTAL)
        fig_body.pack(fill="both", expand=True, padx=4, pady=4)

        left_fig = ttk.Frame(fig_body)
        right_fig = ttk.Frame(fig_body)
        fig_body.add(left_fig, weight=1)
        fig_body.add(right_fig, weight=3)

        ttk.Label(left_fig, text="Embedded images:").pack(anchor="w")
        self.fig_list = tk.Listbox(left_fig, height=18)
        self.fig_list.pack(fill="both", expand=True)
        self.fig_list.bind("<<ListboxSelect>>", self.on_select_figure)

        ttk.Button(left_fig, text="Digitize plot (beta)", command=self.on_digitize_plot).pack(fill="x", pady=(6,0))

        self.fig_caption = ScrolledText(right_fig, wrap="word", height=6)
        self.fig_caption.pack(fill="x", pady=(0,6))
        self.fig_canvas = tk.Label(right_fig, text="(select an image)", anchor="center")
        self.fig_canvas.pack(fill="both", expand=True)

        # Log tab
        self.log_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.log_frame, text="Log")
        self.log = ScrolledText(self.log_frame, wrap="word")
        self.log.pack(fill="both", expand=True)

    # ---------------- Actions ----------------
    def on_upload(self):
        path = filedialog.askopenfilename(title="Select PDF", filetypes=[("PDF files","*.pdf")])
        if path:
            self.pdf_path.set(path)

    def on_choose_outdir(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.out_dir.set(d)

    def on_open_outdir(self):
        d = self.out_dir.get().strip()
        if not d:
            return
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(p))  # Windows
        except Exception:
            try:
                import subprocess
                subprocess.run(["open", str(p)])  # macOS
            except Exception:
                messagebox.showinfo("Output folder", str(p))

    def on_load_baseline(self):
        path = filedialog.askopenfilename(
            title="Select baseline DB (.json/.jsonl/.csv)",
            filetypes=[("JSON","*.json"), ("JSONL","*.jsonl"), ("CSV","*.csv"), ("All","*.*")]
        )
        if path:
            self.baseline_path.set(path)

    def on_analyze(self):
        pdf = self.pdf_path.get().strip()
        if not pdf or not Path(pdf).exists():
            messagebox.showerror("Missing PDF", "Please upload/select a PDF first.")
            return

        out_dir = Path(self.out_dir.get().strip() or (Path.cwd() / "outputs"))
        out_dir.mkdir(parents=True, exist_ok=True)

        # Clear UI
        self._clear_tables()
        self._clear_figures()
        self._clear_results()
        self._clear_json()
        self._clear_comparison()
        self._log_clear()

        self.status.set("Analyzing…")
        self._log(f"Running IRONCLAD on: {pdf}")

        def worker():
            try:
                mode_map = {
                    "none": "none",
                    "None": "none",
                    "OCR (Tesseract)": "ocr",
                    "VLM (OpenAI)": "vlm",
                }
                table_fallback_mode = mode_map.get(self.table_fallback.get(), "none")

                res = ironclad_run(
                    pdf_path=pdf,
                    doc_id=self.doc_id.get().strip() or "local:paper",
                    out_dir=str(out_dir),
                    extract_images_flag=self.flag_images.get(),
                    reconstruct_tables_flag=self.flag_tables.get(),
                    extract_table_records_flag=self.flag_table_records.get(),
                    baseline_path=self.baseline_path.get().strip() or None,
                    table_fallback_mode=table_fallback_mode,
                    vlm_model=self.vlm_model.get().strip() or "gpt-4o-mini",
                )
                self.root.after(0, lambda: self._on_done(res))
            except Exception as e:
                self.root.after(0, lambda exc=e: self._on_error(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, res: Dict[str, Any]):
        self.records = res.get("records", [])
        self.tables = res.get("tables", [])
        self.figures = res.get("figures", {})
        self.comparison = res.get("comparison", [])

        self._populate_results(self.records)
        self._populate_tables(self.tables)
        self._populate_figures(self.figures)
        self._populate_comparison(self.comparison)

        for line in res.get("logs", []):
            self._log(line)

        self.status.set(f"Done. Extracted {len(self.records)} record(s). Saved: {res.get('output_json')}")
        self.tabs.select(self.cmp_frame)

    def _on_error(self, e: Exception):
        self.status.set("Error.")
        self._log(f"ERROR: {repr(e)}")
        messagebox.showerror("IRONCLAD error", str(e))

    # ---------------- Populate UI ----------------
    def _populate_results(self, records: List[Dict[str, Any]]):
        for i, r in enumerate(records):
            v = r.get("value_min")
            vmax = r.get("value_max")
            value_str = str(v) if vmax is None or vmax == v else f"{v}–{vmax}"
            hard_fail = ";".join((r.get("constraints", {}) or {}).get("hard_fail", []) or [])

            tag = r.get("origin","unclear")
            if tag not in {"this_work","literature","mixed","unclear"}:
                tag = "unclear"

            self.tree.insert("", "end", iid=str(i), values=(
                r.get("material",""),
                r.get("category",""),
                r.get("property",""),
                value_str,
                r.get("unit_original",""),
                r.get("provenance",{}).get("page",""),
                r.get("origin",""),
                r.get("confidence",""),
                hard_fail
            ), tags=(tag,))

    def _populate_comparison(self, rows: List[Dict[str, Any]]):
        for i, r in enumerate(rows):
            self.cmp_tree.insert("", "end", iid=str(i), values=(
                r.get("material",""),
                r.get("property",""),
                r.get("category",""),
                r.get("this_work",""),
                r.get("paper_cited_literature",""),
                r.get("external_baseline",""),
                r.get("novelty_flag",""),
            ))

    def _populate_tables(self, tables: List[Dict[str, Any]]):
        for t in tables:
            self.tbl_list.insert("end", f"{t.get('table_id')} (p.{t.get('page')})")

    def _populate_figures(self, figures: Dict[str, Any]):
        imgs = figures.get("images", []) if figures else []
        for i, im in enumerate(imgs):
            cap = im.get("caption") or ""
            label = f"Fig {i+1} (p.{im.get('page')}) — {cap[:35]}"
            self.fig_list.insert("end", label)

    # ---------------- Selection handlers ----------------
    def on_select_record(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.records):
            return
        r = self.records[idx]
        self._show_record_json(r)

    def _show_record_json(self, r: Dict[str, Any]):
        self._clear_json()
        # Flatten to key/value for readability
        flat = {
            "doc_id": r.get("doc_id"),
            "source_type": r.get("source_type"),
            "material": r.get("material"),
            "property": r.get("property"),
            "category": r.get("category"),
            "value_min": r.get("value_min"),
            "value_max": r.get("value_max"),
            "unit_original": r.get("unit_original"),
            "value_si_min": r.get("value_si_min"),
            "value_si_max": r.get("value_si_max"),
            "unit_si": r.get("unit_si"),
            "origin": r.get("origin"),
            "citations": ", ".join(r.get("citations") or []),
            "confidence": r.get("confidence"),
            "hard_fail": ";".join((r.get("constraints", {}) or {}).get("hard_fail", []) or []),
            "soft_warn": ";".join((r.get("constraints", {}) or {}).get("soft_warn", []) or []),
            "provenance_page": r.get("provenance",{}).get("page"),
            "provenance_bbox": r.get("provenance",{}).get("bbox"),
            "provenance_snippet": r.get("provenance",{}).get("snippet"),
        }
        for k, v in flat.items():
            self.json_tree.insert("", "end", values=(k, str(v)))

    def on_select_table(self, _evt=None):
        idxs = self.tbl_list.curselection()
        if not idxs:
            return
        i = idxs[0]
        if i < 0 or i >= len(self.tables):
            return
        t = self.tables[i]
        self.tbl_text.delete("1.0", "end")
        self.tbl_text.insert("end", f"Table {t.get('table_id')} — page {t.get('page')}\n")
        self.tbl_text.insert("end", f"bbox: {t.get('bbox')}\n")
        self.tbl_text.insert("end", f"meta: {json.dumps(t.get('meta',{}), indent=2)}\n\n")
        header = t.get("header")
        if header:
            self.tbl_text.insert("end", " | ".join(header) + "\n")
            self.tbl_text.insert("end", "-" * 80 + "\n")
        for row in t.get("rows", []):
            self.tbl_text.insert("end", " | ".join(row) + "\n")

    def on_select_figure(self, _evt=None):
        idxs = self.fig_list.curselection()
        if not idxs:
            return
        i = idxs[0]
        imgs = self.figures.get("images", []) if self.figures else []
        if i < 0 or i >= len(imgs):
            return
        im = imgs[i]
        self.fig_caption.delete("1.0", "end")
        self.fig_caption.insert("end", f"Page: {im.get('page')}\nType: {im.get('figure_type')}\n\nCaption:\n{im.get('caption') or '(none)'}\n")
        self._show_image(im.get("path"))

    def _show_image(self, path: Optional[str]):
        if not path or not Path(path).exists():
            self.fig_canvas.configure(text="(image file missing)", image="")
            return
        p = str(path)
        try:
            img = Image.open(p)
            # Fit to canvas area
            max_w, max_h = 650, 430
            img.thumbnail((max_w, max_h))
            tk_img = ImageTk.PhotoImage(img)
            self._img_cache["current"] = tk_img
            self.fig_canvas.configure(image=tk_img, text="")
        except Exception as e:
            self.fig_canvas.configure(text=f"(cannot render image: {e})", image="")

    
    def on_digitize_plot(self):
        """
        Open a simple digitization window for the currently selected figure.
        Requires manual ROI + axis calibration.
        """
        idxs = self.fig_list.curselection()
        if not idxs:
            messagebox.showinfo("Digitize", "Select a figure first in the Figures tab.")
            return
        i = idxs[0]
        imgs = self.figures.get("images", []) if self.figures else []
        if i < 0 or i >= len(imgs):
            return
        im = imgs[i]
        path = im.get("path")
        if not path or not Path(path).exists():
            messagebox.showerror("Digitize", "Image file not found on disk.")
            return

        # Only suggest digitization if caption looks plot-like, but allow anyway
        self._open_digitizer_window(image_path=path, suggested_name=f"figure_{i+1}")

    def _open_digitizer_window(self, image_path: str, suggested_name: str = "digitized"):
        win = tk.Toplevel(self.root)
        win.title("Plot digitization (beta) — ROI + axis calibration")
        win.geometry("980x720")

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # Left: image canvas
        left = ttk.Frame(frm)
        left.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(frm)
        right.pack(side="right", fill="y")

        ttk.Label(left, text="Click bottom-left then top-right corners of the plot area (ROI).").pack(anchor="w")
        canvas = tk.Canvas(left, width=720, height=560, bg="white")
        canvas.pack(fill="both", expand=True, pady=6)

        # Load image
        pil = Image.open(image_path)
        # Fit into canvas
        pil_disp = pil.copy()
        pil_disp.thumbnail((720, 560))
        tkimg = ImageTk.PhotoImage(pil_disp)
        canvas.create_image(0, 0, anchor="nw", image=tkimg)
        # keep refs
        win._tkimg = tkimg  # type: ignore

        # Coordinate mapping from displayed image to original pixels
        scale_x = pil.size[0] / pil_disp.size[0]
        scale_y = pil.size[1] / pil_disp.size[1]

        clicks = []  # [(x,y)] in original pixel coords

        roi_var = tk.StringVar(value="ROI: (not set)")
        ttk.Label(right, textvariable=roi_var).pack(anchor="w", pady=(0,6))

        def on_click(evt):
            # convert to original pixels
            ox = int(evt.x * scale_x)
            oy = int(evt.y * scale_y)
            clicks.append((ox, oy))
            if len(clicks) == 1:
                roi_var.set(f"ROI bottom-left: {clicks[0]} (now click top-right)")
                canvas.create_oval(evt.x-4, evt.y-4, evt.x+4, evt.y+4, outline="red", width=2)
            elif len(clicks) == 2:
                roi_var.set(f"ROI BL={clicks[0]}, TR={clicks[1]}")
                canvas.create_oval(evt.x-4, evt.y-4, evt.x+4, evt.y+4, outline="blue", width=2)
            else:
                # reset if user keeps clicking
                clicks.clear()
                roi_var.set("ROI reset. Click bottom-left then top-right.")
                canvas.delete("all")
                canvas.create_image(0, 0, anchor="nw", image=tkimg)

        canvas.bind("<Button-1>", on_click)

        # Right: calibration inputs
        ttk.Label(right, text="Axis calibration values").pack(anchor="w")
        x_min = tk.DoubleVar(value=0.0)
        x_max = tk.DoubleVar(value=1.0)
        y_min = tk.DoubleVar(value=0.0)
        y_max = tk.DoubleVar(value=1.0)
        log_x = tk.BooleanVar(value=False)
        log_y = tk.BooleanVar(value=False)
        thr = tk.IntVar(value=80)

        def row(label, var):
            r = ttk.Frame(right); r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=8).pack(side="left")
            ttk.Entry(r, textvariable=var, width=16).pack(side="left")
        row("x_min", x_min)
        row("x_max", x_max)
        row("y_min", y_min)
        row("y_max", y_max)

        ttk.Checkbutton(right, text="log-x axis", variable=log_x).pack(anchor="w", pady=(8,0))
        ttk.Checkbutton(right, text="log-y axis", variable=log_y).pack(anchor="w")

        rthr = ttk.Frame(right); rthr.pack(fill="x", pady=(8,2))
        ttk.Label(rthr, text="threshold").pack(side="left")
        ttk.Entry(rthr, textvariable=thr, width=8).pack(side="left", padx=6)
        ttk.Label(right, text="(lower = darker pixels)").pack(anchor="w")

        preview = ScrolledText(right, wrap="word", height=18)
        preview.pack(fill="both", expand=True, pady=8)

        def do_digitize():
            if len(clicks) != 2:
                messagebox.showerror("Digitize", "ROI not set. Click bottom-left then top-right on the plot area.")
                return
            bl, tr = clicks[0], clicks[1]
            try:
                pts = digitize_single_curve(
                    image_path=image_path,
                    roi_bl=bl,
                    roi_tr=tr,
                    x_min=float(x_min.get()), x_max=float(x_max.get()),
                    y_min=float(y_min.get()), y_max=float(y_max.get()),
                    log_x=bool(log_x.get()), log_y=bool(log_y.get()),
                    threshold=int(thr.get()),
                )
            except Exception as e:
                messagebox.showerror("Digitize failed", str(e))
                return

            out = Path(self.out_dir.get().strip() or (Path.cwd() / "outputs"))
            out.mkdir(parents=True, exist_ok=True)
            ddir = out / "digitized"
            ddir.mkdir(parents=True, exist_ok=True)
            out_csv = ddir / f"{suggested_name}_digitized.csv"

            # write CSV
            import csv
            with out_csv.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["x","y"])
                w.writeheader()
                for p in pts:
                    w.writerow(p)

            preview.delete("1.0","end")
            preview.insert("end", f"Exported {len(pts)} points to:\n{out_csv}\n\nFirst points:\n")
            for p in pts[:12]:
                preview.insert("end", f"{p['x']:.6g}, {p['y']:.6g}\n")

            messagebox.showinfo("Digitize", f"Saved: {out_csv}")

        ttk.Button(right, text="Digitize & Export CSV", command=do_digitize).pack(fill="x", pady=(4,0))
        ttk.Button(right, text="Close", command=win.destroy).pack(fill="x", pady=(6,0))

# ---------------- Export helpers ----------------
    def on_export_tables(self):
        if not self.tables:
            messagebox.showinfo("Tables", "No tables detected.")
            return
        out = Path(self.out_dir.get().strip() or (Path.cwd() / "outputs"))
        out.mkdir(parents=True, exist_ok=True)
        path = out / "ironclad_tables_export.json"
        path.write_text(json.dumps(self.tables, indent=2, ensure_ascii=False), encoding="utf-8")
        messagebox.showinfo("Tables exported", str(path))

    # ---------------- Clearing helpers ----------------
    def _clear_results(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _clear_json(self):
        for i in self.json_tree.get_children():
            self.json_tree.delete(i)

    def _clear_tables(self):
        self.tbl_list.delete(0, "end")
        self.tbl_text.delete("1.0", "end")

    def _clear_figures(self):
        self.fig_list.delete(0, "end")
        self.fig_caption.delete("1.0", "end")
        self.fig_canvas.configure(text="(select an image)", image="")
        self._img_cache.clear()

    def _clear_comparison(self):
        for i in self.cmp_tree.get_children():
            self.cmp_tree.delete(i)

    def _log_clear(self):
        self.log.delete("1.0", "end")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")


def main():
    if BOOTSTRAP_OK:
        root = tb.Window(themename="flatly")
    else:
        root = tk.Tk()
        # use a nicer ttk theme if available
        try:
            ttk.Style(root).theme_use("clam")
        except Exception:
            pass
    app = IroncladApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
