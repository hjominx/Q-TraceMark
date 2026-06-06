from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from qtracemark import embed_layers, image_to_ycbcr_arrays, master_seed_from_qrng
from measure_fpr import demo_layers
from run_demo import make_source_image


ASSETS = Path("docs/assets")

# Palette: poster + product-pitch, restrained and high-contrast.
NAVY = "#1f2a44"
BLUE = "#2d6cdf"
TEAL = "#2a9d8f"
RED = "#e25563"
GRAY = "#6b7280"
LIGHT = "#f3f5f9"

ATTACK_LABELS = {
    "source": "source\n(no mark)",
    "watermarked": "watermarked",
    "jpeg_q70": "JPEG q70",
    "crop_50pct": "crop 50%",
    "brightness": "brightness",
    "pasted_fragment": "pasted\nfragment",
}
ATTACK_ORDER = ["source", "watermarked", "jpeg_q70", "crop_50pct", "brightness", "pasted_fragment"]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": GRAY,
            "axes.titlecolor": NAVY,
            "axes.labelcolor": NAVY,
            "text.color": NAVY,
            "xtick.color": NAVY,
            "ytick.color": NAVY,
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def _short_hash(value: str, keep: int = 16) -> str:
    return value[:keep] + "…" if len(value) > keep else value


def _detection_map(report: dict) -> dict:
    if "detections" in report:
        return report["detections"]
    if "attack_detections" in report:
        return report["attack_detections"]
    raise KeyError("report must contain either 'detections' or 'attack_detections'")


def figure_watermark_diff(out: Path) -> None:
    work_dir = Path("results/figures_work")
    work_dir.mkdir(parents=True, exist_ok=True)
    master_seed, _ = master_seed_from_qrng(None, "qtracemark-demo-v1")
    layers = demo_layers(master_seed)
    source = make_source_image(work_dir / "source.png")
    watermarked = embed_layers(source, layers)

    src_y, _, _ = image_to_ycbcr_arrays(source)
    wm_y, _, _ = image_to_ycbcr_arrays(watermarked)
    diff = np.abs(wm_y - src_y)

    # Amplify: clamp display range low so the woven mid-frequency pattern is visible.
    vmax = max(1.5, float(np.percentile(diff, 97)))

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.8), constrained_layout=True)
    axes[0].imshow(np.asarray(source))
    axes[0].set_title("source")
    axes[1].imshow(np.asarray(watermarked))
    axes[1].set_title("watermarked (invisible)")
    heat = axes[2].imshow(diff, cmap="inferno", vmin=0, vmax=vmax)
    axes[2].set_title(f"|difference| amplified\nmax {diff.max():.1f}/255 (mean {diff.mean():.2f})")
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    cbar = fig.colorbar(heat, ax=axes[2], fraction=0.046, pad=0.04)
    cbar.set_label("luminance delta", color=NAVY)
    fig.suptitle("Q-TraceMark: watermark is visually imperceptible, present in frequency domain", color=NAVY, fontweight="bold")
    fig.savefig(out)
    plt.close(fig)


def figure_attack_confidence(report: dict, out: Path, title_suffix: str = "") -> None:
    detections = _detection_map(report)
    names = [n for n in ATTACK_ORDER if n in detections]
    work_conf, copy_conf, work_z, copy_z = [], [], [], []
    for name in names:
        rows = {row["layer_type"]: row for row in detections[name]}
        work_conf.append(rows["work"]["confidence"])
        copy_conf.append(rows["copy"]["confidence"])
        work_z.append(rows["work"]["z_score"])
        copy_z.append(rows["copy"]["z_score"])

    x = np.arange(len(names))
    width = 0.38
    fig, ax = plt.subplots(figsize=(11, 5.6))
    bars_w = ax.bar(x - width / 2, work_conf, width, label="work layer", color=BLUE)
    bars_c = ax.bar(x + width / 2, copy_conf, width, label="copy layer", color=TEAL)
    ax.axhline(0.95, color=RED, linestyle="--", linewidth=1.5, label="detection threshold 0.95")

    for bars, zs in ((bars_w, work_z), (bars_c, copy_z)):
        for bar, z in zip(bars, zs):
            ax.annotate(
                f"z={z:.1f}",
                (bar.get_x() + bar.get_width() / 2, min(bar.get_height(), 1.0)),
                textcoords="offset points",
                xytext=(0, 4),
                ha="center",
                fontsize=8,
                color=GRAY,
            )

    ax.set_xticks(x)
    ax.set_xticklabels([ATTACK_LABELS[n] for n in names])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("detection confidence")
    suffix = f" — {title_suffix}" if title_suffix else ""
    ax.set_title(f"Detection confidence per attack (work / copy fingerprints){suffix}")
    ax.legend(loc="center right", framealpha=0.95)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out)
    plt.close(fig)


