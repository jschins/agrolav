"""Reminder pass. It is not called from a page request."""
from __future__ import annotations

import os
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from app.ledger import (
    open_invoices,
    read_incoming_bookings,
    record_reminder,
    reminder_body,
    sent_steps,
    steps_due,
    sync_payments,
)
from app.orders import connect

_ROOT = Path(__file__).resolve().parent.parent


def send_message(sender: str, recipient: str, subject: str, body: str, copy: str = "") -> None:
    host = os.environ.get("SHOP_SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SHOP_SMTP_HOST is not set")
    port = int(os.environ.get("SHOP_SMTP_PORT", "587"))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    if copy and copy.lower() != recipient.lower():
        message["Cc"] = copy
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        username = os.environ.get("SHOP_SMTP_USER", "").strip()
        password = os.environ.get("SHOP_SMTP_PASSWORD", "").strip()
        if username:
            smtp.starttls()
            smtp.login(username, password)
        smtp.send_message(message)


def send_reminder(invoice, body: str, sender: str) -> None:
    send_message(sender, invoice.email, f"Factuur {invoice.number}", body)


def send_code_request(contact: str, email: str, code: str) -> None:
    """Send the bestelcode to the contact, with a copy to the shop."""
    sender = os.environ.get("SHOP_CODE_MAIL_FROM", "j.m.schins@gmail.com").strip() or "j.m.schins@gmail.com"
    copy = os.environ.get("SHOP_CODE_MAIL_CC", "j.m.schins@gmail.com").strip() or "j.m.schins@gmail.com"
    try:
        send_message(
            sender,
            email,
            "Uw bestelcode",
            (
                f"Geachte {contact}:\n"
                "\n"
                "Uw bestelcode voor het bestellen op rekening bij Uitgeverij De Boog is\n"
                f"{code}\n"
                "\n"
                "Met deze code kunt u uw bestellingen plaatsen. Wij vertrouwen erop dat u de rekeningen uiterlijk binnen één maand na ontvangst van de facturen betaalt; uiteraard, mits de bestelde boeken daadwerkelijk zijn geleverd.\n"
            ),
            copy,
        )
    except smtplib.SMTPException as exc:
        raise RuntimeError("mail failed") from exc


def run(today: date | None = None, db_path: Path | None = None) -> int:
    today = today or date.today()
    path = db_path or Path(os.environ.get("SHOP_DATA_DIR", str(_ROOT / "data"))) / "orders.sqlite"
    if db_path is not None:
        path = db_path
    iban = os.environ.get("SHOP_BOOG_IBAN", "").strip()
    sender = os.environ.get("SHOP_MAIL_FROM", "info@deboog.nl").strip()
    conn = connect(path if db_path is not None else path)
    sent = 0
    try:
        if iban:
            sync_payments(conn, read_incoming_bookings(iban))
        already = sent_steps(conn)
        when = datetime.now()
        for invoice in open_invoices(conn):
            current = invoice
            for step in steps_due(current, today, already):
                refreshed = open_invoices(conn)
                current = next((item for item in refreshed if item.number == invoice.number), current)
                if current.open_cents <= 0:
                    break
                body = reminder_body(current, iban)
                send_reminder(current, body, sender)
                record_reminder(conn, current, step, when)
                already.add((current.number, step))
                sent += 1
    finally:
        conn.close()
    return sent
