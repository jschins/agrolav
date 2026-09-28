"""One-off: Dutch part of login.md -> documentation/login.pdf."""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "login.md"
OUT = ROOT / "login.pdf"
FONT = Path(r"C:\Windows\Fonts\segoeui.ttf")
FONT_B = Path(r"C:\Windows\Fonts\segoeuib.ttf")
MONO = Path(r"C:\Windows\Fonts\consola.ttf")


def dutch_text() -> str:
    text = SRC.read_text(encoding="utf-8")
    return text.split("\n## Browser path", 1)[0].strip() + "\n"


def parse_html_table(html: str) -> list[list[tuple[str, int]]]:
    rows: list[list[tuple[str, int]]] = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells: list[tuple[str, int]] = []
        for attrs, body in re.findall(r"<t[hd]([^>]*)>(.*?)</t[hd]>", tr, re.S):
            span_m = re.search(r'colspan="(\d+)"', attrs)
            span = int(span_m.group(1)) if span_m else 1
            text = re.sub(r"<[^>]+>", "", body)
            text = re.sub(r"\s+", " ", text).strip()
            cells.append((text, span))
        if cells:
            rows.append(cells)
    return rows


def parse_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        if not line.strip().startswith("|"):
            break
        if re.match(r"^\|\s*-+", line.strip()):
            continue
        cells = [c.strip().replace("`", "") for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


class Doc(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4")
        self.add_font("Segoe", "", str(FONT))
        self.add_font("Segoe", "B", str(FONT_B))
        self.add_font("Consolas", "", str(MONO))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(16, 16, 16)

    def h1(self, text: str) -> None:
        self.ln(2)
        self.set_font("Segoe", "B", 16)
        self.multi_cell(0, 8, text)
        self.ln(2)

    def h2(self, text: str) -> None:
        self.ln(3)
        self.set_font("Segoe", "B", 13)
        self.multi_cell(0, 7, text)
        self.ln(1)

    def para(self, text: str) -> None:
        self.set_font("Segoe", "", 11)
        self.multi_cell(0, 6, text)
        self.ln(1.5)

    def bullet(self, text: str) -> None:
        self.set_font("Segoe", "", 11)
        x = self.l_margin
        self.set_x(x)
        self.multi_cell(0, 6, "•  " + text)
        self.ln(0.6)

    def draw_spanned(self, rows: list[list[tuple[str, int]]]) -> None:
        """Instudo: first column left; login names centered, with colspans."""
        if not rows:
            return
        width = self.w - self.l_margin - self.r_margin
        weights = (1.3, 1.15, 1.15, 1.15, 1.15)
        total = sum(weights)
        widths = [width * w / total for w in weights]
        line_h = 6
        self.set_draw_color(180, 180, 180)
        for ri, row in enumerate(rows):
            bold = ri == 0
            self.set_font("Segoe", "B" if bold else "", 9)
            spans = []
            col = 0
            for text, span in row:
                spans.append((text, col, span))
                col += span
            heights = []
            for text, col, span in spans:
                cell_w = sum(widths[col:col + span]) - 2
                n = max(1, len(self.multi_cell(cell_w, line_h, text or " ", dry_run=True, output="LINES")))
                heights.append(n * line_h + 2)
            row_h = max(heights)
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
            y0 = self.get_y()
            x = self.l_margin
            for text, col, span in spans:
                cell_w = sum(widths[col:col + span])
                align = "L" if col == 0 else "C"
                self.set_xy(x, y0)
                self.rect(x, y0, cell_w, row_h)
                self.set_xy(x + 1, y0 + 1)
                self.multi_cell(
                    cell_w - 2,
                    line_h,
                    text,
                    align=align,
                    new_x=XPos.RIGHT,
                    new_y=YPos.TOP,
                )
                x += cell_w
            self.set_xy(self.l_margin, y0 + row_h)
        self.ln(3)

    def draw_table(self, rows: list[list[str]], center_col: int | None) -> None:
        if not rows:
            return
        width = self.w - self.l_margin - self.r_margin
        cols = max(len(r) for r in rows)
        for row in rows:
            while len(row) < cols:
                row.append("")
        if cols == 5:
            weights = (1.3, 1.15, 1.15, 1.15, 1.15)
        elif cols == 3:
            weights = (1.1, 2.2, 1.4)
        else:
            weights = tuple(1 for _ in range(cols))
        total = sum(weights)
        widths = [width * w / total for w in weights]
        line_h = 6
        self.set_draw_color(180, 180, 180)
        self.set_font("Segoe", "", 9)
        for ri, row in enumerate(rows):
            bold = ri == 0
            self.set_font("Segoe", "B" if bold else "", 9)
            heights = []
            for ci, cell in enumerate(row):
                self.set_font("Segoe", "B" if bold else "", 9)
                n = max(1, len(self.multi_cell(widths[ci] - 2, line_h, cell or " ", dry_run=True, output="LINES")))
                heights.append(n * line_h + 2)
            row_h = max(heights)
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
            y0 = self.get_y()
            x = self.l_margin
            for ci, cell in enumerate(row):
                align = "C" if center_col is not None and ci == center_col else "L"
                self.set_xy(x, y0)
                self.rect(x, y0, widths[ci], row_h)
                self.set_xy(x + 1, y0 + 1)
                self.multi_cell(
                    widths[ci] - 2,
                    line_h,
                    cell,
                    align=align,
                    new_x=XPos.RIGHT,
                    new_y=YPos.TOP,
                )
                x += widths[ci]
            self.set_xy(self.l_margin, y0 + row_h)
        self.ln(3)


def main() -> None:
    pdf = Doc()
    pdf.add_page()
    lines = dutch_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            pdf.h1(line[2:].strip())
            i += 1
        elif line.startswith("## "):
            pdf.h2(line[3:].strip())
            i += 1
        elif "<table" in line:
            block = [line]
            i += 1
            while i < len(lines) and "</table>" not in lines[i - 1]:
                block.append(lines[i])
                i += 1
            pdf.draw_spanned(parse_html_table("\n".join(block)))
        elif line.strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows = parse_table(block)
            header = rows[0] if rows else []
            center = 1 if any(c.lower().startswith("login-namen") for c in header) else None
            pdf.draw_table(rows, center)
        elif line.strip().startswith("- "):
            pdf.bullet(re.sub(r"\*\*(.+?)\*\*", r"\1", line.strip()[2:]))
            i += 1
        elif line.strip() in {"", "---"}:
            i += 1
        else:
            parts = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].strip().startswith("|") and not lines[i].strip().startswith("- ") and lines[i].strip() != "---":
                parts.append(lines[i].strip())
                i += 1
            text = re.sub(r"`([^`]+)`", r"\1", " ".join(parts))
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            pdf.para(text)
    pdf.output(str(OUT))
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
