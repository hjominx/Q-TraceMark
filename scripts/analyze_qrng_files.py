from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from qtracemark import entropy_report, save_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze EVK QRNG raw binary files for Q-TraceMark evidence reports.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/qrng"),
        help="Directory containing EVK .bin files",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/assets/evk_qrng_quality_report.json"),
        help="Output JSON report path",
    )
    return parser


def summarize_group(records: list[dict]) -> dict:
    if not records:
        return {"count": 0}
    ratios = np.asarray([r["bit_one_ratio"] for r in records], dtype=np.float64)
    entropies = np.asarray([r["byte_entropy_bits_per_byte"] for r in records], dtype=np.float64)
    sizes = np.asarray([r["byte_count"] for r in records], dtype=np.int64)
    longest = np.asarray([r["longest_run_bits"] for r in records], dtype=np.int64)
    return {
        "count": len(records),
        "total_bytes": int(sizes.sum()),
        "bit_one_ratio_mean": float(ratios.mean()),
        "bit_one_ratio_std": float(ratios.std(ddof=1)) if len(ratios) > 1 else 0.0,
        "bit_one_ratio_min": float(ratios.min()),
        "bit_one_ratio_max": float(ratios.max()),
        "byte_entropy_mean": float(entropies.mean()),
        "byte_entropy_std": float(entropies.std(ddof=1)) if len(entropies) > 1 else 0.0,
        "longest_run_max": int(longest.max()),
    }


def main() -> None:
    args = build_parser().parse_args()
    files = sorted(args.data_dir.glob("*.bin"))
    if not files:
        raise FileNotFoundError(f"No .bin files found in {args.data_dir}")

    records = []
    for path in files:
        report = entropy_report(path.read_bytes()).as_dict()
        report["file"] = path.name
        report["relative_path"] = str(path)
        records.append(report)

    groups = {
        "A": [record for record in records if record["file"].startswith("evk_A")],
        "B_repeats": [record for record in records if record["file"].startswith("evk_B")],
        "C": [record for record in records if record["file"].startswith("evk_C")],
        "all": records,
    }
    payload = {
        "project": "Q-TraceMark",
        "report_type": "evk_qrng_quality",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(args.data_dir),
        "file_count": len(records),
        "files": records,
        "groups": {name: summarize_group(group) for name, group in groups.items()},
    }
    save_json(args.out, payload)
    print(json.dumps({"out": str(args.out), "file_count": len(records), "groups": payload["groups"]}, indent=2))


if __name__ == "__main__":
    main()

