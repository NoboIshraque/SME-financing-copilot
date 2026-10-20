"""Export the submission documents to PDF with headless Chromium (WP-19).

    uv run --no-project --with markdown python scripts/export_submission_pdfs.py [--chrome PATH]

Writes docs/submission/pdf/: technical-documentation.pdf, security-self-assessment.pdf (A4, from
the Markdown) and deck.pdf (one 1920x1080 page per slide, in deck.json order, speaker notes left
out). Fonts the slides name are not fetched: install Space Grotesk, IBM Plex Sans and Noto Sans
Bengali locally first, or the system fallback is used. The slides were written for the claude.ai
Slides runtime, which resets default margins and draws `<x-connector>` arrows; both are replayed
here (CSS reset, connectors redrawn as inline SVG) so the PDF matches the deck.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "docs" / "submission"
OUT = SUB / "pdf"

DOC_CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Noto Sans', 'Noto Sans Bengali', 'Noto Sans CJK SC', Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.45; color: #111; }
h1 { font-size: 20pt; } h2 { font-size: 15pt; border-bottom: 1px solid #ccc; }
h3 { font-size: 12.5pt; } code, pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.5pt; }
pre { background: #f5f5f5; padding: 8px; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 8px 0; }
th, td { border: 1px solid #bbb; padding: 4px 6px; vertical-align: top; }
th { background: #eee; }
"""

DECK_CSS = """
@page { size: 1920px 1080px; margin: 0; }
html, body { margin: 0; padding: 0; }
section { width: 1920px; height: 1080px; box-sizing: border-box; position: relative;
          overflow: hidden; page-break-after: always; break-after: page; }
aside { display: none; }
section h1, section h2, section h3, section p, section ul, section ol, section table { margin: 0; }
section ul, section ol { padding-left: 1.2em; }
section li + li { margin-top: 8px; }
section table { border-collapse: collapse; width: 100%; }
section th, section td { padding: 14px 16px; border-bottom: 1px solid #E2DED2; vertical-align: top; }
section th { border-bottom: 2px solid #12211D; }
section hr { border: none; margin: 0; height: 0; width: 100%; align-self: stretch; }
"""

CONNECTOR = re.compile(r"<x-connector([^>]*)></x-connector>")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def _style(style: str, key: str, default: str) -> str:
    found = re.search(rf"(?:^|;)\s*{key}\s*:\s*([^;]+)", style)
    return found.group(1).strip() if found else default


def _arrow(match: re.Match[str]) -> str:
    """One `<x-connector>` as inline SVG: a positioned line, or an inline flow arrow."""
    attrs = dict(ATTR.findall(match.group(1)))
    style = attrs.get("style", "")
    color = _style(style, "color", "#12211D")
    width = _style(style, "border-width", "3px").removesuffix("px")
    marker = (f'<defs><marker id="a{match.start()}" viewBox="0 0 10 10" refX="9" refY="5" '
              f'markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
              f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker></defs>')
    head = f'marker-end="url(#a{match.start()})"'
    if "x1" in attrs:
        return (f'<svg style="position:absolute;left:0;top:0;width:100%;height:100%;'
                f'overflow:visible;pointer-events:none">{marker}'
                f'<line x1="{attrs["x1"]}" y1="{attrs["y1"]}" x2="{attrs["x2"]}" '
                f'y2="{attrs["y2"]}" stroke="{color}" stroke-width="{width}" {head}/></svg>')
    length = int(_style(style, "width", "56px").removesuffix("px"))
    return (f'<svg width="{length}" height="24" style="flex:none;align-self:center">{marker}'
            f'<line x1="0" y1="12" x2="{length - 2}" y2="12" stroke="{color}" '
            f'stroke-width="{width}" {head}/></svg>')


def find_chrome(given: str | None) -> str:
    for candidate in (given, shutil.which("chromium"), shutil.which("google-chrome"),
                      "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("no Chromium found; pass --chrome PATH")


def print_pdf(chrome: str, html: str, target: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                        "--no-pdf-header-footer", f"--print-to-pdf={target}", page.as_uri()],
                       check=True, capture_output=True, timeout=180)


def doc_html(source: Path) -> str:
    body = markdown.markdown(source.read_text(encoding="utf-8"),
                             extensions=["tables", "fenced_code", "toc", "sane_lists"])
    return f"<!doctype html><meta charset='utf-8'><style>{DOC_CSS}</style>{body}"


def deck_html() -> str:
    deck = json.loads((SUB / "deck" / "deck.json").read_text(encoding="utf-8"))
    slides = [(SUB / "deck" / "slides" / f"{sid}.html").read_text(encoding="utf-8")
              for sid in deck["order"]]
    body = "\n".join(CONNECTOR.sub(_arrow, re.sub(r"<aside>.*?</aside>", "", s, flags=re.S))
                     for s in slides)
    return (f"<!doctype html><meta charset='utf-8'><title>{deck['title']}</title>"
            f"<style>{DECK_CSS}</style>{body}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome")
    chrome = find_chrome(parser.parse_args().chrome)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("technical-documentation", "security-self-assessment"):
        print_pdf(chrome, doc_html(SUB / f"{name}.md"), OUT / f"{name}.pdf")
    print_pdf(chrome, deck_html(), OUT / "deck.pdf")
    for pdf in sorted(OUT.glob("*.pdf")):
        print(f"{pdf.relative_to(ROOT)}  {pdf.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
