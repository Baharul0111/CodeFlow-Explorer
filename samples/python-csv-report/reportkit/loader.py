"""Find CSV files and read them into plain dictionaries."""
import csv

EXPECTED_COLUMNS = {"date", "product", "region", "units", "price"}


def find_csv_files(folder):
    """Every .csv file in the folder, in a steady order."""
    return sorted(path for path in folder.glob("*.csv") if path.is_file())


def read_csv(path):
    """Read one file, returning its rows and whether its columns looked right."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        if not EXPECTED_COLUMNS.issubset(columns):
            return [], False
        return [dict(row, _source=path.name) for row in reader], True


def load_folder(folder, min_rows=1):
    """Read every CSV file, skipping ones that are too short or have the wrong columns."""
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder")
    rows = []
    skipped = []
    for path in find_csv_files(folder):
        file_rows, ok = read_csv(path)
        if not ok:
            skipped.append({"file": path.name, "why": "unexpected columns"})
            continue
        if len(file_rows) < min_rows:
            skipped.append({"file": path.name, "why": "too few rows"})
            continue
        rows.extend(file_rows)
    return rows, skipped
