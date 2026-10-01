---
license: cc-by-4.0
language:
- ja
- en
task_categories:
- tabular-regression
- time-series-forecasting
tags:
- japan
- human-mobility
- population
- mesh
- geospatial
- geoparquet
- frozen-snapshot
- mlit
size_categories:
- 10M<n<100M
configs:
- config_name: mesh1km
  data_files: parquet/monthly_mdp_mesh1km.parquet
  default: true
- config_name: fromto_city
  data_files: parquet/monthly_fromto_city.parquet
- config_name: attribute_mesh1km
  data_files: parquet/attribute_mesh1km.parquet
- config_name: prefcode_citycode_master
  data_files: parquet/prefcode_citycode_master.parquet
- config_name: regioncode_master
  data_files: parquet/regioncode_master.parquet
---

# mlit-1km-fromto-2022-01

全国の人流オープンデータ, the Japanese government's open data on where people
were: the average number of people present in every 1 km mesh of the
country, and in every municipality by where they live, for each month from
2019-01 to 2021-12. Weekday and holiday, daytime and late night.

CC BY 4.0, by way of the Government of Japan Standard Terms of Use 2.0.

## Why this exists

The publisher distributes 94 zip files, one per prefecture and kind, each
holding a zip per month that holds one CSV. Nothing can be read in part: to
look at Tokyo in December 2021 you unpack Tokyo, and to compare two
prefectures you unpack both. This dataset is the same CSVs as five Parquet
files, sorted so that a query on one prefecture and month reads a few row
groups over HTTP.

The month in the name is the month the files last changed. Every file was
dated 2022-01-14 or earlier when this was first fetched, and the bytes have
not changed since. More on that below.

## What is here

| config | rows | |
|---|---:|---|
| `mesh1km` | 38,079,507 | stay population per 1 km mesh, 47 prefectures, 36 months |
| `fromto_city` | 2,340,980 | stay population per municipality, by home area |
| `attribute_mesh1km` | 775,000 | each mesh's centre and bounds, with a polygon `geometry` |
| `prefcode_citycode_master` | 3,792 | municipality codes and names |
| `regioncode_master` | 94 | prefecture to regional block |

`raw/` holds the publisher's 94 zips, the three master zips, the terms of use
(`license.pdf`) and the data definition (`opendatadefinition.pdf`), byte for
byte. `raw/MANIFEST.sha256` records the sha256, the size and the
Last-Modified of each as fetched.

### mesh1km

| column | |
|---|---|
| `mesh1kmid` | third-level standard mesh code, 8 digits |
| `prefcode`, `citycode` | prefecture and municipality codes |
| `year`, `month` | |
| `dayflag` | 0 holiday, 1 weekday, 2 all days |
| `timezone` | 0 daytime (the 11 to 14 o'clock hours), 1 late night (1 to 4), 2 all day |
| `population` | people present, averaged per day over the month |

Values under 10 are not published, so a mesh with fewer people is absent
rather than zero.

### fromto_city

`year`, `month`, `dayflag`, `timezone`, `prefcode`, `citycode` (where people
were), `from_area` and `population`. `from_area` is where they live: 0 the
same municipality, 1 another municipality of the same prefecture, 2 another
prefecture of the same regional block, 3 another block. The municipality
they came from is not given.

## Codes are text

`prefcode` is `'01'`, `month` is `'01'`, `citycode` is `'01101'`. Every column
but `population` is the text of the CSV, as the data definition writes it.
Compare with strings: `WHERE prefcode = '13'`, not `= 13`.

The attribute file and the two masters exist in a 2019 and a 2020 version,
kept here side by side and told apart by a `version` column. Join on one of
them, or every row doubles. In the 2019 data Nakagawa in Fukuoka still
carries 40305, the code of the town it was before it became a city; the data
definition says so.

```sql
-- DuckDB, straight off the Hub. Taito ward, December 2021, daytime, all days.
SELECT mesh1kmid, population
FROM 'hf://datasets/yuiseki/mlit-1km-fromto-2022-01/parquet/monthly_mdp_mesh1km.parquet'
WHERE prefcode = '13' AND citycode = '13106'
  AND year = '2021' AND month = '12' AND dayflag = '2' AND timezone = '0'
ORDER BY population DESC;
-- 53394652  63678
-- 53394642  54161
-- ...
```

Tokyo's weekday daytime total fell from 17,171,524 in March 2020 to
15,587,728 in April, when the first state of emergency was declared. Anyone
splitting this data by month for validation should know that the spring of
2020 is not like the months around it.

## The dates on the files

The claim that nothing changed after January 2022 rests on bytes, not on
dates. On 2026-09-29 every file carried a Last-Modified between 2021-02-19
and 2022-01-14, and their sha256 were recorded. On 2026-10-02 every one of
them came back dated 2026-09-30, with the same bytes: the objects were put
again and their content was not changed. `scripts/01_download.py` in the
source repository compares each download against the recorded hashes and
stops on any difference.

The catalogue entry says it was modified on 2024-10-04. That was the entry,
not a file.

## Reproducing it

```bash
git clone https://github.com/yuiseki/mlit-1km-fromto-2022-01
cd mlit-1km-fromto-2022-01
uv run python scripts/01_download.py      # 99 files, checked against the recorded bytes
uv run python scripts/02_verify.py        # 36 months a prefecture, rows and totals pinned
uv run python scripts/03_export_parquet.py
```

The values are reproducible and the Parquet bytes are not: DuckDB writes in
parallel and the compressed files come out a few tens of kilobytes apart. Two
runs were compared row by row in both directions and no row differed.

## Licence

CC BY 4.0. Credit, in the form the terms ask for:

    出典：「全国の人流オープンデータ」（国土交通省）
    （https://www.geospatial.jp/ckan/dataset/mlit-1km-fromto）を加工して作成

The publisher applies 全国の人流オープンデータ利用規約 (`raw/license.pdf`),
which follows the Government of Japan Standard Terms of Use 2.0 and so may be
used in accordance with CC BY 4.0. The terms ask that a modification be
declared and that modified content not be presented as the government's own;
this dataset is not published by the Government of Japan. `LICENSE` beside
this file states the modifications in Japanese, as the terms ask. The zips
under `raw/` are unchanged.
