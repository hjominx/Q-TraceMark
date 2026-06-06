from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from qtracemark import detect_registry, embed_layers, master_seed_from_qrng, save_json
from run_demo import make_attacks, make_source_image
from measure_fpr import (
    DEFAULT_THRESHOLDS,
    demo_layers,
    evaluate_controls,
    load_controls,
    null_distribution_stats,
    parse_thresholds,
)


DOCS_REPORT = Path("docs/assets/validation_report.json")


def detect_attacks(paths: dict[str, Path], regions: dict[str, tuple[int, int, int, int]], layers, threshold: float) -> dict[str, list[dict]]:
    detections: dict[str, list[dict]] = {}
    for name, path in paths.items():
        image = Image.open(path).convert("RGB")
        if name in regions:
            image = image.crop(regions[name])
        detections[name] = [row.as_dict() for row in detect_registry(image, layers, threshold=threshold)]
    return detections


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Q-TraceMark report-grade validation suite.")
    parser.add_argument("--qrng-file", type=Path, default=None, help="Optional EVK QRNG raw .bin file")
    parser.add_argument("--controls-dir", type=Path, default=None, help="Folder of real unwatermarked images for FPR controls")
    parser.add_argument("--samples", type=int, default=12, help="Number of synthetic controls when no controls-dir is given")
    parser.add_argument("--width", type=int, default=320, help="Synthetic control image width")
    parser.add_argument("--height", type=int, default=224, help="Synthetic control image height")
    parser.add_argument("--thresholds", type=str, default=DEFAULT_THRESHOLDS, help="Comma-separated corrected-confidence thresholds")
    parser.add_argument("--out", type=Path, default=Path("results/validation/validation_report.json"), help="Output report path")
    parser.add_argument("--update-docs", action="store_true", help="Also overwrite docs/assets/validation_report.json (off by default)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.samples < 1:
        raise ValueError("--samples must be positive")
    thresholds = parse_thresholds(args.thresholds)
    primary_threshold = thresholds[0]

    out_dir = args.out.parent
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-demo-v1")
    layers = demo_layers(master_seed)

    # 1. Watermark issuance + attack generation
    source = make_source_image(image_dir / "source.png")
    watermarked = embed_layers(source, layers)
    watermarked_path = image_dir / "watermarked.png"
    watermarked.save(watermarked_path)

    paths = {"source": image_dir / "source.png", "watermarked": watermarked_path}
    attack_paths, attack_regions = make_attacks(watermarked, source, image_dir)
    paths.update(attack_paths)

    # 2. Detection on watermarked copy and attacked copies
    attack_detections = detect_attacks(paths, attack_regions, layers, primary_threshold)

    # 3. FPR measurement on unwatermarked controls + threshold sweep
    controls, control_source = load_controls(args.controls_dir, args.samples, (args.width, args.height))
    control_records, sweep = evaluate_controls(controls, layers, thresholds)
    stats = null_distribution_stats(control_records)

    report = {
        "project": "Q-TraceMark",
        "report_type": "report_grade_validation",
        "evidence_schema_version": "0.2",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "work_id": layers[0].layer_id,
        "copy_id": layers[1].layer_id,
        "thresholds": thresholds,
        "primary_threshold": primary_threshold,
        "confidence_model": "one-sided z-test with Bonferroni correction over period^2 phase trials",
        "qrng_source": str(args.qrng_file) if args.qrng_file else "deterministic demo fallback; replace with EVK QRNG file for lab runs",
        "entropy_report": entropy.as_dict(),
        "master_seed_hash": hashlib.sha256(master_seed).hexdigest(),
        "layers": [
            {
                "layer_type": layer.layer_type,
                "layer_id": layer.layer_id,
                "seed_hash": layer.seed_hash,
                "alpha": layer.alpha,
                "density": layer.density,
                "period": layer.period,
            }
            for layer in layers
        ],
        "attack_detections": attack_detections,
        "attack_regions": {name: list(box) for name, box in attack_regions.items()},
        "false_positive_analysis": {
            "control_source": control_source,
            "samples": len(controls),
            "synthetic_image_size": [args.width, args.height],
            "threshold_sweep": sweep,
            **stats,
            "controls": control_records,
        },
    }

    save_json(args.out, report)
    if args.update_docs:
        save_json(DOCS_REPORT, report)

    summary = {
        "report": str(args.out),
        "control_source": control_source,
        "control_samples": len(controls),
        "attack_detection_pass": {
            name: all(row["detected"] for row in rows)
            for name, rows in attack_detections.items()
            if name != "source"
        },
        "source_false_positive": any(row["detected"] for row in attack_detections.get("source", [])),
        "fpr_threshold_sweep": sweep,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
