#!/usr/bin/env python3
"""Fetch the 99 files of 全国の人流オープンデータ and freeze exactly what arrived.

The dataset (https://www.geospatial.jp/ckan/dataset/mlit-1km-fromto) is 94
zip files, one per prefecture and kind, each holding one zip per month that
holds one CSV; three zips of masters; and the terms of use and the data
definition as PDF. The CKAN API lists them without a login and every URL
redirects to a signed S3 URL.

The name of this dataset claims that nothing in it changed after January
2022. That claim is checked on the bytes, not on Last-Modified: every file
must match scripts/REFERENCE.sha256, the hashes recorded on 2026-09-29 when
every Last-Modified was 2022-01-14 or earlier. The server's dates cannot be
trusted for it. license.pdf came back on 2026-10-02 with a Last-Modified of
2026-09-30 and the same bytes: the object was put again, the content was not
changed. The page's metadata_modified (2024-10) is a change to the catalogue
entry, not to any file.

Six more PDFs on the page (a QGIS manual and five worked examples) are not
data and are left out.

    uv run python scripts/01_download.py
"""

import email.utils
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw"
DATASET = "mlit-1km-fromto"
API = f"https://www.geospatial.jp/ckan/api/3/action/package_show?id={DATASET}"
UA = "mlit-1km-fromto-2022-01/1 (+https://github.com/yuiseki/mlit-1km-fromto-2022-01)"
PDFS = {"利用規約": "license.pdf", "オープンデータ（人流データ）定義書": "opendatadefinition.pdf"}
MASTERS = ("attribute", "prefcode_citycode_master", "regioncode_master")
REFERENCE = ROOT / "scripts" / "REFERENCE.sha256"


def wanted(resources: list[dict]) -> list[dict]:
    keep = [
        r for r in resources
        if r["name"].startswith(("monthly_mdp_mesh1km_", "monthly_fromto_city_"))
        or r["name"] in MASTERS or r["name"] in PDFS
    ]  # fmt: skip
    if len(keep) != 99:
        raise SystemExit(f"{len(keep)} resources to take, not 99")
    return keep


def reference() -> dict[str, tuple[str, int]]:
    out = {}
    for line in REFERENCE.read_text().splitlines():
        if line and not line.startswith("#"):
            sha, size, _lm, name = line.split("  ")
            out[name] = (sha, int(size))
    return out


def fetch(url: str, dest: Path, size: int | None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
                last_modified = r.headers["Last-Modified"]
            break
        except OSError as e:
            if attempt == 2:
                raise
            print(f"retry {dest.name}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    if size is not None and tmp.stat().st_size != size:
        raise SystemExit(f"{dest.name}: got {tmp.stat().st_size} bytes, CKAN lists {size}")
    tmp.replace(dest)
    return last_modified


def main() -> int:
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        pkg = json.load(r)["result"]
    ref = reference()
    OUT.mkdir(parents=True, exist_ok=True)
    lines, reput = [], []
    for res in wanted(pkg["resources"]):
        name = PDFS.get(res["name"]) or res["url"].rsplit("/", 1)[1]
        dest = OUT / name
        lm = fetch(res["url"], dest, int(res["size"]) if res.get("size") else None)
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        if (sha, dest.stat().st_size) != ref.get(name):
            raise SystemExit(f"{name} is not the file recorded in {REFERENCE.name}")
        if email.utils.parsedate_to_datetime(lm).date().isoformat() > "2022-01-31":
            reput.append(name)
        lines.append(f"{sha}  {dest.stat().st_size}  {lm}  {name}")
    if sorted(n.rsplit("  ", 1)[1] for n in lines) != sorted(ref):
        raise SystemExit(f"the files fetched are not the {len(ref)} in {REFERENCE.name}")
    lines.sort(key=lambda s: s.rsplit("  ", 1)[1])
    (OUT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} files, every one the bytes of {REFERENCE.name}")
    print(f"{len(reput)} carry a Last-Modified after January 2022 with those same bytes")
    print(f"catalogue entry modified {pkg['metadata_modified']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
