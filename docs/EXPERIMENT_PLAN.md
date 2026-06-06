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

## 8. 주의사항

본 실험은 "복제 방지"가 아니라 "사후 추적" 실험이다. 강한 AI 재생성,
매우 작은 crop, 카메라 재촬영에서는 검출률이 낮아질 수 있다.
