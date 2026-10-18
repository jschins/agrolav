"""PDF rendering for invoices sent by the shop administrator."""
from __future__ import annotations

from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.catalog import Catalog, euro, vat_cents
from app.ledger import Invoice


def _safe_text(value: object) -> str:
    """Keep text representable by ReportLab's built-in WinAnsi fonts."""
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_safe_text(value)), style)


def build_invoice_pdf(invoice: Invoice, catalog: Catalog, iban: str = "") -> bytes:
    """Render a compact, printable invoice and return its PDF bytes."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Factuur {invoice.number}",
        author=catalog.shop_name or "Uitgeverij De Boog",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Title"], alignment=TA_RIGHT, textColor=colors.HexColor("#39245f")
    )
    small_style = ParagraphStyle("InvoiceSmall", parent=styles["Normal"], fontSize=9, leading=12)
    story = []

    issuer = [catalog.shop_name or "Uitgeverij De Boog"]
    if catalog.place:
        issuer.append(catalog.place)
    story.append(
        Table(
            [[Paragraph(f"<b>{escape(_safe_text(issuer[0]))}</b>", small_style), _paragraph(f"Factuur {invoice.number}", title_style)]],
            colWidths=[95 * mm, 75 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]),
        )
    )
    if len(issuer) > 1:
        story.append(Paragraph("<br/>".join(escape(_safe_text(line)) for line in issuer[1:]), small_style))
    story.append(Spacer(1, 12 * mm))

    recipient = [invoice.name]
    if invoice.address:
        recipient.extend(part.strip() for part in invoice.address.split(",") if part.strip())
    if invoice.email:
        recipient.append(invoice.email)
    if invoice.vat_number:
        recipient.append(f"BTW-nummer: {invoice.vat_number}")
    story.append(Paragraph("<b>Factuur aan</b>", small_style))
    story.append(Paragraph("<br/>".join(escape(_safe_text(line)) for line in recipient), small_style))
    story.append(Spacer(1, 8 * mm))

    details = [
        ["Factuurnummer", invoice.number, "Factuurdatum", _safe_text(invoice.ordered_at)[:10]],
        ["Vervaldatum", invoice.due_on.isoformat(), "E-mail", invoice.email],
    ]
    detail_table = Table(details, colWidths=[29 * mm, 56 * mm, 29 * mm, 56 * mm])
    detail_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#5c5364")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#5c5364")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([detail_table, Spacer(1, 8 * mm)])

    book_titles = {book.slug: book.titel for book in catalog.books}
    rows = [["Omschrijving", "Aantal", "Prijs per stuk", "Totaal"]]
    for line in invoice.lines:
        line_total = line.number_of_copies * line.price_cents_per_copy
        rows.append(
            [
                _paragraph(book_titles.get(line.slug, line.slug), small_style),
                str(line.number_of_copies),
                euro(line.price_cents_per_copy),
                euro(line_total),
            ]
        )
    line_table = Table(rows, colWidths=[79 * mm, 20 * mm, 35 * mm, 36 * mm], repeatRows=1)
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eee9f4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#302047")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c8bdcf")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([line_table, Spacer(1, 6 * mm)])

    tax_cents = (
        int(invoice.portokosten_cents)
        if invoice.portokosten_cents is not None
        else vat_cents(invoice.payable_cents, catalog.vat_rate)
    )
    totals = [
        ["Totaal inclusief btw", euro(invoice.payable_cents)],
        [catalog.vat_label or "Btw inbegrepen", euro(tax_cents)],
        ["Openstaand bedrag", euro(invoice.open_cents)],
    ]
    totals_table = Table(totals, colWidths=[135 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("LINEABOVE", (0, 2), (-1, 2), 0.6, colors.HexColor("#39245f")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(totals_table)

    if iban and invoice.open_cents > 0:
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph("<b>Betalen</b>", small_style))
        story.append(
            _paragraph(
                f"Maak het openstaande bedrag over naar IBAN {_safe_text(iban)} en vermeld "
                f"factuurnummer {_safe_text(invoice.number)} bij de betaling.",
                small_style,
            )
        )
    document.build(story)
    return output.getvalue()
