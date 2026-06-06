from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from qtracemark import LayerSpec, derive_seed, detect_registry, master_seed_from_qrng, save_json


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate Q-TraceMark false positive rate on unwatermarked controls.")
    parser.add_argument("--qrng-file", type=Path, default=None, help="Optional EVK QRNG raw .bin file")
    parser.add_argument("--samples", type=int, default=12, help="Number of unwatermarked control images")
    parser.add_argument("--width", type=int, default=320, help="Control image width")
    parser.add_argument("--height", type=int, default=224, help="Control image height")
    parser.add_argument("--threshold", type=float, default=0.95, help="Corrected confidence threshold")
    parser.add_argument("--out", type=Path, default=Path("results/fpr/fpr_report.json"), help="Output report path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.samples < 1:
        raise ValueError("--samples must be positive")

    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-demo-v1")
    work_id = "ART-2026-QRNG-001"
    copy_id = "COPY-PLATFORM-A-USER-8832"
    layers = [
        LayerSpec("work", work_id, derive_seed(master_seed, "work", work_id), alpha=10.0),
        LayerSpec("copy", copy_id, derive_seed(master_seed, "copy", copy_id), alpha=7.0),
    ]

    controls = []
    false_positive_images = 0
    for index in range(args.samples):
        image = make_control_image(index, (args.width, args.height))
        detections = [row.as_dict() for row in detect_registry(image, layers, threshold=args.threshold)]
        image_false_positive = any(row["detected"] for row in detections)
        false_positive_images += int(image_false_positive)
        controls.append(
            {
                "index": index,
                "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "false_positive": image_false_positive,
                "detections": detections,
            }
        )

    max_confidence = max(row["confidence"] for item in controls for row in item["detections"])
    min_corrected_p = min(row["p_value_corrected"] for item in controls for row in item["detections"])
    max_z = max(row["z_score"] for item in controls for row in item["detections"])
    report = {
        "project": "Q-TraceMark",
        "report_type": "empirical_null_fpr",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "samples": args.samples,
        "image_size": [args.width, args.height],
        "threshold": args.threshold,
        "family_wise_alpha": 1.0 - args.threshold,
        "false_positive_images": false_positive_images,
        "false_positive_rate": false_positive_images / args.samples,
        "max_null_confidence": max_confidence,
        "min_null_corrected_p_value": min_corrected_p,
        "max_null_z_score": max_z,
        "qrng_source": str(args.qrng_file) if args.qrng_file else "deterministic demo fallback; replace with EVK QRNG file for lab runs",
        "entropy_report": entropy.as_dict(),
        "controls": controls,
    }
    save_json(args.out, report)
    print(json.dumps({k: report[k] for k in ("samples", "false_positive_images", "false_positive_rate", "max_null_confidence", "min_null_corrected_p_value", "max_null_z_score")}, indent=2))


if __name__ == "__main__":
    main()

