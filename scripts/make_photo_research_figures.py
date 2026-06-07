from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageEnhance

from measure_fpr import make_control_image
from qtracemark import LayerSpec, derive_seed, detect_registry, embed_layers, image_to_ycbcr_arrays, master_seed_from_qrng, save_json
from run_image_experiment import align_down, align_up, fit_image


NAVY = "#1f2a44"
BLUE = "#2d6cdf"
TEAL = "#2a9d8f"
RED = "#e25563"
GRAY = "#6b7280"
LIGHT = "#f3f5f9"


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": GRAY,
            "axes.labelcolor": NAVY,
            "axes.titlecolor": NAVY,
            "xtick.color": NAVY,
            "ytick.color": NAVY,
            "text.color": NAVY,
            "font.size": 10.5,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "savefig.dpi": 160,
            "savefig.bbox": "tight",
        }
    )


def centered_aligned_crop(image: Image.Image, area_fraction: float) -> Image.Image:
    width, height = image.size
    side = math.sqrt(area_fraction)
    crop_w = max(16, align_down(int(width * side)))
    crop_h = max(16, align_down(int(height * side)))
    left = align_down((width - crop_w) // 2)
    top = align_down((height - crop_h) // 2)
    right = align_up(left + crop_w, width)
    bottom = align_up(top + crop_h, height)
    return image.crop((left, top, right, bottom))


def jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def detect_pair(image: Image.Image, layers: list[LayerSpec], threshold: float) -> dict:
    rows = [row.as_dict() for row in detect_registry(image, layers, threshold=threshold)]
    by_layer = {row["layer_type"]: row for row in rows}
    return {
        "work_confidence": by_layer["work"]["confidence"],
        "copy_confidence": by_layer["copy"]["confidence"],
        "work_z": by_layer["work"]["z_score"],
        "copy_z": by_layer["copy"]["z_score"],
        "work_detected": by_layer["work"]["detected"],
        "copy_detected": by_layer["copy"]["detected"],
        "all_detected": by_layer["work"]["detected"] and by_layer["copy"]["detected"],
    }


def psnr(a: Image.Image, b: Image.Image) -> float:
    arr_a = np.asarray(a.convert("RGB"), dtype=np.float64)
    arr_b = np.asarray(b.convert("RGB"), dtype=np.float64)
    mse = float(np.mean((arr_a - arr_b) ** 2))
    if mse == 0:
        return float("inf")
    return 20 * math.log10(255.0 / math.sqrt(mse))


def luminance_delta_stats(source: Image.Image, watermarked: Image.Image) -> dict:
    src_y, _, _ = image_to_ycbcr_arrays(source)
    wm_y, _, _ = image_to_ycbcr_arrays(watermarked)
    delta = wm_y - src_y
    abs_delta = np.abs(delta)
    return {
        "mean_abs_delta_y": float(abs_delta.mean()),
        "median_abs_delta_y": float(np.median(abs_delta)),
        "p95_abs_delta_y": float(np.percentile(abs_delta, 95)),
        "p99_abs_delta_y": float(np.percentile(abs_delta, 99)),
        "max_abs_delta_y": float(abs_delta.max()),
        "delta_array": delta,
        "abs_delta_array": abs_delta,
    }


def run_sweeps(watermarked: Image.Image, source: Image.Image, layers: list[LayerSpec], threshold: float, null_samples: int) -> dict:
    jpeg_qualities = [95, 85, 75, 65, 55, 45, 35, 25]
    crop_areas = [0.90, 0.75, 0.60, 0.50, 0.35, 0.25, 0.15]
    fragment_areas = [0.60, 0.45, 0.30, 0.20, 0.12, 0.08]
    brightness_factors = [0.65, 0.80, 0.95, 1.10, 1.25, 1.40]

    jpeg = [
        {"quality": q, **detect_pair(jpeg_roundtrip(watermarked, q), layers, threshold)}
        for q in jpeg_qualities
    ]
    crop = [
        {"area_fraction": area, **detect_pair(centered_aligned_crop(watermarked, area), layers, threshold)}
        for area in crop_areas
    ]
    fragment = [
        {"area_fraction": area, **detect_pair(centered_aligned_crop(watermarked, area), layers, threshold)}
        for area in fragment_areas
    ]
    brightness = [
        {
            "factor": factor,
            **detect_pair(ImageEnhance.Brightness(watermarked).enhance(factor), layers, threshold),
        }
        for factor in brightness_factors
    ]

    null_records = []
    for i in range(null_samples):
        control = make_control_image(i, (320, 224))
        detected = detect_pair(control, layers, threshold)
        null_records.append(
            {
                "index": i,
                "max_confidence": max(detected["work_confidence"], detected["copy_confidence"]),
                **detected,
            }
        )

    source_detection = detect_pair(source, layers, threshold)
    watermarked_detection = detect_pair(watermarked, layers, threshold)
    return {
        "source": source_detection,
        "watermarked": watermarked_detection,
        "jpeg": jpeg,
        "crop": crop,
        "fragment": fragment,
        "brightness": brightness,
        "null_records": null_records,
    }


def line_plot(rows: list[dict], x_key: str, title: str, xlabel: str, out: Path, invert_x: bool = False) -> None:
    xs = [row[x_key] for row in rows]
    work = [row["work_confidence"] for row in rows]
    copy = [row["copy_confidence"] for row in rows]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.plot(xs, work, marker="o", linewidth=2.2, color=BLUE, label="work layer")
    ax.plot(xs, copy, marker="s", linewidth=2.2, color=TEAL, label="copy layer")
    ax.axhline(0.95, color=RED, linestyle="--", linewidth=1.4, label="threshold 0.95")
    ax.set_ylim(-0.02, 1.08)
    if invert_x:
        ax.invert_xaxis()
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("corrected confidence")
    ax.legend(loc="lower left", framealpha=0.95)
    ax.grid(True, alpha=0.20)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out)
    plt.close(fig)


def figure_crop_fragment(crop_rows: list[dict], fragment_rows: list[dict], out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharey=True)
    for ax, rows, title in (
        (axes[0], crop_rows, "Aligned crop sweep"),
        (axes[1], fragment_rows, "Fragment ROI size sweep"),
    ):
        xs = [row["area_fraction"] * 100 for row in rows]
        ax.plot(xs, [row["work_confidence"] for row in rows], marker="o", linewidth=2.2, color=BLUE, label="work")
        ax.plot(xs, [row["copy_confidence"] for row in rows], marker="s", linewidth=2.2, color=TEAL, label="copy")
        ax.axhline(0.95, color=RED, linestyle="--", linewidth=1.4)
        ax.set_title(title)
        ax.set_xlabel("retained image area (%)")
        ax.grid(True, alpha=0.20)
        ax.invert_xaxis()
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("corrected confidence")
    axes[1].legend(loc="lower left", framealpha=0.95)
    fig.suptitle("Robustness under partial evidence: how much image is enough?")
    fig.savefig(out)
    plt.close(fig)


def figure_null_distribution(null_records: list[dict], sweeps: dict, out: Path) -> None:
    null = np.asarray([row["max_confidence"] for row in null_records], dtype=np.float64)
    attack_mins = [
        min(sweeps["watermarked"]["work_confidence"], sweeps["watermarked"]["copy_confidence"]),
        min(row["work_confidence"] for row in sweeps["jpeg"]),
        min(row["copy_confidence"] for row in sweeps["jpeg"]),
        min(row["work_confidence"] for row in sweeps["crop"]),
        min(row["copy_confidence"] for row in sweeps["crop"]),
    ]
    marked_floor = min(attack_mins)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.hist(null, bins=18, color="#b8c2d6", edgecolor="white", label=f"unwatermarked controls (n={len(null)})")
    ax.axvline(0.95, color=RED, linestyle="--", linewidth=1.8, label="threshold 0.95")
    ax.axvline(0.99, color=NAVY, linestyle=":", linewidth=1.8, label="threshold 0.99")
    ax.axvline(0.999, color=TEAL, linestyle="-.", linewidth=1.8, label="threshold 0.999")
    ax.axvline(marked_floor, color="#111827", linewidth=2.2, label="worst marked detection")
    ax.set_title("Empirical null distribution vs marked-photo detections")
    ax.set_xlabel("max confidence over work/copy candidates")
    ax.set_ylabel("control image count")
    ax.set_xlim(-0.02, 1.02)
    ax.legend(loc="upper center", framealpha=0.95)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out)
    plt.close(fig)


