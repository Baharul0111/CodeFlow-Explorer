"""Add the clean rows up into the numbers the report shows."""
from collections import defaultdict


def month_key(row):
    return row["date"].strftime("%Y-%m")


def monthly_totals(rows):
    """Money and units for each month, oldest first."""
    buckets = defaultdict(lambda: {"pence": 0, "units": 0, "orders": 0})
    for row in rows:
        bucket = buckets[month_key(row)]
        bucket["pence"] += row["pence"]
        bucket["units"] += row["units"]
        bucket["orders"] += 1
    return [
        {"month": month, **values, "average_pence": values["pence"] // max(values["orders"], 1)}
        for month, values in sorted(buckets.items())
    ]


def top_products(rows, limit=5):
    """The products that brought in the most money."""
    totals = defaultdict(int)
    for row in rows:
        totals[row["product"]] += row["pence"]
    ranked = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
    return [{"product": name, "pence": pence} for name, pence in ranked[:limit]]
