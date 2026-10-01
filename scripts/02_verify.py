#!/usr/bin/env python3
"""Check that the frozen zips hold what this dataset says they hold.

Read with zipfile and the csv module only, so nothing here shares a parser
with the Parquet export. Every prefecture zip must hold 36 months
(2019-01 to 2021-12), every CSV in it must be that prefecture's, and the
totals must be those of the files recorded in scripts/REFERENCE.sha256.
"""

import csv
import hashlib
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

_spec = importlib.util.spec_from_file_location("export", ROOT / "scripts" / "03_export_parquet.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

EXPECTED = {
    "monthly_mdp_mesh1km": {"csvs": 1692, "rows": 38079507, "population": 41119094290},
    "monthly_fromto_city": {"csvs": 1692, "rows": 2340980, "population": 41178569986},
}
MONTHS = [f"{y}/{m:02d}" for y in (2019, 2020, 2021) for m in range(1, 13)]


def main() -> int:
    failures = []

    def check(ok: bool, what: str) -> None:
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            failures.append(what)

    lines = (RAW / "MANIFEST.sha256").read_text().splitlines()
    check(len(lines) == 99, f"MANIFEST.sha256 lists {len(lines)} files, expected 99")
    bad = 0
    for line in lines:
        sha, size, _lm, name = line.split("  ")
        data = (RAW / name).read_bytes()
        bad += hashlib.sha256(data).hexdigest() != sha or len(data) != int(size)
    check(bad == 0, f"every file matches the manifest ({bad} do not)")

    for kind, want in EXPECTED.items():
        csvs = rows = total = 0
        wrong_pref = wrong_months = 0
        for i in range(1, 48):
            pref = f"{i:02d}"
            months = []
            for name, data in export.inner_csvs(RAW / f"{kind}_{pref}.zip"):
                months.append(name.split("/", 1)[1].rsplit("/", 1)[0])
                r, t = export.csv_stats(data)
                csvs, rows, total = csvs + 1, rows + r, total + t
                prefs = {
                    row["prefcode"] for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
                }
                wrong_pref += prefs != {pref}
            wrong_months += sorted(months) != MONTHS
        check(
            wrong_months == 0, f"{kind}: every prefecture has the 36 months ({wrong_months} do not)"
        )
        check(wrong_pref == 0, f"{kind}: every CSV holds only its prefecture ({wrong_pref} do not)")
        for k in ("csvs", "rows", "population"):
            got = {"csvs": csvs, "rows": rows, "population": total}[k]
            check(got == want[k], f"{kind}: {k} {got:,}, expected {want[k]:,}")

    if failures:
        print(f"\n{len(failures)} checks failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
