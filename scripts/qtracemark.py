from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


BLOCK = 8
DEFAULT_PERIOD = 17
MID_FREQ_COEFFS = (
    (1, 2),
    (2, 1),
    (1, 3),
    (3, 1),
    (2, 2),
    (2, 3),
    (3, 2),
    (1, 4),
    (4, 1),
    (2, 4),
    (4, 2),
)


def _dct_matrix(n: int = BLOCK) -> np.ndarray:
    matrix = np.zeros((n, n), dtype=np.float64)
    factor = math.pi / (2 * n)
    for k in range(n):
        alpha = math.sqrt(1 / n) if k == 0 else math.sqrt(2 / n)
        for i in range(n):
            matrix[k, i] = alpha * math.cos((2 * i + 1) * k * factor)
    return matrix


DCT = _dct_matrix()
IDCT = DCT.T


@dataclass(frozen=True)
class EntropyReport:
    byte_count: int
    sha256: str
    bit_one_ratio: float
    byte_entropy: float
    longest_run: int

    def as_dict(self) -> dict:
        return {
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "bit_one_ratio": self.bit_one_ratio,
            "byte_entropy_bits_per_byte": self.byte_entropy,
            "longest_run_bits": self.longest_run,
        }


@dataclass(frozen=True)
class LayerSpec:
    layer_type: str
    layer_id: str
    seed: bytes
    alpha: float
    density: float = 0.55
    period: int = DEFAULT_PERIOD

    @property
    def seed_hash(self) -> str:
        return hashlib.sha256(self.seed).hexdigest()


@dataclass(frozen=True)
class DetectionResult:
    layer_type: str
    layer_id: str
    confidence: float
    z_score: float
    mean_correlation: float
    samples: int
    best_phase: int
    detected: bool

    def as_dict(self) -> dict:
        return {
            "layer_type": self.layer_type,
            "layer_id": self.layer_id,
            "confidence": self.confidence,
            "z_score": self.z_score,
            "mean_correlation": self.mean_correlation,
            "samples": self.samples,
            "best_phase": self.best_phase,
            "detected": self.detected,
        }


def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def derive_seed(master_seed: bytes, *parts: str) -> bytes:
    h = hashlib.sha256()
    h.update(master_seed)
    for part in parts:
        h.update(b"\x00")
        h.update(part.encode("utf-8"))
    return h.digest()


def entropy_report(data: bytes) -> EntropyReport:
    if not data:
        raise ValueError("entropy_report requires non-empty data")
    arr = np.frombuffer(data, dtype=np.uint8)
    ones = int(np.unpackbits(arr).sum())
    bit_count = len(data) * 8
    counts = np.bincount(arr, minlength=256).astype(np.float64)
    probs = counts[counts > 0] / len(arr)
    entropy = float(-(probs * np.log2(probs)).sum())
    longest = _longest_bit_run(data)
    return EntropyReport(
        byte_count=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        bit_one_ratio=ones / bit_count,
        byte_entropy=entropy,
        longest_run=longest,
    )


def _longest_bit_run(data: bytes) -> int:
    best = 0
    current = 0
    prev = None
    for byte in data:
        for i in range(7, -1, -1):
            bit = (byte >> i) & 1
            if bit == prev:
                current += 1
            else:
                current = 1
                prev = bit
            best = max(best, current)
    return best


def master_seed_from_qrng(qrng_file: Path | None, label: str) -> tuple[bytes, EntropyReport]:
    if qrng_file is None:
        demo_bytes = _deterministic_demo_qrng(label, size=1024 * 1024)
        return derive_seed(sha256_bytes(demo_bytes), label), entropy_report(demo_bytes)
    data = qrng_file.read_bytes()
    return derive_seed(sha256_bytes(data), label), entropy_report(data)


def _deterministic_demo_qrng(label: str, size: int) -> bytes:
    # This fallback is only for reproducible demos when the EVK file is unavailable.
    # Lab runs should pass --qrng-file and use actual QRNG output.
    out = bytearray()
    counter = 0
    seed = hashlib.sha256(("demo-qtracemark:" + label).encode("utf-8")).digest()
    while len(out) < size:
        h = hashlib.sha256()
        h.update(seed)
        h.update(counter.to_bytes(8, "big"))
        out.extend(h.digest())
        counter += 1
    return bytes(out[:size])


def image_to_ycbcr_arrays(image: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ycbcr = image.convert("YCbCr")
    arr = np.asarray(ycbcr, dtype=np.float64)
    return arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]


def arrays_to_rgb(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> Image.Image:
    merged = np.stack(
        [
            np.clip(y, 0, 255),
            np.clip(cb, 0, 255),
            np.clip(cr, 0, 255),
        ],
        axis=2,
    ).astype(np.uint8)
    return Image.fromarray(merged, "YCbCr").convert("RGB")


def pad_to_block(arr: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    h, w = arr.shape
    pad_h = (BLOCK - h % BLOCK) % BLOCK
    pad_w = (BLOCK - w % BLOCK) % BLOCK
    if pad_h or pad_w:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w)), mode="edge")
    return arr, (h, w)


