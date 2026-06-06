from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from qtracemark import LayerSpec, derive_seed, detect_registry, master_seed_from_qrng, save_json


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_THRESHOLDS = "0.95,0.99,0.999"


def make_control_image(index: int, size: tuple[int, int]) -> Image.Image:
    width, height = size
    rng = np.random.default_rng(index + 20260606)
    base = np.zeros((height, width, 3), dtype=np.uint8)
    x_grad = np.linspace(0, 1, width)
    y_grad = np.linspace(0, 1, height)[:, None]
    base[:, :, 0] = np.clip(210 + 35 * x_grad + rng.normal(0, 2, (height, width)), 0, 255)
    base[:, :, 1] = np.clip(190 + 40 * y_grad + rng.normal(0, 2, (height, width)), 0, 255)
    base[:, :, 2] = np.clip(170 + 25 * (1 - x_grad) + rng.normal(0, 2, (height, width)), 0, 255)
    image = Image.fromarray(base, "RGB")
    draw = ImageDraw.Draw(image)
    for _ in range(10):
        x0 = int(rng.integers(0, width - 20))
        y0 = int(rng.integers(0, height - 20))
        x1 = min(width, x0 + int(rng.integers(20, width // 3 + 20)))
        y1 = min(height, y0 + int(rng.integers(20, height // 3 + 20)))
        color = tuple(int(v) for v in rng.integers(40, 230, size=3))
        if rng.random() < 0.5:
            draw.rectangle((x0, y0, x1, y1), outline=color, width=2)
        else:
            draw.ellipse((x0, y0, x1, y1), outline=color, width=2)
    return image


def parse_thresholds(text: str) -> list[float]:
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = float(part)
        if not 0.0 < value < 1.0:
            raise ValueError(f"threshold must be in (0, 1): {value}")
        values.append(value)
    if not values:
        raise ValueError("no thresholds provided")
    return sorted(set(values))


def load_controls(
    controls_dir: Path | None, samples: int, size: tuple[int, int]
) -> tuple[list[tuple[str, Image.Image]], str]:
    """Return (label, image) controls. Real images from a directory win; else synthetic."""
    if controls_dir is not None:
        files = (
            sorted(p for p in controls_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if controls_dir.exists()
            else []
        )
        if files:
            controls = [(p.name, Image.open(p).convert("RGB")) for p in files]
            return controls, f"directory:{controls_dir}"
        print(f"[measure_fpr] no images in {controls_dir}; falling back to synthetic controls")
    controls = [(f"synthetic-{i}", make_control_image(i, size)) for i in range(samples)]
    return controls, "synthetic"


def evaluate_controls(
    controls: list[tuple[str, Image.Image]],
    layers: list[LayerSpec],
    thresholds: list[float],
) -> tuple[list[dict], list[dict]]:
    """Detect on each unwatermarked control once, then sweep thresholds over confidences."""
    primary = thresholds[0]
    records: list[dict] = []
    for label, image in controls:
        rows = [row.as_dict() for row in detect_registry(image, layers, threshold=primary)]
        records.append(
            {
                "label": label,
                "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "false_positive": any(row["confidence"] >= primary for row in rows),
                "detections": rows,
            }
        )

    sweep: list[dict] = []
    total = len(records)
    for threshold in thresholds:
        false_positive_images = sum(
            any(row["confidence"] >= threshold for row in rec["detections"]) for rec in records
        )
        sweep.append(
            {
                "threshold": threshold,
                "family_wise_alpha": round(1.0 - threshold, 6),
                "false_positive_images": false_positive_images,
                "false_positive_rate": false_positive_images / total if total else 0.0,
            }
        )
    return records, sweep


def null_distribution_stats(records: list[dict]) -> dict:
    rows = [row for rec in records for row in rec["detections"]]
    if not rows:
        return {"max_null_confidence": 0.0, "min_null_corrected_p_value": 1.0, "max_null_z_score": 0.0}
    return {
        "max_null_confidence": max(row["confidence"] for row in rows),
        "min_null_corrected_p_value": min(row["p_value_corrected"] for row in rows),
        "max_null_z_score": max(row["z_score"] for row in rows),
    }


def demo_layers(master_seed: bytes) -> list[LayerSpec]:
    work_id = "ART-2026-QRNG-001"
    copy_id = "COPY-PLATFORM-A-USER-8832"
    return [
        LayerSpec("work", work_id, derive_seed(master_seed, "work", work_id), alpha=10.0),
        LayerSpec("copy", copy_id, derive_seed(master_seed, "copy", copy_id), alpha=7.0),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate Q-TraceMark false positive rate on unwatermarked controls.")
    parser.add_argument("--qrng-file", type=Path, default=None, help="Optional EVK QRNG raw .bin file")
    parser.add_argument("--controls-dir", type=Path, default=None, help="Folder of real unwatermarked images to use as controls")
    parser.add_argument("--samples", type=int, default=12, help="Number of synthetic controls when no controls-dir is given")
    parser.add_argument("--width", type=int, default=320, help="Synthetic control image width")
    parser.add_argument("--height", type=int, default=224, help="Synthetic control image height")
    parser.add_argument("--thresholds", type=str, default=DEFAULT_THRESHOLDS, help="Comma-separated corrected-confidence thresholds")
    parser.add_argument("--out", type=Path, default=Path("results/fpr/fpr_report.json"), help="Output report path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.samples < 1:
        raise ValueError("--samples must be positive")
    thresholds = parse_thresholds(args.thresholds)

    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-demo-v1")
    layers = demo_layers(master_seed)

    controls, control_source = load_controls(args.controls_dir, args.samples, (args.width, args.height))
    records, sweep = evaluate_controls(controls, layers, thresholds)
    stats = null_distribution_stats(records)

    report = {
        "project": "Q-TraceMark",
        "report_type": "empirical_null_fpr",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "control_source": control_source,
        "samples": len(controls),
        "synthetic_image_size": [args.width, args.height],
        "thresholds": thresholds,
        "threshold_sweep": sweep,
        **stats,
        "qrng_source": str(args.qrng_file) if args.qrng_file else "deterministic demo fallback; replace with EVK QRNG file for lab runs",
        "entropy_report": entropy.as_dict(),
        "controls": records,
    }
    save_json(args.out, report)
    print(
        json.dumps(
            {
                "control_source": control_source,
                "samples": len(controls),
                "threshold_sweep": sweep,
                **stats,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
