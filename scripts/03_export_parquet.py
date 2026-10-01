#!/usr/bin/env python3
"""Turn the nested zips into one Parquet per kind, for the Hub viewer and DuckDB.

Every prefecture zip holds one zip per month, and every one of those holds a
single CSV. Nothing in it can be read in part. This writes:

  monthly_mdp_mesh1km.parquet      stay population per 1 km mesh, all prefectures
  monthly_fromto_city.parquet      stay population per municipality by home area
  attribute_mesh1km.parquet        mesh centre and bounds, with a polygon (GeoParquet)
  prefcode_citycode_master.parquet the UTF-8 masters, the 2019 and the 2020 file
  regioncode_master.parquet

Codes stay strings as the data definition says (prefcode "01", month "01");
only population becomes an integer. The rows and the population total of
every output are checked against the CSVs, counted by the csv module, before
the run ends.
"""

import csv
import io
import sys
import zipfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "parquet"
WORK = ROOT / "data" / "work"


def inner_csvs(
    path: Path, keep: Callable[[str], bool] = lambda name: True
) -> Iterator[tuple[str, bytes]]:
    """(inner zip name, CSV bytes) for every inner zip of an outer zip, by name."""
    with zipfile.ZipFile(path) as outer:
        names = sorted(n for n in outer.namelist() if n.endswith(".zip") and keep(n))
        for name in names:
            with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                members = [n for n in inner.namelist() if not n.endswith("/")]
                if len(members) != 1:
                    raise ValueError(f"{path.name}:{name} holds {len(members)} files, not one file")
                yield name, inner.read(members[0])


def csv_stats(data: bytes) -> tuple[int, int]:
    """(rows, population total) of one CSV, counted without DuckDB."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    rows = total = 0
    for row in reader:
        rows += 1
        total += int(row["population"]) if "population" in row else 0
    return rows, total


def load_csvs(
    con,
    table: str,
    files: list[Path],
    integer_columns: Iterable[str] = (),
    version: Callable[[Path], str] | None = None,
) -> None:
    """Load CSVs into a table with every column text except integer_columns."""
    ints = list(integer_columns)
    cast = ", ".join(f"cast({c} as integer) as {c}" for c in ints)
    cols = f"* exclude ({', '.join(ints)}), {cast}" if ints else "*"

    def read(fs: list[Path]) -> str:
        lst = ", ".join(f"'{f}'" for f in fs)
        return f"read_csv([{lst}], header = true, all_varchar = true, union_by_name = true)"

    if version is None:
        con.execute(f"create or replace table {table} as select {cols} from {read(files)}")
        return
    parts = [f"select '{version(f)}' as version, {cols} from {read([f])}" for f in files]
    con.execute(f"create or replace table {table} as {' union all by name '.join(parts)}")


def extract(zips: list[Path], out: Path, keep: Callable[[str], bool] = lambda n: True) -> dict:
    """Write every inner CSV of the zips under out; return its rows and total."""
    rows = total = n = 0
    files = []
    for z in zips:
        for name, data in inner_csvs(z, keep):
            f = out / name.removesuffix(".zip")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
            r, t = csv_stats(data)
            rows, total, n = rows + r, total + t, n + 1
            files.append(f)
    return {"files": files, "csvs": n, "rows": rows, "population": total}


def write(con, query: str, path: Path, expected: dict) -> None:
    # No bloom filters. DuckDB reads a column's bloom filter in every row group
    # that a filter on that column touches, even a row group the min/max
    # statistics already rule out. dayflag and timezone hold 0, 1 and 2 in
    # every row group, so a query on one ward and month made 1,114 requests
    # over HTTP and took 32 s from the Hub. The rows are sorted by prefecture,
    # year and month, and the statistics alone skip what is not wanted.
    con.execute(
        f"copy ({query}) to '{path}' (format parquet, compression zstd, "
        "row_group_size 100000, write_bloom_filter false)"
    )
    got = con.sql(f"select count(*) from '{path}'").fetchone()[0]
    if got != expected["rows"]:
        raise SystemExit(f"{path.name}: {got} rows, the CSVs have {expected['rows']}")
    cols = [r[0] for r in con.sql(f"select name from parquet_schema('{path}')").fetchall()]
    if "population" in cols:
        s = con.sql(f"select sum(population) from '{path}'").fetchone()[0]
        if s != expected["population"]:
            raise SystemExit(f"{path.name}: population {s}, the CSVs have {expected['population']}")
    print(f"{path.name:34} {got:>11,} rows {path.stat().st_size:>12,} bytes")


def year_of(p: Path) -> str:
    return p.stem.rsplit("_", 1)[1]


def main() -> int:
    import duckdb

    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("set memory_limit = '6GB'; set preserve_insertion_order = false")
    con.execute("install spatial; load spatial")
    csvdir = WORK / "csv"

    for kind, order in [
        ("monthly_mdp_mesh1km", "prefcode, year, month, dayflag, timezone, mesh1kmid"),
        ("monthly_fromto_city", "prefcode, citycode, year, month, dayflag, timezone, from_area"),
    ]:
        zips = sorted(RAW.glob(f"{kind}_*.zip"))
        if len(zips) != 47:
            raise SystemExit(f"{kind}: {len(zips)} prefecture zips, not 47")
        ex = extract(zips, csvdir / kind)
        load_csvs(con, kind, ex["files"], integer_columns=["population"])
        write(con, f"select * from {kind} order by {order}", OUT / f"{kind}.parquet", ex)

    ex = extract([RAW / "attribute.zip"], csvdir / "attribute")
    load_csvs(con, "attribute", ex["files"], version=year_of)
    write(con, """
        select *, st_makeenvelope(lon_min::double, lat_min::double,
                                  lon_max::double, lat_max::double) as geometry
        from attribute order by version, mesh1kmid
    """, OUT / "attribute_mesh1km.parquet", ex)  # fmt: skip

    for name, zname, key in [
        ("prefcode_citycode_master", "prefcodecitycodemaster.zip", "citycode"),
        ("regioncode_master", "regioncodemaster.zip", "prefcode"),
    ]:
        ex = extract([RAW / zname], csvdir / name, lambda n: "_utf8_" in n)
        load_csvs(con, name, ex["files"], version=year_of)
        write(con, f"select * from {name} order by version, {key}", OUT / f"{name}.parquet", ex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
