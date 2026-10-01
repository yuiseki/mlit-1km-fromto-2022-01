import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "export", Path(__file__).parents[1] / "scripts" / "03_export_parquet.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _nested(tmp_path, csvs: dict[str, bytes]) -> Path:
    """An outer zip holding one inner zip per CSV, like the MLIT files."""
    outer = {}
    for path, data in csvs.items():
        outer[path + ".zip"] = _zip({Path(path).name: data})
    outer["13/"] = b""
    p = tmp_path / "outer.zip"
    p.write_bytes(_zip(outer))
    return p


def test_inner_csvs_yields_each_csv_in_name_order(tmp_path):
    p = _nested(tmp_path, {
        "13/2020/01/monthly_mdp_mesh1km.csv": b"a\n2\n",
        "13/2019/12/monthly_mdp_mesh1km.csv": b"a\n1\n",
    })  # fmt: skip
    got = list(m.inner_csvs(p))
    assert [name for name, _ in got] == [
        "13/2019/12/monthly_mdp_mesh1km.csv.zip",
        "13/2020/01/monthly_mdp_mesh1km.csv.zip",
    ]
    assert [data for _, data in got] == [b"a\n1\n", b"a\n2\n"]


def test_inner_csvs_can_pick_members(tmp_path):
    p = _nested(tmp_path, {
        "m/master_sjis_2019.csv": b"x\n",
        "m/master_utf8_2019.csv": b"y\n",
    })  # fmt: skip
    got = list(m.inner_csvs(p, lambda name: "utf8" in name))
    assert [data for _, data in got] == [b"y\n"]


def test_inner_csvs_rejects_an_inner_zip_with_other_than_one_file(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(_zip({"13/x.csv.zip": _zip({"a.csv": b"1", "b.csv": b"2"})}))
    with pytest.raises(ValueError, match="one file"):
        list(m.inner_csvs(p))


def test_csv_stats_counts_rows_and_sums_population():
    data = b"mesh1kmid,prefcode,population\n53394519,13,10\n53394520,13,32\n"
    assert m.csv_stats(data) == (2, 42)


def test_csv_stats_reads_a_bom_and_crlf():
    data = "﻿prefcode,population\r\n01,5\r\n".encode()
    assert m.csv_stats(data) == (1, 5)


def test_load_keeps_leading_zeros_of_codes(tmp_path):
    import duckdb

    f = tmp_path / "a.csv"
    f.write_bytes(b"year,month,prefcode,citycode,population\n2019,01,01,01101,12\n")
    con = duckdb.connect()
    m.load_csvs(con, "t", [f], integer_columns=["population"])
    row = con.sql("select month, prefcode, citycode, population from t").fetchone()
    assert row == ("01", "01", "01101", 12)
    types = dict(con.sql("select column_name, column_type from (describe t)").fetchall())
    assert types["prefcode"] == "VARCHAR" and types["population"] == "INTEGER"


def test_load_can_add_a_version_column(tmp_path):
    import duckdb

    a, b = tmp_path / "x_2019.csv", tmp_path / "x_2020.csv"
    a.write_bytes(b"prefcode\n01\n")
    b.write_bytes(b"prefcode\n02\n")
    con = duckdb.connect()
    m.load_csvs(con, "t", [a, b], version=lambda p: p.stem[-4:])
    assert con.sql("select version, prefcode from t order by 1").fetchall() == [
        ("2019", "01"),
        ("2020", "02"),
    ]


def test_parquet_is_written_without_bloom_filters(tmp_path):
    # DuckDB reads a column's bloom filter in every row group a filter touches,
    # even one the min/max statistics already rule out. Over HTTP that is a
    # request per row group per filtered column: 1,114 for one ward and month.
    import duckdb

    con = duckdb.connect()
    p = tmp_path / "t.parquet"
    m.write(
        con,
        "select lpad((i % 47 + 1)::varchar, 2, '0') as prefcode, 1 as population from range(20000) t(i)",
        p,
        {"rows": 20000, "population": 20000},
    )
    got = con.sql(
        f"select count(*) filter (where bloom_filter_offset is not null) from parquet_metadata('{p}')"
    ).fetchone()[0]
    assert got == 0
