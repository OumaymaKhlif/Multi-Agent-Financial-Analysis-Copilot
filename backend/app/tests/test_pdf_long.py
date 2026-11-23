from app.services.pdf_report import report_to_pdf


# Un long rapport (plusieurs dizaines de pages) produit un PDF valide
def test_pdf_long_report():
    markdown = "## Section\n- Revenue : 331 839 M USD, croissance 17,79 %\n" * 300
    pdf = report_to_pdf(markdown)
    assert pdf.startswith(b"%PDF") and len(pdf) > 10_000
