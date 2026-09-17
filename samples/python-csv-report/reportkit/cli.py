"""Command line entry point: read arguments, run the pipeline, write the report."""
import argparse
import sys
from pathlib import Path

from reportkit.loader import load_folder
from reportkit.cleaner import clean_rows
from reportkit.summary import monthly_totals, top_products
from reportkit.report import write_html


def build_parser():
    parser = argparse.ArgumentParser(description="Turn CSV sales files into one HTML report.")
    parser.add_argument("folder", help="Folder holding the CSV files")
    parser.add_argument("--out", default="report.html", help="Where to write the report")
    parser.add_argument("--min-rows", type=int, default=1, help="Skip files with fewer rows")
    parser.add_argument("--quiet", action="store_true", help="Do not print progress")
    return parser


def run(folder, out_path, min_rows, quiet=False):
    """The whole job: load, clean, add up, write."""
    rows, skipped = load_folder(Path(folder), min_rows=min_rows)
    if not rows:
        raise SystemExit("No usable rows were found in that folder.")
    cleaned, dropped = clean_rows(rows)
    totals = monthly_totals(cleaned)
    best = top_products(cleaned, limit=5)
    write_html(Path(out_path), totals=totals, best=best, dropped=dropped, skipped=skipped)
    if not quiet:
        print(f"Wrote {out_path}: {len(cleaned)} rows, {len(totals)} months")
    return {"rows": len(cleaned), "months": len(totals), "dropped": dropped, "skipped": skipped}


def main(argv=None):
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    try:
        run(args.folder, args.out, args.min_rows, args.quiet)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - the CLI must never show a traceback
        print(f"Could not build the report: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
