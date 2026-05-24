from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import tempfile
import os
from datetime import datetime


def generate_invoice(user_name, plan_label, amount, method, trx_id):
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = SimpleDocTemplate(tmp.name, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph("🎤 MS Voice Bot", styles["Title"]))
    elements.append(Paragraph("Payment Invoice", styles["Heading2"]))
    elements.append(Spacer(1, 20))

    # Invoice data
    data = [
        ["Field", "Details"],
        ["Customer", user_name],
        ["Plan", plan_label],
        ["Amount", f"BDT {amount}"],
        ["Payment Method", method.upper()],
        ["Transaction ID", trx_id],
        ["Date", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")],
        ["Status", "✅ Verified"],
    ]

    table = Table(data, colWidths=[150, 300])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Thank you for your purchase! 🎤", styles["Normal"]))

    doc.build(elements)
    return tmp.name