def figure_fpr_thresholds(validation: dict, out: Path, title_suffix: str = "") -> None:
    fpa = validation["false_positive_analysis"]
    sweep = fpa["threshold_sweep"]
    thresholds = [s["threshold"] for s in sweep]
    fprs = [s["false_positive_rate"] for s in sweep]
    counts = [(s["false_positive_images"], fpa["samples"]) for s in sweep]
    max_null = fpa["max_null_confidence"]

    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    x = np.arange(len(thresholds))
    bars = ax.bar(x, fprs, width=0.5, color=BLUE)
    top = max(fprs + [0.05])
    ax.set_ylim(0, top * 1.25)
    for bar, (fp, n) in zip(bars, counts):
        ax.annotate(
            f"FPR {bar.get_height():.3f}\n({fp}/{n} images)",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            fontsize=10,
            color=NAVY,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t:g}" for t in thresholds])
    ax.set_xlabel("corrected-confidence threshold")
    ax.set_ylabel("false positive rate (unwatermarked controls)")
    suffix = f" — {title_suffix}" if title_suffix else ""
    ax.set_title(f"False positive rate controlled by threshold sweep{suffix}")
    ax.text(
        0.5,
        0.86,
        f"max confidence on {fpa['samples']} unwatermarked controls = {max_null:.3f}\n"
        f"threshold sweep reports empirical false positives",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color=GRAY,
        bbox=dict(boxstyle="round,pad=0.5", fc=LIGHT, ec=GRAY),
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out)
    plt.close(fig)


def _box(ax, x, y, w, h, title, lines, color):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.04",
            linewidth=1.6,
            edgecolor=color,
            facecolor="white",
        )
    )
    ax.text(x + w / 2, y + h - 0.10, title, ha="center", va="top", fontweight="bold", color=color, fontsize=11)
    ax.text(x + w / 2, y + h - 0.30, "\n".join(lines), ha="center", va="top", color=NAVY, fontsize=8.5, family="monospace")


def _arrow(ax, x0, y0, x1, y1):
    ax.add_patch(
        FancyArrowPatch(
            (x0, y0),
            (x1, y1),
            arrowstyle="-|>",
            mutation_scale=16,
            linewidth=1.6,
            color=GRAY,
        )
    )


def figure_evidence_package(report: dict, out: Path, title_suffix: str = "") -> None:
    detections = _detection_map(report)
    entropy = report["entropy_report"]
    work = next(l for l in report["layers"] if l["layer_type"] == "work")
    copy = next(l for l in report["layers"] if l["layer_type"] == "copy")
    wm_work = next(r for r in detections["watermarked"] if r["layer_type"] == "work")

    fig, ax = plt.subplots(figsize=(13.5, 4.2))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.4)
    ax.axis("off")

    boxes = [
        (
            "QRNG raw",
            [
                f"bytes: {entropy['byte_count']:,}",
                f"sha256: {_short_hash(entropy['sha256'])}",
                f"bit-1 ratio: {entropy['bit_one_ratio']:.4f}",
                f"entropy: {entropy['byte_entropy_bits_per_byte']:.3f} b/B",
            ],
            BLUE,
        ),
        (
            "Seed hashes",
            [
                f"master: {_short_hash(report['master_seed_hash'])}",
                f"work:   {_short_hash(work['seed_hash'])}",
                f"copy:   {_short_hash(copy['seed_hash'])}",
            ],
            TEAL,
        ),
        (
            "Issue log",
            [
                f"work_id: {report['work_id']}",
                f"copy_id: {report['copy_id']}",
                f"issued: {report.get('issued_at_utc', 'n/a')[:19]}",
                f"alpha w/c: {work['alpha']}/{copy['alpha']}",
            ],
            NAVY,
        ),
        (
            "Detection report",
            [
                f"layer: work",
                f"confidence: {wm_work['confidence']:.4f}",
                f"z-score: {wm_work['z_score']:.1f}",
                f"corrected p: {wm_work['p_value_corrected']:.1e}",
            ],
            RED,
        ),
    ]
    w, h, y = 2.7, 2.2, 0.7
    xs = [0.15, 3.15, 6.15, 9.15]
    for (title, lines, color), x in zip(boxes, xs):
        _box(ax, x, y, w, h, title, lines, color)
    for x in xs[:-1]:
        _arrow(ax, x + w + 0.02, y + h / 2, x + 3.0 - 0.02, y + h / 2)
    suffix = f" — {title_suffix}" if title_suffix else ""
    ax.set_title(f"Evidence package: QRNG raw → seed hashes → issue log → detection report{suffix}", color=NAVY, fontweight="bold")
    fig.savefig(out)
    plt.close(fig)


