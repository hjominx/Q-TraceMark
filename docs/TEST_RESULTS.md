# Q-TraceMark 테스트 결과 리포트

- 실행일: 2026-06-07
- 대상 커밋: `31151f7` (main)
- 환경: Python 3.13.12 / numpy 2.4.4 / Pillow 12.2.0 / matplotlib 3.10.8 / macOS (darwin)
- 결과 요약: **전체 항목 PASS (11/11)**

## 1. 결과 요약표

| # | 항목 | 명령 | 결과 |
|---|---|---|---|
| 1 | 단위 테스트 | `pytest tests/` | ✅ 2 passed |
| 2 | 데모 실행 | `run_demo.py` | ✅ report/contact_sheet 생성 |
| 3 | 오탐률(합성 12) | `measure_fpr.py --samples 12` | ✅ 전 threshold FPR 0 |
| 4 | 통합 검증 | `run_validation_suite.py` | ✅ 공격 5종 PASS, source FP 없음 |
| 5 | figure 생성 | `make_figures.py` | ✅ 8개 생성 |
| 6 | QRNG 품질 재현 | `analyze_qrng_files.py` | ✅ 커밋본과 동일 |
| 7 | EVK seed 무결성 | hash/entropy 대조 | ✅ 문서값 일치 |
| 8 | 데모 검출 신뢰도 | demo_report.json | ✅ 분리 명확 |
| 9 | 히스토리 위생 | git 객체 스캔 | ✅ bin 0개 |
| 10 | 문서 링크 | md 링크 스캔 | ✅ 깨짐 없음 |
| 11 | EVK 리포트 | evk_*.json | ✅ 수치 일치 |

## 2. 상세 결과

### 2.1 단위 테스트 (pytest)

```
tests/test_qtracemark.py::test_embedded_layer_detects_on_simple_image          PASSED
tests/test_qtracemark.py::test_unwatermarked_image_does_not_detect_after_phase_correction PASSED
============================== 2 passed in 0.26s ===============================
```

- 양성 케이스: 워터마크 삽입본에서 검출 + confidence > 0.95
- 음성 케이스: 무워터마크 이미지에서 phase 보정 후 미검출

### 2.2 데모 검출 신뢰도 (`docs/assets/demo_report.json`)

| 조건 | work conf | work z | copy conf | copy z | 판정 |
|---|---:|---:|---:|---:|---|
| source (무워터마크) | 0.0000 | 0.6 | 0.0000 | 0.7 | 정상 미검출 |
| watermarked | 1.0000 | 24.6 | 1.0000 | 17.4 | PASS |
| jpeg_q70 | 1.0000 | 24.1 | 1.0000 | 19.4 | PASS |
| crop_50pct | 1.0000 | 18.5 | 1.0000 | 12.1 | PASS |
| brightness | 1.0000 | 10.4 | 1.0000 | 7.5 | PASS |
| pasted_fragment | 1.0000 | 10.2 | 1.0000 | 9.0 | PASS |

해석: 무워터마크 원본은 z≈0.6으로 완전히 분리되고, 모든 공격본은 z=7.5~24.6으로
강건하게 검출. 신호/잡음 분리가 명확하다.

### 2.3 오탐률 (FPR) — 합성 대조군 12장

| threshold | FPR | max null confidence |
|---:|---:|---:|
| 0.95 | 0.000 | 0.826 |
| 0.99 | 0.000 | (동일) |
| 0.999 | 0.000 | (동일) |

소규모(12장) 합성 대조군에서는 오탐 0. null 최대 confidence 0.826으로 0.95 threshold
아래 유지.

### 2.4 통합 검증 스위트 (`run_validation_suite.py`)

```
source_FP: False
attacks:   watermarked ✅  jpeg_q70 ✅  crop_50pct ✅  brightness ✅  pasted_fragment ✅
```

### 2.5 EVK 실제 QRNG 결과 (커밋된 리포트)

EVK seed 무결성 (`data/qrng/evk_C_1MB.bin`):

| 항목 | 측정값 | 문서값 | 일치 |
|---|---|---|---|
| SHA-256 | `f80e1b65…e8cf14` | `f80e1b65…e8cf14` | ✅ |
| bit-one ratio | 0.5001698732 | 0.5001698732 | ✅ |
| byte entropy | 7.999822 b/B | 7.9998220231 b/B | ✅ |
| longest run | 23 | 23 | ✅ |

QRNG 품질 리포트 재현: `analyze_qrng_files.py` 재실행 결과가 커밋본
(`evk_qrng_quality_report.json`, 12파일)과 그룹 통계 **완전 일치**.

EVK FPR sweep (합성 100 대조군, `evk_fpr_report.json`):

| threshold | FP / 표본 | FPR |
|---:|---:|---:|
| 0.95 | 4 / 100 | 0.04 |
| 0.99 | 1 / 100 | 0.01 |
| 0.999 | 0 / 100 | 0.00 |

max null confidence 0.9904 → **대조군을 12→100장으로 늘리자 0.95에서 4% 오탐이
드러남.** 증거용 판정에 0.999 threshold 권장의 실측 근거.

EVK 공격 검출 (`evk_validation_report.json`): source 미검출, watermarked·jpeg_q70·
crop_50pct·brightness·pasted_fragment 전부 검출.

### 2.6 figure 생성

`make_figures.py` 실행 → 8개 PNG 생성:

- demo: `fig_watermark_diff`, `fig_attack_confidence`, `fig_fpr_thresholds`,
  `fig_evidence_package`, `fig_qtracemark_pipeline`
- EVK: `evk_fig_attack_confidence`, `evk_fig_fpr_thresholds`, `evk_fig_evidence_package`

재생성 시 작업 트리 변화 없음(결정적 출력).

### 2.7 저장소 위생 / 무결성

- 전체 git 객체에서 `.bin` 블롭: **0개** (히스토리 purge 검증)
- `data/qrng` 추적 파일: `README.md` 단 1개
- 전체 마크다운 링크 스캔: **깨진 링크 없음**
- 전체 테스트 실행 후 작업 트리: clean

## 3. 재현 방법

```bash
python3 -m pytest tests/ -v
python3 scripts/run_demo.py
python3 scripts/measure_fpr.py --samples 12
python3 scripts/run_validation_suite.py
python3 scripts/make_figures.py
python3 scripts/analyze_qrng_files.py
```

## 4. 한계 / 주의

- FPR은 **합성 대조군** 기준. report-grade 수치는 실제 사진 대조군
  (`--controls-dir`)으로 재측정 필요.
- EVK seed `evk_C_1MB.bin`은 과거 공개 이력으로 폐기 대상 — 최종 실험은 새 EVK
  수집 파일로 재실행 권장 (수치는 위 결과로 재현 가능).
- 검출 robustness는 강한 AI 재생성·미세 crop·재촬영에서 저하될 수 있음(미검증).
- Bonferroni 보정은 seed 내부 phase 탐색(`period^2`)만 보정. 대규모 registry로 확장 시
  후보 수 보정 또는 registry-level FPR 측정 필요 (현재 2-layer PoC는 경험적 FPR로 방어).
