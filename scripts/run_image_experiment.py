from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from qtracemark import (
    BLOCK,
    LayerSpec,
    derive_seed,
    detect_registry,
    embed_layers,
    image_to_ycbcr_arrays,
    master_seed_from_qrng,
    save_json,
)


ATTACK_ORDER = ["source", "watermarked", "jpeg_q70", "crop_50pct", "brightness", "pasted_fragment"]
ATTACK_LABELS = {
    "source": "source\n(no mark)",
    "watermarked": "watermarked",
    "jpeg_q70": "JPEG q70",
    "crop_50pct": "crop 50%",
    "brightness": "brightness",
    "pasted_fragment": "pasted\nfragment ROI",
}


def align_down(value: int, quantum: int = BLOCK) -> int:
    return max(0, (value // quantum) * quantum)


def align_up(value: int, limit: int, quantum: int = BLOCK) -> int:
    return min(limit, ((value + quantum - 1) // quantum) * quantum)


def fit_image(image: Image.Image, max_long_edge: int) -> Image.Image:
    width, height = image.size
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return image.copy()
    scale = max_long_edge / long_edge
    size = (int(round(width * scale)), int(round(height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def make_attacks(watermarked: Image.Image, out_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[int, int, int, int]]]:
    width, height = watermarked.size
    attacks: dict[str, Path] = {}
    regions: dict[str, tuple[int, int, int, int]] = {}

    jpeg_path = out_dir / "attack_jpeg_q70.jpg"
    watermarked.save(jpeg_path, quality=70, optimize=True)
    attacks["jpeg_q70"] = jpeg_path

    crop_box = (
        align_down(int(width * 0.16)),
        align_down(int(height * 0.18)),
        align_up(int(width * 0.86), width),
        align_up(int(height * 0.88), height),
    )
    crop_path = out_dir / "attack_crop_50pct.png"
    watermarked.crop(crop_box).save(crop_path)
    attacks["crop_50pct"] = crop_path

    bright_path = out_dir / "attack_brightness.png"
    bright = ImageEnhance.Brightness(watermarked).enhance(1.14)
    bright = ImageEnhance.Contrast(bright).enhance(0.94)
    bright.save(bright_path)
    attacks["brightness"] = bright_path

    patch_box = (
        align_down(int(width * 0.18)),
        align_down(int(height * 0.34)),
        align_up(int(width * 0.72), width),
        align_up(int(height * 0.82), height),
    )
    patch = watermarked.crop(patch_box)
    background = watermarked.filter(ImageFilter.GaussianBlur(radius=12)).convert("RGB")
    overlay = Image.new("RGB", background.size, (230, 235, 240))
    background = Image.blend(background, overlay, 0.58)
    paste_x = align_down(int(width * 0.28))
    paste_y = align_down(int(height * 0.18))
    paste_box = (paste_x, paste_y, paste_x + patch.size[0], paste_y + patch.size[1])
    background.paste(patch, (paste_x, paste_y))
    draw = ImageDraw.Draw(background)
    draw.rectangle(paste_box, outline=(220, 75, 85), width=max(3, width // 350))
    draw.text((paste_x + 8, max(8, paste_y - 24)), "suspected repost fragment", fill=(80, 45, 45), font=ImageFont.load_default())
    paste_path = out_dir / "attack_pasted_fragment.png"
    background.save(paste_path)
    attacks["pasted_fragment"] = paste_path
    regions["pasted_fragment"] = paste_box

    return attacks, regions


def make_contact_sheet(paths: dict[str, Path], report: dict, out_path: Path) -> None:
    thumb_w, thumb_h = 360, 240
    items = [(name, paths[name]) for name in ATTACK_ORDER if name in paths]
    sheet = Image.new("RGB", (1140, 860), (250, 250, 248))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, (name, path) in enumerate(items):
        img = Image.open(path).convert("RGB")
        img.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = 30 + (idx % 3) * 370
        y = 36 + (idx // 3) * 290
        sheet.paste(img, (x, y))
        draw.text((x, y + thumb_h + 8), ATTACK_LABELS.get(name, name).replace("\n", " "), fill=(26, 32, 40), font=font)

    y = 640
    draw.text((30, y), "Q-TraceMark detection summary", fill=(20, 24, 30), font=font)
    y += 26
    for attack_name in ATTACK_ORDER:
        if attack_name not in report["detections"]:
            continue
        short = []
        for row in report["detections"][attack_name]:
            status = "PASS" if row["detected"] else "FAIL"
            short.append(f'{row["layer_type"]}:{row["confidence"]:.3f}/{status}')
        draw.text((30, y), f"{attack_name}: " + "  ".join(short), fill=(20, 24, 30), font=font)
        y += 22
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def make_diff_figure(source: Image.Image, watermarked: Image.Image, out_path: Path) -> None:
    src_y, _, _ = image_to_ycbcr_arrays(source)
    wm_y, _, _ = image_to_ycbcr_arrays(watermarked)
    diff = np.abs(wm_y - src_y)
    vmax = max(1.5, float(np.percentile(diff, 98)))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), constrained_layout=True)
    axes[0].imshow(np.asarray(source))
    axes[0].set_title("source photo")
    axes[1].imshow(np.asarray(watermarked))
    axes[1].set_title("watermarked")
    heat = axes[2].imshow(diff, cmap="inferno", vmin=0, vmax=vmax)
    axes[2].set_title(f"amplified |delta Y|\nmax {diff.max():.1f}/255, mean {diff.mean():.2f}")
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(heat, ax=axes[2], fraction=0.046, pad=0.04)
    fig.suptitle("Invisible fingerprint on real photo: visually stable, measurable in luminance/DCT domain")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def make_confidence_figure(report: dict, out_path: Path) -> None:
    names = [name for name in ATTACK_ORDER if name in report["detections"]]
    work_conf, copy_conf, work_z, copy_z = [], [], [], []
    for name in names:
        rows = {row["layer_type"]: row for row in report["detections"][name]}
        work_conf.append(rows["work"]["confidence"])
        copy_conf.append(rows["copy"]["confidence"])
        work_z.append(rows["work"]["z_score"])
        copy_z.append(rows["copy"]["z_score"])

    x = np.arange(len(names))
    width = 0.38
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bars_w = ax.bar(x - width / 2, work_conf, width, label="work layer", color="#2d6cdf")
    bars_c = ax.bar(x + width / 2, copy_conf, width, label="copy layer", color="#2a9d8f")
    ax.axhline(report["detection_threshold"], color="#e25563", linestyle="--", linewidth=1.5, label=f"threshold {report['detection_threshold']}")
    for bars, zs in ((bars_w, work_z), (bars_c, copy_z)):
        for bar, z in zip(bars, zs):
            ax.annotate(
                f"z={z:.1f}",
                (bar.get_x() + bar.get_width() / 2, min(1.0, bar.get_height())),
                textcoords="offset points",
                xytext=(0, 4),
                ha="center",
                fontsize=8,
                color="#6b7280",
            )
    ax.set_xticks(x)
    ax.set_xticklabels([ATTACK_LABELS.get(n, n) for n in names])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("corrected confidence")
    ax.set_title("Real-photo Q-TraceMark detection confidence")
    ax.legend(loc="center right", framealpha=0.95)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def write_presentation_notes(report: dict, out_path: Path) -> None:
    passed = [
        name
        for name in ATTACK_ORDER
        if name != "source"
        and name in report["detections"]
        and all(row["detected"] for row in report["detections"][name])
    ]
    failed = [
        name
        for name in ATTACK_ORDER
        if name != "source"
        and name in report["detections"]
        and not all(row["detected"] for row in report["detections"][name])
    ]
    if failed:
        claim = (
            "A real photo can receive work/copy forensic fingerprints that remain visually subtle; "
            f"in this run, {', '.join(passed) or 'no attacks'} passed while {', '.join(failed)} show the current PoC boundary."
        )
    else:
        claim = (
            "A real photo can receive work/copy forensic fingerprints that remain visually subtle "
            "and detectable after the tested JPEG, crop, brightness, and fragment repost attacks."
        )
    lines = [
        "# Q-TraceMark Photo Test Presentation Notes",
        "",
        "## One-sentence demo claim",
        "",
        claim,
        "",
        "## Slide-ready result table",
        "",
        "| Case | Work confidence | Copy confidence | Result |",
        "|---|---:|---:|---|",
    ]
    for name in ATTACK_ORDER:
        rows = report["detections"].get(name)
        if not rows:
            continue
        by_layer = {row["layer_type"]: row for row in rows}
        detected = all(row["detected"] for row in rows)
        result = "PASS" if detected else "FAIL"
        lines.append(
            f"| {name} | {by_layer['work']['confidence']:.4f} | {by_layer['copy']['confidence']:.4f} | {result} |"
        )
    lines.extend(
        [
            "",
        "## Recommended slide sequence",
        "",
        "1. Problem: image repost/crop makes visual search ambiguous.",
        "2. Idea: issue a per-work and per-copy fingerprint from QRNG-derived seed material.",
        "3. Real photo demo: show source vs watermarked vs amplified difference.",
        "4. Attack demo: JPEG, crop, brightness, pasted fragment.",
        "5. Evidence: confidence bars + QRNG hash/seed hash/timestamp package.",
        "6. Honest boundary: this is forensic tracing, not copy prevention; small fragments and hard transformations require stronger coding/registration.",
        "7. Final QRNG caveat: final presentation seed must come from a fresh local EVK capture.",
            "",
            "## Generated assets",
            "",
            f"- Contact sheet: `{report['assets']['contact_sheet']}`",
            f"- Difference figure: `{report['assets']['diff_figure']}`",
            f"- Confidence figure: `{report['assets']['confidence_figure']}`",
            f"- JSON evidence report: `{report['assets']['report_json']}`",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Q-TraceMark on a user-provided real image.")
    parser.add_argument("--image", type=Path, required=True, help="Source image path")
    parser.add_argument("--qrng-file", type=Path, default=None, help="Optional local EVK QRNG .bin file")
    parser.add_argument("--out", type=Path, default=Path("results/photo_experiment"), help="Output directory")
    parser.add_argument("--max-long-edge", type=int, default=1536, help="Resize long edge for PoC speed")
    parser.add_argument("--work-id", default="PHOTO-WARNEMUNDE-2026-001")
    parser.add_argument("--copy-id", default="COPY-DEMO-PRESENTATION-001")
    parser.add_argument("--work-alpha", type=float, default=10.0, help="DCT embedding strength for the work layer")
    parser.add_argument("--copy-alpha", type=float, default=7.0, help="DCT embedding strength for the copy layer")
    parser.add_argument("--threshold", type=float, default=0.95)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    image_bytes = args.image.read_bytes()
    original_sha256 = hashlib.sha256(image_bytes).hexdigest()
    source = fit_image(Image.open(args.image).convert("RGB"), args.max_long_edge)
    source_path = out_dir / "source_resized.png"
    source.save(source_path)

    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-photo-test-v1")
    work_seed = derive_seed(master_seed, "work", args.work_id)
    copy_seed = derive_seed(master_seed, "copy", args.copy_id)
    layers = [
        LayerSpec("work", args.work_id, work_seed, alpha=args.work_alpha),
        LayerSpec("copy", args.copy_id, copy_seed, alpha=args.copy_alpha),
    ]
    watermarked = embed_layers(source, layers)
    watermarked_path = out_dir / "watermarked.png"
    watermarked.save(watermarked_path)

    attack_paths, attack_regions = make_attacks(watermarked, out_dir)
    paths = {"source": source_path, "watermarked": watermarked_path, **attack_paths}
    detections = {}
    for name in ATTACK_ORDER:
        path = paths[name]
        image = Image.open(path).convert("RGB")
        if name in attack_regions:
            image = image.crop(attack_regions[name])
        detections[name] = [row.as_dict() for row in detect_registry(image, layers, threshold=args.threshold)]

    report = {
        "project": "Q-TraceMark",
        "report_type": "real_photo_experiment",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_image": {
            "input_path": str(args.image),
            "input_sha256": original_sha256,
            "original_size": list(Image.open(args.image).size),
            "working_size": list(source.size),
        },
        "qrng_source": str(args.qrng_file) if args.qrng_file else "deterministic demo fallback; use fresh EVK QRNG for final presentation",
        "entropy_report": entropy.as_dict(),
        "work_id": args.work_id,
        "copy_id": args.copy_id,
        "detection_threshold": args.threshold,
        "confidence_model": "one-sided z-test with Bonferroni correction over period^2 phase trials",
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
        "detections": detections,
        "attack_regions": {name: list(box) for name, box in attack_regions.items()},
    }

    report_path = out_dir / "report.json"
    contact_sheet = out_dir / "contact_sheet.png"
    diff_figure = out_dir / "diff_figure.png"
    confidence_figure = out_dir / "confidence_figure.png"
    notes_path = out_dir / "presentation_notes.md"
    report["assets"] = {
        "report_json": str(report_path),
        "contact_sheet": str(contact_sheet),
        "diff_figure": str(diff_figure),
        "confidence_figure": str(confidence_figure),
        "presentation_notes": str(notes_path),
    }
    save_json(report_path, report)
    make_contact_sheet(paths, report, contact_sheet)
    make_diff_figure(source, watermarked, diff_figure)
    make_confidence_figure(report, confidence_figure)
    write_presentation_notes(report, notes_path)

    summary = {
        "report": str(report_path),
        "working_size": list(source.size),
        "qrng_source": report["qrng_source"],
        "assets": report["assets"],
        "detection_pass": {
            name: all(row["detected"] for row in rows)
            for name, rows in detections.items()
            if name != "source"
        },
        "source_false_positive": any(row["detected"] for row in detections["source"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