def unpad(arr: np.ndarray, original_shape: tuple[int, int]) -> np.ndarray:
    h, w = original_shape
    return arr[:h, :w]


def block_dct(block: np.ndarray) -> np.ndarray:
    return DCT @ (block - 128.0) @ DCT.T


def block_idct(coeff: np.ndarray) -> np.ndarray:
    return IDCT @ coeff @ IDCT.T + 128.0


def _hash_int(seed: bytes, layer_type: str, y_index: int, x_index: int, purpose: str) -> int:
    h = hashlib.sha256()
    h.update(seed)
    h.update(layer_type.encode("utf-8"))
    h.update(purpose.encode("utf-8"))
    h.update(y_index.to_bytes(4, "big", signed=False))
    h.update(x_index.to_bytes(4, "big", signed=False))
    return int.from_bytes(h.digest()[:8], "big")


def _pattern(seed: bytes, layer_type: str, pattern_y: int, pattern_x: int) -> tuple[bool, int, int]:
    gate = _hash_int(seed, layer_type, pattern_y, pattern_x, "gate")
    selected = (gate / (2**64 - 1)) < 0.55
    coeff_i = _hash_int(seed, layer_type, pattern_y, pattern_x, "coeff") % len(MID_FREQ_COEFFS)
    sign = 1 if (_hash_int(seed, layer_type, pattern_y, pattern_x, "sign") & 1) else -1
    return selected, coeff_i, sign


def embed_layers(image: Image.Image, layers: Iterable[LayerSpec]) -> Image.Image:
    y, cb, cr = image_to_ycbcr_arrays(image)
    y_padded, original_shape = pad_to_block(y)
    out = y_padded.copy()
    blocks_y = out.shape[0] // BLOCK
    blocks_x = out.shape[1] // BLOCK

    for by in range(blocks_y):
        for bx in range(blocks_x):
            coeff = block_dct(out[by * BLOCK : (by + 1) * BLOCK, bx * BLOCK : (bx + 1) * BLOCK])
            changed = False
            for layer in layers:
                pattern_y = by % layer.period
                pattern_x = bx % layer.period
                selected, coeff_i, sign = _pattern(layer.seed, layer.layer_type, pattern_y, pattern_x)
                if not selected:
                    continue
                u, v = MID_FREQ_COEFFS[coeff_i]
                coeff[u, v] += layer.alpha * sign
                changed = True
            if changed:
                out[by * BLOCK : (by + 1) * BLOCK, bx * BLOCK : (bx + 1) * BLOCK] = block_idct(coeff)

    out = unpad(out, original_shape)
    return arrays_to_rgb(out, cb, cr)


def detect_layer(image: Image.Image, layer: LayerSpec, threshold: float = 0.60) -> DetectionResult:
    y, _, _ = image_to_ycbcr_arrays(image)
    y_padded, _ = pad_to_block(y)
    blocks_y = y_padded.shape[0] // BLOCK
    blocks_x = y_padded.shape[1] // BLOCK
    block_coeffs: list[list[np.ndarray]] = []
    for by in range(blocks_y):
        row: list[np.ndarray] = []
        for bx in range(blocks_x):
            block = y_padded[by * BLOCK : (by + 1) * BLOCK, bx * BLOCK : (bx + 1) * BLOCK]
            row.append(block_dct(block))
        block_coeffs.append(row)

    best: DetectionResult | None = None
    for phase_y in range(layer.period):
        for phase_x in range(layer.period):
            phase = phase_y * layer.period + phase_x
            values: list[float] = []
            for by in range(blocks_y):
                for bx in range(blocks_x):
                    pattern_y = (by + phase_y) % layer.period
                    pattern_x = (bx + phase_x) % layer.period
                    selected, coeff_i, sign = _pattern(layer.seed, layer.layer_type, pattern_y, pattern_x)
                    if not selected:
                        continue
                    u, v = MID_FREQ_COEFFS[coeff_i]
                    values.append(float(sign * block_coeffs[by][bx][u, v]))
            if len(values) < 8:
                continue
            arr = np.asarray(values, dtype=np.float64)
            mean = float(arr.mean())
            std = float(arr.std(ddof=1)) if len(arr) > 1 else 1.0
            if std < 1e-9:
                std = 1.0
            z = mean / (std / math.sqrt(len(arr)))
            confidence = 1.0 / (1.0 + math.exp(-0.55 * (z - 2.0)))
            result = DetectionResult(
                layer_type=layer.layer_type,
                layer_id=layer.layer_id,
                confidence=float(confidence),
                z_score=float(z),
                mean_correlation=mean,
                samples=len(values),
                best_phase=phase,
                detected=confidence >= threshold,
            )
            if best is None or result.confidence > best.confidence:
                best = result
    if best is None:
        return DetectionResult(layer.layer_type, layer.layer_id, 0.0, 0.0, 0.0, 0, 0, False)
    return best


def detect_registry(image: Image.Image, layers: Iterable[LayerSpec], threshold: float = 0.60) -> list[DetectionResult]:
    return [detect_layer(image, layer, threshold=threshold) for layer in layers]


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
