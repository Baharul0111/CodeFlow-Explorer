"""Write the finished HTML file."""
from html import escape

TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Sales report</title></head>
<body>
<h1>Sales report</h1>
{summary}
<h2>Every month</h2>
{months}
<h2>Best products</h2>
{products}
</body>
</html>
"""


def money(pence):
    return f"£{pence / 100:,.2f}"


def render_months(totals):
    rows = "".join(
        f"<tr><td>{escape(item['month'])}</td><td>{money(item['pence'])}</td>"
        f"<td>{item['units']}</td><td>{money(item['average_pence'])}</td></tr>"
        for item in totals
    )
    return f"<table><tr><th>Month</th><th>Money</th><th>Units</th><th>Average order</th></tr>{rows}</table>"


def render_products(best):
    items = "".join(
        f"<li>{escape(item['product'])} — {money(item['pence'])}</li>" for item in best
    )
    return f"<ol>{items}</ol>"


def write_html(path, totals, best, dropped, skipped):
    """Put the whole report together and save it."""
    summary = (
        f"<p>{len(totals)} months. {dropped} rows were unusable. "
        f"{len(skipped)} files were skipped.</p>"
    )
    path.write_text(
        TEMPLATE.format(
            summary=summary, months=render_months(totals), products=render_products(best)
        ),
        encoding="utf-8",
    )
    return path
