from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from qtracemark import (
    LayerSpec,
    derive_seed,
    detect_registry,
    embed_layers,
    master_seed_from_qrng,
    save_json,
)


def make_source_image(path: Path, size: tuple[int, int] = (768, 512)) -> Image.Image:
    img = Image.new("RGB", size, (245, 242, 232))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.rectangle((0, 0, w, h), fill=(242, 239, 229))
    for i in range(18):
        x0 = int((i * 47) % w)
        color = (90 + i * 5 % 80, 125 + i * 9 % 90, 150 + i * 7 % 80)
        draw.line((x0, 0, (x0 + 220) % w, h), fill=color, width=3)
    draw.ellipse((90, 90, 330, 330), fill=(215, 112, 101), outline=(80, 70, 60), width=5)
    draw.rectangle((410, 105, 690, 365), fill=(82, 132, 150), outline=(45, 62, 75), width=5)
    draw.polygon([(535, 58), (715, 225), (610, 430), (430, 420), (350, 190)], fill=(236, 190, 92), outline=(72, 61, 45))
    draw.arc((120, 140, 300, 290), start=15, end=340, fill=(255, 248, 230), width=10)
    draw.line((450, 205, 650, 290), fill=(255, 248, 230), width=12)
    draw.line((450, 290, 650, 205), fill=(255, 248, 230), width=12)
    font = ImageFont.load_default()
    draw.text((38, 42), "Q-TraceMark demo artwork", fill=(38, 42, 50), font=font)
    draw.text((40, h - 50), "source image / generated for PoC", fill=(38, 42, 50), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def make_attacks(watermarked: Image.Image, source: Image.Image, out_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[int, int, int, int]]]:
    attacks: dict[str, Path] = {}
    regions: dict[str, tuple[int, int, int, int]] = {}

    jpeg_path = out_dir / "attack_jpeg.jpg"
    watermarked.save(jpeg_path, quality=70)
    attacks["jpeg_q70"] = jpeg_path

    crop_path = out_dir / "attack_crop.png"
    crop = watermarked.crop((160, 96, 672, 432))
    crop.save(crop_path)
    attacks["crop_50pct"] = crop_path

    bright_path = out_dir / "attack_brightness.png"
    bright = ImageEnhance.Brightness(watermarked).enhance(1.18)
    bright = ImageEnhance.Contrast(bright).enhance(0.92)
    bright.save(bright_path)
    attacks["brightness"] = bright_path

    paste_path = out_dir / "attack_paste.png"
    background = Image.new("RGB", watermarked.size, (225, 230, 235))
    draw = ImageDraw.Draw(background)
    for x in range(0, background.size[0], 32):
        draw.line((x, 0, x, background.size[1]), fill=(205, 212, 220), width=1)
    patch = watermarked.crop((96, 96, 448, 384))
    paste_box = (224, 112, 576, 400)
    background.paste(patch, paste_box[:2])
    draw.rectangle(paste_box, outline=(200, 60, 60), width=4)
    draw.text((226, 88), "suspected pasted fragment", fill=(70, 50, 50), font=ImageFont.load_default())
    background.save(paste_path)
    attacks["pasted_fragment"] = paste_path
    regions["pasted_fragment"] = paste_box

    return attacks, regions


def make_contact_sheet(paths: dict[str, Path], report: dict, out_path: Path) -> None:
    thumb_w, thumb_h = 300, 200
    items = [
        ("source", paths["source"]),
        ("watermarked", paths["watermarked"]),
        ("jpeg q70", paths["jpeg_q70"]),
        ("crop", paths["crop_50pct"]),
        ("brightness", paths["brightness"]),
        ("pasted fragment", paths["pasted_fragment"]),
    ]
    sheet = Image.new("RGB", (960, 720), (250, 250, 248))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for idx, (label, path) in enumerate(items):
        img = Image.open(path).convert("RGB")
        img.thumbnail((thumb_w, thumb_h))
        x = 24 + (idx % 3) * 312
        y = 36 + (idx // 3) * 250
        sheet.paste(img, (x, y))
        draw.text((x, y + thumb_h + 8), label, fill=(30, 36, 42), font=font)
    y0 = 560
    draw.text((24, y0), "Detection summary", fill=(20, 24, 30), font=font)
    y = y0 + 24
    for attack_name, rows in report["detections"].items():
        short = []
        for row in rows:
            status = "PASS" if row["detected"] else "FAIL"
            short.append(f'{row["layer_type"]}:{row["confidence"]:.2f}/{status}')
        draw.text((24, y), f"{attack_name}: " + "  ".join(short), fill=(20, 24, 30), font=font)
        y += 20
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Q-TraceMark PoC demo.")
    parser.add_argument("--qrng-file", type=Path, default=None, help="Optional EVK QRNG raw .bin file")
    parser.add_argument("--out", type=Path, default=Path("results/demo"), help="Output directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    master_seed, entropy = master_seed_from_qrng(args.qrng_file, "qtracemark-demo-v1")
    work_id = "ART-2026-QRNG-001"
    copy_id = "COPY-PLATFORM-A-USER-8832"
    work_seed = derive_seed(master_seed, "work", work_id)
    copy_seed = derive_seed(master_seed, "copy", copy_id)
    layers = [
        LayerSpec("work", work_id, work_seed, alpha=10.0),
        LayerSpec("copy", copy_id, copy_seed, alpha=7.0),
    ]

    source_path = out_dir / "source.png"
    source = make_source_image(source_path)
    watermarked = embed_layers(source, layers)
    watermarked_path = out_dir / "watermarked.png"
    watermarked.save(watermarked_path)

    paths = {"source": source_path, "watermarked": watermarked_path}
    attack_paths, attack_regions = make_attacks(watermarked, source, out_dir)
    paths.update(attack_paths)

    detections = {}
    for name, path in paths.items():
        image = Image.open(path).convert("RGB")
        if name in attack_regions:
            image = image.crop(attack_regions[name])
        detections[name] = [row.as_dict() for row in detect_registry(image, layers)]

    evidence = {
        "project": "Q-TraceMark",
        "evidence_schema_version": "0.2",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "work_id": work_id,
        "copy_id": copy_id,
        "detection_threshold": 0.95,
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
        "detections": detections,
        "attack_regions": {name: list(box) for name, box in attack_regions.items()},
    }
    report_path = out_dir / "report.json"
    save_json(report_path, evidence)
    make_contact_sheet(paths, evidence, out_dir / "contact_sheet.png")

    print(json.dumps({"report": str(report_path), "contact_sheet": str(out_dir / "contact_sheet.png")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
