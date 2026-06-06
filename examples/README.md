# Examples

Run the core demo:

```bash
python3 scripts/run_demo.py
```

Run a small empirical false-positive-rate check on unwatermarked control images:

```bash
python3 scripts/measure_fpr.py --samples 12
```

For report-grade numbers, increase the sample count and use the same EVK QRNG file used in the
watermark issuance experiment:

```bash
python3 scripts/measure_fpr.py --qrng-file /path/to/evk_C_1MB.bin --samples 100
```

