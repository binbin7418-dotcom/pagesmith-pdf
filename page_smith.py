#!/usr/bin/env python3
"""
PageSmith PDF — batch PDF page operations with a verification pass.

Pipeline:
  1. Run a batch of deterministic page operations over whole files/folders:
     split (by page ranges or every N pages), merge (ordered), rotate,
     extract pages, and text watermarks (adjustable opacity / position).
  2. Re-check EVERY output file: re-open it, count its pages, verify the
     page-count conservation for its operation, spot-check rotation and
     watermark presence. Results land in pagesmith_report.md.
  3. Inputs that cannot be opened (corrupt, encrypted) are reported as
     failed and skipped — never silently dropped, never "repaired" by
     guessing. PageSmith does not edit PDF content, OCR, or fill forms.

Local only. No network access. Engine: pypdf (BSD-3-Clause);
watermark layers are drawn with reportlab (BSD). See THIRD_PARTY_NOTICES.md.

Usage:
  python page_smith.py job.json <outdir>            # batch job file
  python page_smith.py in.pdf <outdir> --split-every 2
  python page_smith.py in.pdf <outdir> --split-ranges 1-3,4-6
  python page_smith.py in.pdf <outdir> --extract 2,4-5
  python page_smith.py in.pdf <outdir> --rotate 90 [--pages 1-3]
  python page_smith.py in.pdf <outdir> --watermark "CONFIDENTIAL"
                       [--opacity 0.25] [--position center|top|bottom]
  python page_smith.py <folder> <outdir> --merge-all
"""
import io
import json
import os
import sys

from pypdf import PdfReader, PdfWriter


# --------------------------------------------------------------------------
# page specs
# --------------------------------------------------------------------------

def parse_page_spec(spec, total):
    """Parse a 1-based spec like '2,4-5,8' into sorted 0-based indices.
    Raises ValueError on malformed or out-of-range input."""
    if isinstance(spec, (list, tuple)):
        idx = []
        for s in spec:
            idx += parse_page_spec(str(s), total)
        return sorted(set(idx))
    spec = str(spec).strip()
    if spec.lower() == "all":
        return list(range(total))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty page entry in spec '{spec}'")
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if lo < 1 or hi < lo or hi > total:
                raise ValueError(f"page range '{part}' out of bounds (document has {total} pages)")
            out.extend(range(lo - 1, hi))
        else:
            n = int(part)
            if n < 1 or n > total:
                raise ValueError(f"page '{part}' out of bounds (document has {total} pages)")
            out.append(n - 1)
    return sorted(set(out))


def parse_ranges(spec):
    """Parse '1-3,4-6' into a list of (lo, hi) 1-based inclusive ranges."""
    ranges = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty range in '{spec}'")
        if "-" in part:
            a, b = part.split("-", 1)
            ranges.append((int(a), int(b)))
        else:
            ranges.append((int(part), int(part)))
    return ranges


# --------------------------------------------------------------------------
# watermark overlay
# --------------------------------------------------------------------------

