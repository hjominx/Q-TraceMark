from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from qtracemark import LayerSpec, derive_seed, detect_layer, embed_layers


def test_embedded_layer_detects_on_simple_image():
    image = Image.new("RGB", (256, 256), (180, 170, 150))
    seed = derive_seed(b"unit-test-master-seed", "work", "ART-TEST")
    layer = LayerSpec("work", "ART-TEST", seed, alpha=8.0)
    watermarked = embed_layers(image, [layer])
    result = detect_layer(watermarked, layer)
    assert result.detected
    assert result.confidence > 0.95


def test_unwatermarked_image_does_not_detect_after_phase_correction():
    image = Image.new("RGB", (256, 256), (180, 170, 150))
    seed = derive_seed(b"unit-test-master-seed", "work", "ART-TEST")
    layer = LayerSpec("work", "ART-TEST", seed, alpha=8.0)
    result = detect_layer(image, layer)
    assert not result.detected
    assert result.phase_trials == layer.period * layer.period


if __name__ == "__main__":
    test_embedded_layer_detects_on_simple_image()
    test_unwatermarked_image_does_not_detect_after_phase_correction()
