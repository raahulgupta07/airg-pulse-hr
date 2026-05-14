"""Generate senior CV PDFs from fixtures via reportlab."""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT

from tests.api.seniors_data import SENIORS

OUT = Path("tests/seniors_pdf")
OUT.mkdir(parents=True, exist_ok=True)


def build_pdf(senior: dict) -> Path:
    safe = senior["name"].replace(" ", "_")
    path = OUT / f"{safe}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter,
                            leftMargin=0.7*inch, rightMargin=0.7*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    s = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=s["Heading1"], fontSize=18, spaceAfter=4, textColor="#222")
    sub = ParagraphStyle("sub", parent=s["Normal"], fontSize=11, textColor="#555", spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=s["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor="#000")
    body = ParagraphStyle("body", parent=s["Normal"], fontSize=10, leading=14, alignment=TA_LEFT)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=0)

    flow = []
    flow.append(Paragraph(senior["name"], h1))
    flow.append(Paragraph(
        f"{senior['title']} · {senior['company']} · {senior['location']}<br/>"
        f"{senior['email']} · {senior['phone']} · {senior['years']} years experience",
        sub))

    flow.append(Paragraph("SUMMARY", h2))
    flow.append(Paragraph(senior["summary"], body))

    flow.append(Paragraph("SKILLS", h2))
    flow.append(Paragraph(", ".join(senior["skills"]), body))

    flow.append(Paragraph("EXPERIENCE", h2))
    for title, company, dates, desc in senior["experience"]:
        flow.append(Paragraph(f"<b>{title}</b> — {company} <i>({dates})</i>", body))
        flow.append(Paragraph(desc, bullet))
        flow.append(Spacer(1, 4))

    flow.append(Paragraph("EDUCATION", h2))
    for deg, school, dates in senior["education"]:
        flow.append(Paragraph(f"<b>{deg}</b> — {school} <i>({dates})</i>", body))

    if senior.get("certs"):
        flow.append(Paragraph("CERTIFICATIONS", h2))
        for c in senior["certs"]:
            flow.append(Paragraph(f"• {c}", body))

    doc.build(flow)
    return path


def build_all():
    paths = []
    for s in SENIORS:
        p = build_pdf(s)
        paths.append(p)
        print(f"  ✓ {p.name}")
    return paths


if __name__ == "__main__":
    print(f"Building {len(SENIORS)} senior CV PDFs into {OUT}/")
    build_all()
    print("Done.")
