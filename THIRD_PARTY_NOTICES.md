# Third-party notices

PageSmith PDF includes the following open-source components:

- **pypdf** — BSD-3-Clause License (full text in PYPDF_LICENSE.txt).
  https://pypdf.readthedocs.io
- **reportlab** — BSD License. https://www.reportlab.com
  Used only to draw the watermark overlay layer.
- **Pillow** — HPND License. https://python-pillow.org
  Transitive dependency of reportlab; no Pillow code paths are used by
  PageSmith itself beyond reportlab internals.

The PageSmith batch engine, verification (re-check) layer and GUI are our
own work. No AGPL components are used.
