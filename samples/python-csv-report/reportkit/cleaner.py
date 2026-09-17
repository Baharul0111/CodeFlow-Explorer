"""Fix up messy rows and throw away ones that cannot be used."""
from datetime import date, datetime

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y")


def parse_date(text):
    """Understand the three date styles the shops use; give back None for anything else."""
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), pattern).date()
        except (ValueError, AttributeError):
            continue
    return None


def parse_money(text):
    """Turn '£12.50' or '12,50' into pennies."""
    if text is None:
        return None
    cleaned = str(text).replace("£", "").replace("$", "").replace(",", ".").strip()
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return None


def clean_row(row):
    """Return a tidy row, or None when something important is missing."""
    sold_on = parse_date(row.get("date", ""))
    price = parse_money(row.get("price"))
    try:
        units = int(str(row.get("units", "")).strip() or 0)
    except ValueError:
        return None
    if sold_on is None or price is None or units <= 0:
        return None
    if sold_on > date.today():
        return None
    return {
        "date": sold_on,
        "product": (row.get("product") or "unknown").strip().title(),
        "region": (row.get("region") or "unknown").strip().upper(),
        "units": units,
        "pence": price * units,
        "source": row.get("_source", ""),
    }


def clean_rows(rows):
    """Clean every row and count the ones that had to be dropped."""
    cleaned = []
    dropped = 0
    for row in rows:
        tidy = clean_row(row)
        if tidy is None:
            dropped += 1
            continue
        cleaned.append(tidy)
    return cleaned, dropped
