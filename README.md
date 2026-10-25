# PageSmith PDF — Batch Page Operations & Re-Check

PageSmith runs PDF page operations on **whole batches** — a folder of scans,
contracts or statements processed by rule in one run, not one file opened
and clicked at a time — then **re-opens and verifies every output** and
writes a plain-English report. 100% local: legal and financial documents
never leave your computer, no account, no subscription, no upload.

## What it does
- **Split** — by page ranges (`1-3,4-6,7-10`) or every N pages
- **Merge** — any number of PDFs, in the order you list them
- **Rotate** — all pages or a page selection, by 90/180/270 degrees
- **Extract** — pull pages (`2,4-5`) into a new file
- **Text watermark** — adjustable opacity, center (diagonal), top or bottom

## The re-check (the part other tools skip)
After writing, every output file is re-opened and force-parsed page by
page. The report confirms: the file opens, the page count matches, the
operation's page conservation adds up (split parts sum back to the source,
a merge equals the sum of its inputs), rotated pages really carry the new
rotation, and the watermark text is really present on every page. Inputs
that cannot be opened (corrupt, encrypted) are listed as problems and
skipped — never silently dropped, never "repaired" by guessing.

## Verified behaviour
Seeded acceptance suite (a 10-page document plus a 4-page document with a
blank page and a pre-rotated page): one batch of 6 operations produced 10
outputs — split 3/3/4 and 4/4/2 with page conservation 10, merge 10+4 = 14
with order verified, rotate +90° landing exactly (including +90° on top of
the pre-rotated page = 180°), extract returning exactly pages 2, 4, 5,
watermark confirmed on all 10 pages. The re-check caught a deliberately
truncated output, a fake PDF, and a page-count mismatch. A corrupt input
and a missing input were both reported while the valid operation in the
same batch still completed. **20 of 20 acceptance checks pass.**

## Run from source
```
pip install -r requirements.txt
python page_smith.py job.json output_folder          # batch job file
python page_smith.py in.pdf output_folder --split-every 2
python page_smith.py in.pdf output_folder --split-ranges 1-3,4-6
python page_smith.py in.pdf output_folder --extract 2,4-5
python page_smith.py in.pdf output_folder --rotate 90 --pages 1-3
python page_smith.py in.pdf output_folder --watermark "CONFIDENTIAL" --opacity 0.25 --position center
python page_smith.py folder output_folder --merge-all
```
A job file is a JSON list of operations, e.g.
`{"operations": [{"op": "split", "input": "a.pdf", "mode": "ranges", "ranges": "1-3,4-6"},
{"op": "merge", "inputs": ["a.pdf", "b.pdf"]},
{"op": "watermark", "input": "a.pdf", "text": "DRAFT", "opacity": 0.3, "position": "center"}]}`.
Every run writes `pagesmith_report.md` next to the outputs. The Windows app
(`gui.py`, packaged with PyInstaller) wraps the same engine.

## Scope
Page operations only. PageSmith does not edit PDF content (text/images),
OCR, fill forms, or repair broken PDF structure — files pypdf cannot open
are reported as failed in the report, not forced.

## License notes
Engine: pypdf (BSD-3-Clause) + reportlab (BSD) — see THIRD_PARTY_NOTICES.md.
