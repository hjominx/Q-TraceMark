# Q-TraceMark 실험 지시서

## 목적

EVK QRNG 기반 seed를 사용하여 이미지에 사본별 비가시성 포렌식 지문을 삽입하고,
크롭·압축·합성 이후에도 해당 지문을 검출할 수 있는지 확인한다.

## 준비물

- EVK QRNG 장치 또는 EVK에서 추출한 `.bin` 난수 파일
- Python 3
- `numpy`, `Pillow`
- 실험용 원본 이미지 3장 이상

## 1. QRNG 데이터 수집

가능하면 EVK 장치에서 1MB 이상의 원시 난수 파일을 저장한다.

권장 파일명:

```text
data/qrng/raw_YYYYMMDD.bin
```

수집한 파일에 대해 다음 값을 기록한다.

- 파일 크기
- SHA-256 hash
- bit 1 비율
- byte entropy
- longest run

## 2. Seed 생성

QRNG 원시 파일에서 다음 값을 생성한다.

```text
master_seed = SHA256(raw_qrng_bytes || experiment_label)
work_seed   = SHA256(master_seed || "work" || work_id)
copy_seed   = SHA256(master_seed || "copy" || copy_id)
```

실험 리포트에는 seed 원문이 아니라 seed hash를 기록한다.

## 3. 워터마크 삽입

이미지를 RGB에서 YCbCr로 변환한 뒤 Y 채널에 삽입한다.

- 블록 크기: 8x8
- 변환: 2D DCT
- 삽입 영역: 중주파수 계수
- 계층:
  - work layer: 강도 `alpha=10.0`
  - copy layer: 강도 `alpha=7.0`

## 4. 공격 이미지 생성

최소 다음 공격을 적용한다.

| 공격 | 조건 |
|---|---|
| JPEG 압축 | quality 70 |
| 크롭 | 전체 면적의 약 50% |
| 부분 합성 | 워터마크 이미지 일부를 다른 배경에 붙이기 |
| 밝기 변화 | brightness ±15% |

## 5. 검출

각 공격 이미지에 대해 registry에 저장된 후보 seed와 correlation score를 계산한다.
검출기는 crop offset을 모르는 상황을 가정해 여러 phase 후보를 탐색하므로,
최종 판정에는 다중비교 보정이 필요하다.

현재 PoC는 다음 값을 기록한다.

- 최고 z-score
- 단일검정 p-value
- Bonferroni 보정 p-value
- `phase_trials = period^2`
- `confidence = 1 - corrected_p_value`

판정 기준 예시:

| confidence | 판정 |
|---:|---|
| 0.95 이상 | PASS |
| 0.90 이상 | WARNING |
| 0.90 미만 | FAIL |

## 6. 오탐률 측정

검출률만 측정하면 증거 시스템으로 부족하다. 워터마크가 없는 이미지에서 얼마나 자주
false positive가 발생하는지도 측정해야 한다.

```bash
python3 scripts/measure_fpr.py --samples 100
```

권장 기록:

- 대조군 이미지 수
- false positive image count
- empirical FPR
- null 분포의 최대 confidence
- null 분포의 최소 보정 p-value
- threshold 선택 근거

### 6.1 실제 사진 대조군 (report-grade)

합성 그래디언트 대조군은 중주파 에너지가 거의 없어 host 간섭의 쉬운 케이스만 본다.
리포트용으로는 워터마크가 들어가지 않은 **실제 사진/텍스처 이미지**를 대조군으로 써야
null 분포의 꼬리를 보수적으로 측정할 수 있다.

1. 워터마크를 삽입한 적 없는 실제 사진을 한 폴더에 모은다. 권장 경로:

   ```text
   data/controls/
   ```

   - 작품과 무관한 사진, 다양한 텍스처(인물, 풍경, 패턴)를 섞는다.
   - 최소 50장, 가능하면 100장 이상.
   - 검출 대상 작품 자체는 절대 포함하지 않는다 (true negative 대조군이어야 함).

2. 실제 사진 폴더로 FPR을 측정한다.

   ```bash
   python3 scripts/measure_fpr.py --controls-dir data/controls --samples 100
   ```

   폴더에 이미지가 있으면 그 이미지들이 대조군으로 사용되고, 없으면 자동으로 합성
   대조군으로 폴백한다.

3. threshold별(0.95 / 0.99 / 0.999) false positive count와 FPR을 함께 기록한다.
   `--thresholds 0.95,0.99,0.999`가 기본값이며 필요시 조정한다.

### 6.2 통합 검증 스위프

검출률(공격 이미지)과 오탐률(대조군)을 한 번에 측정하고 단일 리포트로 남기려면
report-grade 검증 스위트를 사용한다.

```bash
python3 scripts/run_validation_suite.py --controls-dir data/controls --samples 100
```

결과는 `results/validation/validation_report.json`과 `docs/assets/validation_report.json`에
저장되며, 공격별 검출 결과와 threshold sweep FPR이 한 파일에 들어간다.

## 7. 기록할 결과

- 공격 조건
- work layer confidence
- copy layer confidence
- z-score
- 보정 전/후 p-value
- 사용된 QRNG hash
- seed hash
- 발급 timestamp
- 검출 성공/실패

## 8. 실제 EVK QRNG 실행

본 레포에는 수업 EVK 실습에서 추출한 `.bin` 파일을 `data/qrng/`에 포함한다. 실제 QRNG
기반 실행은 deterministic fallback이 아니라 `evk_C_1MB.bin`을 seed source로 사용한다.

```bash
python3 scripts/analyze_qrng_files.py --data-dir data/qrng --out docs/assets/evk_qrng_quality_report.json
python3 scripts/run_demo.py --qrng-file data/qrng/evk_C_1MB.bin --out results/evk_demo
python3 scripts/measure_fpr.py --qrng-file data/qrng/evk_C_1MB.bin --samples 100 --out results/evk_fpr/fpr_report.json
python3 scripts/run_validation_suite.py --qrng-file data/qrng/evk_C_1MB.bin --samples 100 --out results/evk_validation/validation_report.json --no-docs
```

`evk_C_1MB.bin`의 품질 요약:

| 항목 | 값 |
|---|---:|
| byte count | 1,048,576 |
| bit-one ratio | 0.5001698732 |
| byte entropy | 7.9998220231 bits/byte |
| longest run | 23 bits |

EVK FPR sweep에서는 threshold 0.95에서 4/100, 0.99에서 1/100, 0.999에서 0/100의
false positive가 관찰되었다. 따라서 발표와 보고서에서는 "검출기는 threshold sweep으로
운영되어야 하며, 증거용 판정에는 0.999 threshold를 권장한다"고 설명한다.

## 9. 주의사항

본 실험은 "복제 방지"가 아니라 "사후 추적" 실험이다. 강한 AI 재생성,
매우 작은 crop, 카메라 재촬영에서는 검출률이 낮아질 수 있다.