def _watermark_overlay(text, width, height, opacity, position):
    """Build a one-page PDF (as a pypdf PageObject) holding the watermark
    text, sized to the target page."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.saveState()
    try:
        c.setFillAlpha(opacity)
    except Exception:
        pass
    c.setFillColorRGB(0.45, 0.45, 0.45)
    if position == "top":
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, height - 32, text)
    elif position == "bottom":
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, 22, text)
    else:  # center — large diagonal
        size = 44
        tw = c.stringWidth(text, "Helvetica-Bold", size)
        if tw > width * 0.85:
            size = max(12, int(size * (width * 0.85) / tw))
        c.setFont("Helvetica-Bold", size)
        c.translate(width / 2, height / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, text)
    c.restoreState()
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


# --------------------------------------------------------------------------
# operations. Each returns a list of output records:
# {path, op, source, expected_pages, extra_check: callable(reader)->(ok, note)}
# Problems are appended to ctx["problems"] as plain strings.
# --------------------------------------------------------------------------

def _unique_path(outdir, name, used):
    stem, ext = os.path.splitext(name)
    cand, n = name, 2
    while cand in used or os.path.exists(os.path.join(outdir, cand)):
        cand = f"{stem}_{n}{ext}"
        n += 1
    used.add(cand)
    return os.path.join(outdir, cand)


def _open(path, ctx):
    """Open an input PDF. Returns PdfReader or None (problem recorded)."""
    if not os.path.isfile(path):
        ctx["problems"].append(f"input not found: {path}")
        return None
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            ctx["problems"].append(f"input is encrypted, skipped (no password support): {path}")
            return None
        _ = len(reader.pages)
        return reader
    except Exception as e:
        ctx["problems"].append(f"input could not be opened ({type(e).__name__}: {e}), skipped: {path}")
        return None


def _write(writer, outdir, name, ctx):
    path = _unique_path(outdir, name, ctx["used_names"])
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def op_split(op, ctx):
    src = _open(op["input"], ctx)
    if src is None:
        return []
    total = len(src.pages)
    stem = os.path.splitext(os.path.basename(op["input"]))[0]
    outs = []
    mode = op.get("mode", "ranges")
    if mode == "every":
        n = int(op["n"])
        if n < 1:
            ctx["problems"].append(f"split: 'every' must be >= 1 (got {n}) for {op['input']}")
            return []
        chunks = [(i + 1, min(i + n, total)) for i in range(0, total, n)]
        suffix = "part"
    else:
        try:
            chunks = parse_ranges(op["ranges"])
        except (KeyError, ValueError) as e:
            ctx["problems"].append(f"split: bad ranges for {op['input']}: {e}")
            return []
        for lo, hi in chunks:
            if lo < 1 or hi < lo or hi > total:
                ctx["problems"].append(
                    f"split: range {lo}-{hi} out of bounds (document has {total} pages) for {op['input']}")
                return []
        suffix = "p"
    for i, (lo, hi) in enumerate(chunks, 1):
        w = PdfWriter()
        for p in range(lo - 1, hi):
            w.add_page(src.pages[p])
        if mode == "every":
            name = f"{stem}_part{i:02d}.pdf"
        else:
            name = f"{stem}_p{lo}-{hi}.pdf"
        path = _write(w, ctx["outdir"], name, ctx)
        outs.append({"path": path, "op": f"split ({mode}) of {os.path.basename(op['input'])}",
                     "expected_pages": hi - lo + 1,
                     "conservation": (sum(h - l + 1 for l, h in chunks), total)})
    return outs


def op_merge(op, ctx):
    inputs = op["inputs"]
    readers = []
    total = 0
    for path in inputs:
        r = _open(path, ctx)
        if r is None:
            ctx["problems"].append(f"merge aborted: one input unusable, nothing merged ({path})")
            return []
        readers.append(r)
        total += len(r.pages)
    w = PdfWriter()
    for r in readers:
        for page in r.pages:
            w.add_page(page)
    name = op.get("output") or (os.path.splitext(os.path.basename(inputs[0]))[0] + "_merged.pdf")
    path = _write(w, ctx["outdir"], name, ctx)
    return [{"path": path, "op": "merge of " + ", ".join(os.path.basename(p) for p in inputs),
             "expected_pages": total, "conservation": (total, total)}]


def op_rotate(op, ctx):
    src = _open(op["input"], ctx)
    if src is None:
        return []
    total = len(src.pages)
    angle = int(op.get("angle", 90))
    if angle % 90 != 0:
        ctx["problems"].append(f"rotate: angle must be a multiple of 90 (got {angle}) for {op['input']}")
        return []
    try:
        targets = parse_page_spec(op.get("pages", "all"), total)
    except ValueError as e:
        ctx["problems"].append(f"rotate: {e} in {op['input']}")
        return []
    before = {i: (src.pages[i].rotation or 0) for i in targets}
    w = PdfWriter()
    for i, page in enumerate(src.pages):
        if i in targets:
            page.rotate(angle)
        w.add_page(page)
    stem = os.path.splitext(os.path.basename(op["input"]))[0]
    path = _write(w, ctx["outdir"], f"{stem}_rotated.pdf", ctx)

    def check(reader, before=before, targets=set(targets), angle=angle):
        bad = []
        for i in targets:
            want = (before[i] + angle) % 360
            got = reader.pages[i].rotation or 0
            if got != want:
                bad.append(f"page {i + 1}: rotation {got}, expected {want}")
        if bad:
            return False, "; ".join(bad[:3])
        return True, f"rotation verified on {len(targets)} page(s) (+{angle} deg)"

    return [{"path": path, "op": f"rotate {angle} deg of {os.path.basename(op['input'])}",
             "expected_pages": total, "extra_check": check}]


def op_extract(op, ctx):
    src = _open(op["input"], ctx)
    if src is None:
        return []
    total = len(src.pages)
    try:
        idx = parse_page_spec(op["pages"], total)
    except (KeyError, ValueError) as e:
        ctx["problems"].append(f"extract: {e} in {op['input']}")
        return []
    if not idx:
        ctx["problems"].append(f"extract: no pages selected for {op['input']}")
        return []
    w = PdfWriter()
    for i in idx:
        w.add_page(src.pages[i])
    stem = os.path.splitext(os.path.basename(op["input"]))[0]
    path = _write(w, ctx["outdir"], f"{stem}_extract.pdf", ctx)
    return [{"path": path, "op": f"extract pages {op['pages']} of {os.path.basename(op['input'])}",
             "expected_pages": len(idx)}]


def op_watermark(op, ctx):
    src = _open(op["input"], ctx)
    if src is None:
        return []
    text = str(op.get("text", "")).strip()
    if not text:
        ctx["problems"].append(f"watermark: empty text for {op['input']}")
        return []
    opacity = float(op.get("opacity", 0.25))
    if not (0 < opacity <= 1):
        ctx["problems"].append(f"watermark: opacity must be in (0, 1] (got {opacity}) for {op['input']}")
        return []
    position = str(op.get("position", "center")).lower()
    if position not in ("center", "top", "bottom"):
        ctx["problems"].append(f"watermark: position must be center/top/bottom (got '{position}')")
        return []
    overlays = {}

    def overlay_for(page):
        box = page.mediabox
        key = (round(float(box.width)), round(float(box.height)))
        if key not in overlays:
            overlays[key] = _watermark_overlay(text, float(box.width), float(box.height),
                                               opacity, position)
        return overlays[key]

    w = PdfWriter()
    for page in src.pages:
        page.merge_page(overlay_for(page))
        w.add_page(page)
    stem = os.path.splitext(os.path.basename(op["input"]))[0]
    path = _write(w, ctx["outdir"], f"{stem}_watermarked.pdf", ctx)

    def check(reader, text=text):
        missing = []
        for i, page in enumerate(reader.pages):
            try:
                found = text in (page.extract_text() or "")
            except Exception:
                found = False
            if not found:
                missing.append(i + 1)
        if missing:
            return False, f"watermark text not found on page(s) {missing[:5]}"
        return True, f"watermark text confirmed on all {len(reader.pages)} page(s)"

    return [{"path": path, "op": f"watermark '{text}' on {os.path.basename(op['input'])}",
             "expected_pages": len(src.pages), "extra_check": check}]


OPS = {"split": op_split, "merge": op_merge, "rotate": op_rotate,
       "extract": op_extract, "watermark": op_watermark}


# --------------------------------------------------------------------------
# verification pass — re-open every output and prove it
# --------------------------------------------------------------------------

def verify_output(rec):
    """Re-open one output file and check it. Returns (ok, notes list)."""
    notes = []
    try:
        reader = PdfReader(rec["path"])
        if reader.is_encrypted:
            return False, ["output is encrypted — cannot verify"]
        actual = len(reader.pages)
        # force-parse every page: catches truncated / malformed content
        for page in reader.pages:
            _ = page.mediabox
            page.extract_text()
    except Exception as e:
        return False, [f"output cannot be opened/parsed ({type(e).__name__}: {e})"]
    notes.append(f"opens and parses OK, {actual} page(s)")
    if actual != rec["expected_pages"]:
        return False, notes + [f"page count mismatch: expected {rec['expected_pages']}, got {actual}"]
    if "conservation" in rec:
        produced, source_total = rec["conservation"]
        notes.append(f"page conservation: operation accounts for {produced} of {source_total} source page(s)")
    if "extra_check" in rec:
        ok, note = rec["extra_check"](reader)
        notes.append(note)
        if not ok:
            return False, notes
    return True, notes


# --------------------------------------------------------------------------
# batch runner
# --------------------------------------------------------------------------

def run_pagesmith(job, outdir, base_dir="."):
    """Run a job dict {'operations': [...]} and verify every output.
    Writes pagesmith_report.md. Returns a summary dict."""
    os.makedirs(outdir, exist_ok=True)
    ctx = {"outdir": outdir, "problems": [], "used_names": set()}

    def resolve(p):
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    records = []
    for op in job.get("operations", []):
        kind = op.get("op")
        if kind not in OPS:
            ctx["problems"].append(f"unknown operation skipped: {kind!r}")
            continue
        op = dict(op)
        if "input" in op:
            op["input"] = resolve(op["input"])
        if "inputs" in op:
            op["inputs"] = [resolve(p) for p in op["inputs"]]
        try:
            records += OPS[kind](op, ctx)
        except Exception as e:
            ctx["problems"].append(f"operation {kind} failed ({type(e).__name__}: {e})")

    results = []
    for rec in records:
        ok, notes = verify_output(rec)
        results.append({"file": os.path.basename(rec["path"]), "op": rec["op"],
                        "ok": ok, "notes": notes})

    verified = sum(1 for r in results if r["ok"])
    failed = len(results) - verified
    lines = ["# PageSmith — batch operations & re-check report", "",
             f"Operations requested: {len(job.get('operations', []))}  ·  "
             f"Outputs produced: {len(results)}  ·  Verified: {verified}  ·  Failed: {failed}", "",
             "## Outputs (each one re-opened and re-checked after writing)"]
    if results:
        for r in results:
            lines.append(f"- [{'PASS' if r['ok'] else 'FAIL'}] {r['file']} — {r['op']}")
            for n in r["notes"]:
                lines.append(f"  - {n}")
    else:
        lines.append("- none")
    lines += ["", "## Problems (inputs skipped, nothing fabricated)"]
    lines += [f"- {p}" for p in ctx["problems"]] or ["- none"]
    verdict = "PASS" if failed == 0 and not ctx["problems"] else \
              ("PASS WITH PROBLEMS" if failed == 0 else "NOT READY")
    lines += ["", "## Re-check verdict",
              f"- {verdict}: {verified}/{len(results)} outputs verified"
              + (f", {len(ctx['problems'])} problem(s) reported above." if ctx["problems"] else ".")]
    report_path = os.path.join(outdir, "pagesmith_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"operations": len(job.get("operations", [])), "outputs": len(results),
            "verified": verified, "failed": failed,
            "problems": ctx["problems"], "report_path": report_path,
            "files": [r["file"] for r in results]}


def load_job(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _job_from_cli(argv):
    """Translate single-purpose CLI flags into a job dict.
    Returns (job, base_dir) or None if argv is a job-file invocation."""
    src, outdir = argv[1], argv[2]
    rest = argv[3:]

    def val(flag):
        return rest[rest.index(flag) + 1] if flag in rest else None

    if os.path.isdir(src) and "--merge-all" in rest:
        pdfs = sorted(f for f in os.listdir(src) if f.lower().endswith(".pdf"))
        if not pdfs:
            raise SystemExit(f"no PDF files in folder: {src}")
        return {"operations": [{"op": "merge",
                                 "inputs": [os.path.join(src, f) for f in pdfs],
                                 "output": "merged_all.pdf"}]}, "."
    if "--split-every" in rest:
        op = {"op": "split", "input": src, "mode": "every", "n": int(val("--split-every"))}
    elif "--split-ranges" in rest:
        op = {"op": "split", "input": src, "mode": "ranges", "ranges": val("--split-ranges")}
    elif "--extract" in rest:
        op = {"op": "extract", "input": src, "pages": val("--extract")}
    elif "--rotate" in rest:
        op = {"op": "rotate", "input": src, "angle": int(val("--rotate")),
              "pages": val("--pages") or "all"}
    elif "--watermark" in rest:
        op = {"op": "watermark", "input": src, "text": val("--watermark"),
              "opacity": float(val("--opacity") or 0.25),
              "position": val("--position") or "center"}
    else:
        return None
    return {"operations": [op]}, "."


def main(argv):
    if len(argv) < 3:
        print(__doc__.split("Usage:")[1].strip())
        return 2
    built = _job_from_cli(argv)
    if built is not None:
        job, base_dir = built
        outdir = argv[2]
    elif argv[1].lower().endswith(".json"):
        job = load_job(argv[1])
        base_dir = os.path.dirname(os.path.abspath(argv[1]))
        outdir = argv[2]
    else:
        print("error: give a job .json file, or a PDF/folder plus an operation flag")
        return 2
    s = run_pagesmith(job, outdir, base_dir=base_dir)
    print(f"operations={s['operations']} outputs={s['outputs']} verified={s['verified']} "
          f"failed={s['failed']} problems={len(s['problems'])}")
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
