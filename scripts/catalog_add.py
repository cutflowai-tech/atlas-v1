"""Add or update entries of the i18n catalogue from a JSON list (development helper; keeps key order and formatting).

    python3 scripts/catalog_add.py entries.json     # [{"key", "en", "ar", "context", "status"?}]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "src" / "atlas_commander" / "locales" / "catalog.json"


def main(path: str) -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    for row in json.loads(Path(path).read_text(encoding="utf-8")):
        entry = {"en": row["en"], "ar": row["ar"], "context": row["context"], "status": row.get("status", "Needs Arabic Review")}
        if row.get("notes"):
            entry["notes"] = row["notes"]
        document["entries"][row["key"]] = entry
    CATALOG.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