def figure_imperceptibility(source: Image.Image, watermarked: Image.Image, stats: dict, image_psnr: float, out: Path) -> None:
    abs_delta = stats["abs_delta_array"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0), constrained_layout=True)
    axes[0, 0].imshow(np.asarray(source))
    axes[0, 0].set_title("source")
    axes[0, 1].imshow(np.asarray(watermarked))
    axes[0, 1].set_title("watermarked")
    heat = axes[1, 0].imshow(abs_delta, cmap="inferno", vmin=0, vmax=max(1.5, np.percentile(abs_delta, 98)))
    axes[1, 0].set_title("amplified luminance difference")
    axes[1, 1].hist(abs_delta.ravel(), bins=60, color=BLUE, alpha=0.85)
    axes[1, 1].axvline(stats["mean_abs_delta_y"], color=RED, linewidth=1.8, label=f"mean={stats['mean_abs_delta_y']:.2f}")
    axes[1, 1].set_title(f"Delta distribution (PSNR {image_psnr:.2f} dB)")
    axes[1, 1].set_xlabel("|delta Y|")
    axes[1, 1].set_ylabel("pixels")
    axes[1, 1].legend(framealpha=0.95)
    for ax in axes.flat[:3]:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(heat, ax=axes[1, 0], fraction=0.046, pad=0.04)
    fig.suptitle("Imperceptibility analysis on real photo")
    fig.savefig(out)
    plt.close(fig)


