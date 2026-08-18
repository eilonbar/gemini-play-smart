"""Render an article figure from HTML to a PNG.

The illustrations are authored as HTML/CSS rather than drawn, so the numbers in
them stay editable and reviewable in a diff like every other claim in this repo.

    python docs/render_concept.py             # docs/concept.html  -> concept.png
    python docs/render_concept.py depth_sweep # docs/depth_sweep.html -> .png

Requires ``weasyprint`` (HTML to PDF) and ``pymupdf`` (PDF to PNG), neither of
which is a runtime dependency of ``play_smart``:

    pip install weasyprint pymupdf
"""

from __future__ import annotations

import argparse
import pathlib

HERE = pathlib.Path(__file__).parent

#: Medium serves images up to ~1400px wide and doubles that on retina screens.
#: The pages are 800pt, so 2.5x lands at 2000px.
SCALE = 2.5


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("figure", nargs="?", default="concept")
    parser.add_argument("--scale", type=float, default=SCALE)
    parser.add_argument("--keep-pdf", action="store_true")
    args = parser.parse_args()

    source = HERE / f"{args.figure}.html"
    pdf = HERE / f"{args.figure}.pdf"
    png = HERE / f"{args.figure}.png"
    if not source.exists():
        raise SystemExit(f"no such figure: {source}")

    import fitz
    from weasyprint import HTML

    HTML(filename=str(source)).write_pdf(str(pdf))

    with fitz.open(str(pdf)) as doc:
        if len(doc) != 1:
            raise SystemExit(f"expected one page, got {len(doc)} -- content overflowed")
        pixmap = doc[0].get_pixmap(matrix=fitz.Matrix(args.scale, args.scale))
        pixmap.save(str(png))

    if not args.keep_pdf:
        pdf.unlink(missing_ok=True)

    print(f"{png}  {pixmap.width}x{pixmap.height}  {png.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
