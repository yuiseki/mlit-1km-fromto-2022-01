#!/usr/bin/env python3
"""Push the frozen zips, their Parquet and the card to the Hugging Face Hub.

The zips go up as files rather than through datasets.push_to_hub, because
push_to_hub re-encodes. What makes this dataset worth anything is that the
bytes under raw/ are the publisher's own, checked against the hashes recorded
when every one of them was dated January 2022 or earlier, so they are
uploaded unchanged and the manifest travels with them.

    uv run python src/publish.py             # dry run
    uv run python src/publish.py --push
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "yuiseki/mlit-1km-fromto-2022-01"

# Declared on the card, and therefore checked before anything moves.
CONFIGS = {
    "mesh1km": "parquet/monthly_mdp_mesh1km.parquet",
    "fromto_city": "parquet/monthly_fromto_city.parquet",
    "attribute_mesh1km": "parquet/attribute_mesh1km.parquet",
    "prefcode_citycode_master": "parquet/prefcode_citycode_master.parquet",
    "regioncode_master": "parquet/regioncode_master.parquet",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    card = (ROOT / "data" / "README.md").read_text(encoding="utf-8")
    for name, path in CONFIGS.items():
        if not re.search(rf"^- config_name: {re.escape(name)}$", card, re.M):
            raise SystemExit(f"the card declares no config named {name}")
        if not re.search(rf"^  data_files: {re.escape(path)}$", card, re.M):
            raise SystemExit(f"the card's data_files do not point at {path}")
        if not (ROOT / "data" / path).exists():
            raise SystemExit(f"missing {path}; run scripts/03 first")

    # The zips are the claim. A manifest that does not describe them means the
    # copy on the Hub is not the copy that was checked.
    rawdir = ROOT / "data" / "raw"
    listed = {}
    for line in (rawdir / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        sha, _size, _lm, name = line.split("  ")
        listed[name] = sha
    on_disk = sorted(p.name for p in rawdir.iterdir() if p.suffix in (".zip", ".pdf"))
    if sorted(listed) != on_disk:
        raise SystemExit("MANIFEST.sha256 and raw/ do not agree")
    for name, sha in sorted(listed.items()):
        got = hashlib.sha256((rawdir / name).read_bytes()).hexdigest()
        if got != sha:
            raise SystemExit(f"{name}: manifest says {sha}, file is {got}")
    print(f"{len(listed)} files match the manifest")

    files = ["README.md", "LICENSE", "provenance.yaml", "raw/MANIFEST.sha256"]
    files += [f"raw/{n}" for n in on_disk]
    files += list(CONFIGS.values())
    total = sum((ROOT / "data" / f).stat().st_size for f in files)
    print(f"{a.repo}\n  {len(files)} files, {total / 1e6:.1f} MB")
    print(f"  {files[:4]} + {len(on_disk)} under raw/ + {len(CONFIGS)} Parquet")

    if not a.push:
        print("\ndry run. pass --push to upload")
        return 0

    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        folder_path=str(ROOT / "data"),
        repo_id=a.repo,
        repo_type="dataset",
        allow_patterns=files,
    )
    print(f"\npushed to https://huggingface.co/datasets/{a.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