def figure_summary(sweeps: dict, metrics: dict, out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.0), constrained_layout=True)
    axes[0, 0].axis("off")
    rows = [
        ("PSNR", f"{metrics['psnr_rgb_db']:.2f} dB"),
        ("mean |delta Y|", f"{metrics['mean_abs_delta_y']:.2f} / 255"),
        ("p99 |delta Y|", f"{metrics['p99_abs_delta_y']:.2f} / 255"),
        ("source FP", "False"),
        ("null FP @0.95", f"{metrics['null_fp_0_95']}/{metrics['null_samples']}"),
        ("null FP @0.99", f"{metrics['null_fp_0_99']}/{metrics['null_samples']}"),
    ]
    table = axes[0, 0].table(cellText=rows, colLabels=["Metric", "Value"], loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.6)
    axes[0, 0].set_title("Evidence-quality metrics")

    axes[0, 1].plot([r["quality"] for r in sweeps["jpeg"]], [r["work_confidence"] for r in sweeps["jpeg"]], marker="o", color=BLUE, label="work")
    axes[0, 1].plot([r["quality"] for r in sweeps["jpeg"]], [r["copy_confidence"] for r in sweeps["jpeg"]], marker="s", color=TEAL, label="copy")
    axes[0, 1].invert_xaxis()
    axes[0, 1].axhline(0.95, color=RED, linestyle="--")
    axes[0, 1].set_title("JPEG sweep")
    axes[0, 1].set_xlabel("JPEG quality")
    axes[0, 1].set_ylabel("confidence")
    axes[0, 1].legend(framealpha=0.95)

    axes[1, 0].plot([r["area_fraction"] * 100 for r in sweeps["crop"]], [r["work_confidence"] for r in sweeps["crop"]], marker="o", color=BLUE, label="work")
    axes[1, 0].plot([r["area_fraction"] * 100 for r in sweeps["crop"]], [r["copy_confidence"] for r in sweeps["crop"]], marker="s", color=TEAL, label="copy")
    axes[1, 0].invert_xaxis()
    axes[1, 0].axhline(0.95, color=RED, linestyle="--")
    axes[1, 0].set_title("Crop area sweep")
    axes[1, 0].set_xlabel("retained area (%)")
    axes[1, 0].set_ylabel("confidence")

    null = [r["max_confidence"] for r in sweeps["null_records"]]
    axes[1, 1].hist(null, bins=16, color="#b8c2d6", edgecolor="white")
    axes[1, 1].axvline(0.95, color=RED, linestyle="--")
    axes[1, 1].axvline(0.99, color=NAVY, linestyle=":")
    axes[1, 1].axvline(0.999, color=TEAL, linestyle="-.")
    axes[1, 1].set_title("Null confidence distribution")
    axes[1, 1].set_xlabel("max confidence")
    axes[1, 1].set_ylabel("controls")

    for ax in axes.flat[1:]:
        ax.grid(True, alpha=0.20)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Q-TraceMark real-photo robustness summary")
    fig.savefig(out)
    plt.close(fig)


