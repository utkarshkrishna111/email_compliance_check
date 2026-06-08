import csv
from pathlib import Path

INPUT_PATH  = "data/employees.csv"
COLUMN      = "Name"
NAMES       = ["Alice", "Bob", "Charlie"]
OUTPUT_PATH = "data/filtered.csv"

input_path  = Path(INPUT_PATH)
output_path = Path(OUTPUT_PATH)
search_terms = [n.lower() for n in NAMES]

matched_rows = []

with open(input_path, newline="", encoding="utf-8-sig") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        if any(term in row[COLUMN].lower() for term in search_terms):
            matched_rows.append(row)

output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(matched_rows[0].keys()))
    writer.writeheader()
    writer.writerows(matched_rows)

print(f"Done — {len(matched_rows)} row(s) written to {OUTPUT_PATH}")
