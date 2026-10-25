#!/usr/bin/env python3
"""PageSmith desktop shell (tkinter).
Pick PDF file(s), choose one batch operation -> run -> every output is
re-opened and verified, with the verdict and report path shown here."""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page_smith import run_pagesmith

OPS = ["Merge all selected files (in list order)",
       "Split — every N pages",
       "Split — by page ranges",
       "Extract pages",
       "Rotate pages",
       "Add text watermark"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PageSmith PDF — Batch Page Operations & Re-Check")
        self.geometry("720x600")
        self.files = []

        tk.Label(self, text="PDF files (for Merge, list order = merge order):").pack(anchor="w", padx=12, pady=(12, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=12)
        self.listbox = tk.Listbox(row, height=5)
        self.listbox.pack(side="left", fill="x", expand=True)
        btns = tk.Frame(row)
        btns.pack(side="left", padx=6)
        tk.Button(btns, text="Add files…", command=self.add).pack(fill="x", pady=2)
        tk.Button(btns, text="Remove", command=self.remove).pack(fill="x", pady=2)
        tk.Button(btns, text="Clear", command=self.clear).pack(fill="x", pady=2)

        tk.Label(self, text="Operation:").pack(anchor="w", padx=12, pady=(10, 2))
        self.op = ttk.Combobox(self, values=OPS, state="readonly", width=52)
        self.op.current(0)
        self.op.pack(anchor="w", padx=12)

        grid = tk.Frame(self)
        grid.pack(fill="x", padx=12, pady=10)
        tk.Label(grid, text="Split every N pages / ranges (e.g. 1-3,4-6):").grid(row=0, column=0, sticky="w")
        self.split_param = tk.Entry(grid, width=22)
        self.split_param.grid(row=0, column=1, padx=6, sticky="w")
        tk.Label(grid, text="Extract pages (e.g. 2,4-5):").grid(row=1, column=0, sticky="w")
        self.extract_param = tk.Entry(grid, width=22)
        self.extract_param.grid(row=1, column=1, padx=6, sticky="w")
        tk.Label(grid, text="Rotate angle (deg):").grid(row=2, column=0, sticky="w")
        self.angle = ttk.Combobox(grid, values=["90", "180", "270"], state="readonly", width=6)
        self.angle.current(0)
        self.angle.grid(row=2, column=1, padx=6, sticky="w")
        tk.Label(grid, text="Rotate pages (blank = all, e.g. 1-3):").grid(row=3, column=0, sticky="w")
        self.rotate_pages = tk.Entry(grid, width=22)
        self.rotate_pages.grid(row=3, column=1, padx=6, sticky="w")
        tk.Label(grid, text="Watermark text:").grid(row=4, column=0, sticky="w")
        self.wm_text = tk.Entry(grid, width=22)
        self.wm_text.grid(row=4, column=1, padx=6, sticky="w")
        tk.Label(grid, text="Watermark opacity (0–1) / position:").grid(row=5, column=0, sticky="w")
        wm = tk.Frame(grid)
        wm.grid(row=5, column=1, padx=6, sticky="w")
        self.wm_opacity = tk.Entry(wm, width=6)
        self.wm_opacity.insert(0, "0.25")
        self.wm_opacity.pack(side="left")
        self.wm_pos = ttk.Combobox(wm, values=["center", "top", "bottom"], state="readonly", width=9)
        self.wm_pos.current(0)
        self.wm_pos.pack(side="left", padx=6)

        self.btn = tk.Button(self, text="Run Operation & Re-Check Outputs", command=self.run, height=2)
        self.btn.pack(pady=10)
        self.log = scrolledtext.ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.write("PageSmith runs page operations on whole batches of PDFs,\n"
                   "then re-opens every output to verify page counts, rotation\n"
                   "and watermarks. Everything runs locally — your documents\n"
                   "never leave this computer.\n")

    def write(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def add(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", os.path.basename(p))

    def remove(self):
        sel = self.listbox.curselection()
        if sel:
            i = sel[0]
            del self.files[i]
            self.listbox.delete(i)

    def clear(self):
        self.files = []
        self.listbox.delete(0, "end")

    def build_job(self):
        choice = self.op.get()
        files = list(self.files)
        if not files:
            raise ValueError("Add at least one PDF file first.")
        if choice.startswith("Merge"):
            if len(files) < 2:
                raise ValueError("Merge needs at least two files.")
            return {"operations": [{"op": "merge", "inputs": files}]}
        ops = []
        for f in files:
            if choice.startswith("Split — every"):
                ops.append({"op": "split", "input": f, "mode": "every",
                            "n": int(self.split_param.get().strip())})
            elif choice.startswith("Split — by"):
                ops.append({"op": "split", "input": f, "mode": "ranges",
                            "ranges": self.split_param.get().strip()})
            elif choice.startswith("Extract"):
                ops.append({"op": "extract", "input": f,
                            "pages": self.extract_param.get().strip()})
            elif choice.startswith("Rotate"):
                ops.append({"op": "rotate", "input": f,
                            "angle": int(self.angle.get()),
                            "pages": self.rotate_pages.get().strip() or "all"})
            elif choice.startswith("Add"):
                ops.append({"op": "watermark", "input": f,
                            "text": self.wm_text.get(),
                            "opacity": float(self.wm_opacity.get()),
                            "position": self.wm_pos.get()})
        return {"operations": ops}

    def run(self):
        try:
            job = self.build_job()
        except Exception as e:
            messagebox.showerror("PageSmith", str(e))
            return
        self.btn.config(state="disabled")
        threading.Thread(target=self._work, args=(job,), daemon=True).start()

    def _work(self, job):
        try:
            first = (job["operations"][0].get("input")
                     or job["operations"][0]["inputs"][0])
            outdir = os.path.join(os.path.dirname(first), "pagesmith_output")
            s = run_pagesmith(job, outdir)
            self.write(f"\nDone. Operations: {s['operations']} · outputs: {s['outputs']} · "
                       f"verified: {s['verified']} · failed: {s['failed']} · "
                       f"problems: {len(s['problems'])}\nReport: {s['report_path']}\n")
            for p in s["problems"]:
                self.write(f"Problem: {p}\n")
            if s["failed"]:
                self.write("Verdict: NOT READY — see the report for the failing outputs.\n")
            elif s["problems"]:
                self.write("Verdict: PASS WITH PROBLEMS — outputs verified; some inputs were skipped (above).\n")
            else:
                self.write("Verdict: PASS — every output re-opened and verified.\n")
        except Exception as e:  # surface, never crash silently
            self.write(f"\nError: {e}\n")
        finally:
            self.btn.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
