# EVK QRNG Raw Data

This local directory is the expected location for EVK QRNG raw binary files used
for the Q-TraceMark real-QRNG experiment run. The raw `.bin` files are ignored by
Git; the public repository keeps only this README plus derived hashes/statistics
under `docs/assets/`.

> **Security note.** Earlier revisions of this repository accidentally committed the
> raw `.bin` files, and that history was published. Those binaries have since been
> purged from Git history (`git filter-repo`), so the previously exposed seed source
> must be treated as compromised and **discarded**. For final/report-grade runs,
> collect a fresh EVK QRNG capture, keep it only in this local directory, and never
> commit raw `.bin` files — publish only hashes, statistics, and figures.

Expected local files:

- `evk_A_1MB.bin`: 1 MiB EVK sample A
- `evk_B_01.bin` ... `evk_B_10.bin`: ten 100 KiB repeat EVK samples
- `evk_C_1MB.bin`: 1 MiB EVK sample C, used as the primary seed source for the EVK demo

The generated quality summary is committed separately at:

- `docs/assets/evk_qrng_quality_report.json`

For the primary run, `evk_C_1MB.bin` had:

- SHA-256: `f80e1b6577c1c2439c6d71e66d6cd4c24ab7fd6701021358b7c822d031e8cf14`
- bit-one ratio: `0.5001698732`
- byte entropy: `7.9998220231` bits/byte
- longest run: `23` bits