def figure_pipeline(out: Path) -> None:
    stages = [
        ("Creator\nupload", BLUE),
        ("QRNG seed\nissuance", TEAL),
        ("Watermark\nweaving", TEAL),
        ("Attack /\nrepost", RED),
        ("Detector", BLUE),
        ("Evidence\npackage", NAVY),
    ]
    fig, ax = plt.subplots(figsize=(13.5, 3.0))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 2.2)
    ax.axis("off")
    w, h, y = 1.55, 1.2, 0.5
    gap = (12 - w) / (len(stages) - 1)
    centers = []
    for i, (label, color) in enumerate(stages):
        x = i * gap
        centers.append(x + w / 2)
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                linewidth=1.8,
                edgecolor=color,
                facecolor="white",
            )
        )
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=color, fontweight="bold", fontsize=10)
        if i:
            _arrow(ax, (i - 1) * gap + w + 0.04, y + h / 2, x - 0.04, y + h / 2)
    ax.set_title("Q-TraceMark pipeline", color=NAVY, fontweight="bold")
    fig.savefig(out)
    plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Q-TraceMark presentation figures.")
    parser.add_argument("--demo-report", type=Path, default=ASSETS / "demo_report.json")
    parser.add_argument("--validation-report", type=Path, default=ASSETS / "validation_report.json")
    parser.add_argument("--evk-demo-report", type=Path, default=ASSETS / "evk_demo_report.json")
    parser.add_argument("--evk-validation-report", type=Path, default=ASSETS / "evk_validation_report.json")
    parser.add_argument("--out-dir", type=Path, default=ASSETS)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _style()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    demo = _load(args.demo_report)
    validation = _load(args.validation_report)
    evk_demo = _load(args.evk_demo_report) if args.evk_demo_report.exists() else None
    evk_validation = _load(args.evk_validation_report) if args.evk_validation_report.exists() else None

    outputs = {
        "fig_watermark_diff.png": lambda p: figure_watermark_diff(p),
        "fig_attack_confidence.png": lambda p: figure_attack_confidence(demo, p, "demo fallback"),
        "fig_fpr_thresholds.png": lambda p: figure_fpr_thresholds(validation, p, "demo fallback"),
        "fig_evidence_package.png": lambda p: figure_evidence_package(demo, p, "demo fallback"),
        "fig_qtracemark_pipeline.png": lambda p: figure_pipeline(p),
    }
    if evk_demo is not None:
        outputs["evk_fig_attack_confidence.png"] = lambda p: figure_attack_confidence(evk_demo, p, "EVK C seed")
        outputs["evk_fig_evidence_package.png"] = lambda p: figure_evidence_package(evk_demo, p, "EVK C seed")
    if evk_validation is not None:
        outputs["evk_fig_fpr_thresholds.png"] = lambda p: figure_fpr_thresholds(evk_validation, p, "EVK C seed")
    for name, fn in outputs.items():
        path = args.out_dir / name
        fn(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