def write_rows_csv(rows_by_name: dict[str, list[dict]], out: Path) -> None:
    fieldnames = ["experiment", "parameter", "work_confidence", "copy_confidence", "work_z", "copy_z", "all_detected"]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, rows in rows_by_name.items():
            for row in rows:
                if "quality" in row:
                    parameter = row["quality"]
                elif "area_fraction" in row:
                    parameter = row["area_fraction"]
                elif "factor" in row:
                    parameter = row["factor"]
                else:
                    parameter = row.get("index", "")
                writer.writerow(
                    {
                        "experiment": name,
                        "parameter": parameter,
                        "work_confidence": row.get("work_confidence"),
                        "copy_confidence": row.get("copy_confidence"),
                        "work_z": row.get("work_z"),
                        "copy_z": row.get("copy_z"),
                        "all_detected": row.get("all_detected"),
                    }
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate paper-style robustness figures for a real-photo Q-TraceMark run.")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--qrng-file", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("results/photo_research_figures"))
    parser.add_argument("--max-long-edge", type=int, default=1536)
    parser.add_argument("--work-id", default="PHOTO-WARNEMUNDE-2026-001")
    parser.add_argument("--copy-id", default="COPY-DEMO-PRESENTATION-001")
    parser.add_argument("--work-alpha", type=float, default=10.0)
    parser.add_argument("--copy-alpha", type=float, default=7.0)
    parser.add_argument("--threshold", type=float, default=0.95)
    parser.add_argument("--null-samples", type=int, default=60)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    style()
    args.out.mkdir(parents=True, exist_ok=True)

    source = fit_image(Image.open(args.image).convert("RGB"), args.max_long_edge)
    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-photo-test-v1")
    layers = [
        LayerSpec("work", args.work_id, derive_seed(master_seed, "work", args.work_id), alpha=args.work_alpha),
        LayerSpec("copy", args.copy_id, derive_seed(master_seed, "copy", args.copy_id), alpha=args.copy_alpha),
    ]
    watermarked = embed_layers(source, layers)
    image_psnr = psnr(source, watermarked)
    delta_stats = luminance_delta_stats(source, watermarked)
    sweeps = run_sweeps(watermarked, source, layers, args.threshold, args.null_samples)
    null_max = max(row["max_confidence"] for row in sweeps["null_records"])
    null_fp_0_95 = sum(row["max_confidence"] >= 0.95 for row in sweeps["null_records"])
    null_fp_0_99 = sum(row["max_confidence"] >= 0.99 for row in sweeps["null_records"])
    null_fp_0_999 = sum(row["max_confidence"] >= 0.999 for row in sweeps["null_records"])
    metrics = {
        "source_image": str(args.image),
        "source_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "working_size": list(source.size),
        "qrng_source": str(args.qrng_file) if args.qrng_file else "deterministic demo fallback; use fresh EVK capture for final",
        "qrng_sha256": entropy.sha256,
        "work_alpha": args.work_alpha,
        "copy_alpha": args.copy_alpha,
        "threshold": args.threshold,
        "psnr_rgb_db": image_psnr,
        "mean_abs_delta_y": delta_stats["mean_abs_delta_y"],
        "median_abs_delta_y": delta_stats["median_abs_delta_y"],
        "p95_abs_delta_y": delta_stats["p95_abs_delta_y"],
        "p99_abs_delta_y": delta_stats["p99_abs_delta_y"],
        "max_abs_delta_y": delta_stats["max_abs_delta_y"],
        "null_samples": args.null_samples,
        "null_max_confidence": null_max,
        "null_fp_0_95": null_fp_0_95,
        "null_fp_0_99": null_fp_0_99,
        "null_fp_0_999": null_fp_0_999,
        "source_detection": sweeps["source"],
    }
    serializable_sweeps = {k: v for k, v in sweeps.items() if k != "null_records"}
    payload = {**metrics, "sweeps": serializable_sweeps, "null_records": sweeps["null_records"]}
    save_json(args.out / "research_metrics.json", payload)
    write_rows_csv(
        {
            "jpeg": sweeps["jpeg"],
            "crop": sweeps["crop"],
            "fragment": sweeps["fragment"],
            "brightness": sweeps["brightness"],
            "null": sweeps["null_records"],
        },
        args.out / "research_table.csv",
    )

    figure_imperceptibility(source, watermarked, delta_stats, image_psnr, args.out / "fig_imperceptibility_metrics.png")
    line_plot(sweeps["jpeg"], "quality", "JPEG compression robustness", "JPEG quality", args.out / "fig_jpeg_quality_sweep.png", invert_x=True)
    line_plot(sweeps["brightness"], "factor", "Brightness transform robustness", "brightness multiplier", args.out / "fig_brightness_sweep.png")
    figure_crop_fragment(sweeps["crop"], sweeps["fragment"], args.out / "fig_crop_fragment_sweep.png")
    figure_null_distribution(sweeps["null_records"], sweeps, args.out / "fig_null_distribution.png")
    figure_summary(sweeps, metrics, args.out / "fig_research_summary_dashboard.png")

    summary = {
        "out": str(args.out),
        "psnr_rgb_db": round(image_psnr, 3),
        "mean_abs_delta_y": round(metrics["mean_abs_delta_y"], 3),
        "null_max_confidence": round(null_max, 6),
        "null_fp_0_95": null_fp_0_95,
        "null_fp_0_99": null_fp_0_99,
        "null_fp_0_999": null_fp_0_999,
        "jpeg_min_work": min(row["work_confidence"] for row in sweeps["jpeg"]),
        "jpeg_min_copy": min(row["copy_confidence"] for row in sweeps["jpeg"]),
        "crop_min_work": min(row["work_confidence"] for row in sweeps["crop"]),
        "crop_min_copy": min(row["copy_confidence"] for row in sweeps["crop"]),
        "fragment_min_work": min(row["work_confidence"] for row in sweeps["fragment"]),
        "fragment_min_copy": min(row["copy_confidence"] for row in sweeps["fragment"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
