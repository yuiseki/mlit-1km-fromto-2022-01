# mlit-1km-fromto-2022-01

Dataset: https://huggingface.co/datasets/yuiseki/mlit-1km-fromto-2022-01

全国の人流オープンデータ (MLIT), the monthly stay population of every 1 km
mesh and every municipality of Japan for 2019-01 to 2021-12, as the
publisher's files last changed in January 2022, and the code that fetches,
checks and converts them. This repository holds the code; the data is on the
Hub.

## Where things are

```
scripts/01_download.py        99 files from the CKAN API, each checked against REFERENCE.sha256
scripts/REFERENCE.sha256      the bytes as recorded when every file was dated 2022-01 or earlier
scripts/02_verify.py          36 months a prefecture, rows and population totals pinned
scripts/03_export_parquet.py  nested zips -> one Parquet per kind
src/publish.py                pushes the data and its card to the Hub
tests/                        the zip reading, the counting, the loading

data/README.md                the dataset card. Uploaded as-is
data/LICENSE                  the CC BY notice and the modifications, in Japanese as the terms ask
data/provenance.yaml          the vintage, the counts, and what was done
data/raw/                     generated, 192 MiB, the publisher's own files
data/parquet/                 generated, 112 MiB
```

## Running it

```sh
uv run python scripts/01_download.py
uv run python scripts/02_verify.py
uv run python scripts/03_export_parquet.py
uv run python src/publish.py          # dry run; --push to upload
uv run pytest
```

About five minutes, most of it unpacking 3,384 nested CSVs twice.

## Why the bytes and not the dates

The name says the files last changed in January 2022. On 2026-09-29 that was
what the server's Last-Modified said for all 99. On 2026-10-02 the server said
2026-09-30 for all 99, and the bytes were the same: the objects had been put
again. A check on dates would have failed a dataset that had not changed, and
one that trusted dates would pass a dataset that had. `01_download.py`
compares every file with `REFERENCE.sha256` and stops on the first that
differs.

## Three traps

**Codes are text.** `prefcode` is `'01'` and `month` is `'01'`. Only
`population` is an integer. `WHERE prefcode = 13` matches nothing.

**Two versions of the masters.** The attribute file and both masters exist
for 2019 and 2020, side by side under a `version` column. Join without
picking one and every row doubles.

**Bloom filters cost a request per row group.** DuckDB writes them by
default and reads them for every row group a filter touches, including the
ones the statistics already excluded. Filtering on `dayflag` and `timezone`,
which hold every value in every row group, turned one query into 1,114 HTTP
requests. `03_export_parquet.py` writes without them.

## Licence

The code here is MIT. The data it fetches is CC BY 4.0, by way of the
Government of Japan Standard Terms of Use 2.0:

    出典：「全国の人流オープンデータ」（国土交通省）
    （https://www.geospatial.jp/ckan/dataset/mlit-1km-fromto）を加工して作成

See `data/LICENSE` for the notice and the modifications.
