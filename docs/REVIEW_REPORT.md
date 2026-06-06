# Q-TraceMark 전체 검토 보고서

- 검토일: 2026-06-06
- 검토 대상 커밋: `30959db` (Add EVK QRNG experiment reports)
- 검토 범위: 소스 5개 스크립트, 테스트, 문서 5종, EVK 실험 리포트 6종, 원시 QRNG 데이터 12개

## 1. 종합 평가

연구/발표용 PoC로서 **완성도가 높고, 문서가 정직하다.** 4회의 반복 개선을 거치며
(초기 PoC → 통계 보정 → report-grade 검증 → 발표 figure → 실제 EVK 실행) 일관된
방향으로 발전했고, 핵심 주장("QRNG 기반 발급·감사·증거화 레이어")이 코드와 리포트로
뒷받침된다.

검증 결과 **문서가 인용한 수치는 모두 실제 데이터·리포트와 일치**했다(아래 §2). 다만
저장소 위생/일관성 측면에서 **반드시 고쳐야 할 문제 1건(Critical)과 발표 신뢰도에
영향을 주는 문제 1건(Major)** 이 있다.

| 영역 | 평가 |
|---|---|
| 알고리즘/통계 타당성 | 우수 (host-bias 제거 + Bonferroni 보정) |
| 재현성 | 우수 (모든 리포트 재생성 일치) |
| 문서 정직성 | 우수 (합성 대조군 사용을 명시) |
| 저장소 위생 | **결함 — raw .bin 커밋 (Critical)** |
| figure-결과 일관성 | **결함 — EVK 섹션에 demo figure (Major)** |

## 2. 검증 결과 (재현성)

직접 재실행하여 문서 주장과 대조했다. 전부 일치.

| 검증 항목 | 문서/리포트 주장 | 실측 | 일치 |
|---|---|---|---|
| `evk_C_1MB.bin` SHA-256 | `f80e1b65…e8cf14` | `f80e1b65…e8cf14` | ✅ |
| evk_C bit-one ratio | 0.5001698732 | 0.5001698732 | ✅ |
| evk_C byte entropy | 7.9998220231 b/B | 7.9998220231 b/B | ✅ |
| evk_C longest run | 23 bits | 23 bits | ✅ |
| deterministic fallback 여부 | (실제 QRNG) | fallback과 불일치 확인 | ✅ |
| QRNG quality report 그룹 통계 | 커밋본 | 재생성 결과 동일(타임스탬프 제외) | ✅ |
| EVK FPR sweep | 4/100, 1/100, 0/100 | 4/100, 1/100, 0/100 | ✅ |
| EVK 공격 검출 | 전부 PASS, source FAIL | 전부 PASS, source FAIL | ✅ |
| 단위 테스트 / run_demo / validation / make_figures | 통과 | 모두 통과 | ✅ |

**핵심 통계 발견(긍정):** 대조군을 12장에서 100장으로 늘리자 threshold 0.95에서 FPR이
0% → 4%로 드러났다. 이는 "소규모 대조군이 FPR을 과소평가한다"는 점을 실측으로 보여주며,
문서가 분쟁용 판정에 0.999를 권장한 근거로 타당하다.

## 3. 발견된 문제

### 3.1 [Critical] 원시 QRNG `.bin` 파일이 git에 커밋됨

`data/qrng/*.bin` 12개(합계 **3.0 MB**)가 추적되고 있다.

- 작업명령 3는 **"raw .bin은 GitHub에 올라가지 않음", "QRNG raw file 자체는 커밋하지 않음"**
  을 명시했으나 위반됨.
- `.gitignore`에 `data/qrng/` 항목이 없음 (현재 `results/*`만 무시).
- 영향: (1) 저장소가 바이너리로 비대해지고 히스토리에 영구 잔존, (2) 원시 엔트로피
  소스를 공개 배포하면 seed 발급의 비예측성 주장이 약화될 수 있음(증거성/보안 관점),
  (3) 과제 요구사항 불충족.

**권장 조치:**
1. `.gitignore`에 추가:
   ```
   data/qrng/*.bin
   ```
2. 추적 해제(파일은 로컬 보존):
   ```bash
   git rm --cached data/qrng/*.bin
   ```
3. 이미 push 되었다면 히스토리에서 제거 검토(`git filter-repo`). `data/qrng/README.md`와
   `docs/assets/evk_qrng_quality_report.json`(hash·통계만 포함)은 커밋 유지 가능 —
   raw가 없어도 증거 재현에 충분하다.

### 3.2 [Major] EVK 결과 섹션에 demo 데이터 figure가 삽입됨

`docs/PROJECT_BRIEF.md` §7.1 "실제 EVK QRNG 실행 결과"와 `README` "Actual EVK QRNG run"
인근에 `fig_attack_confidence.png`, `fig_fpr_thresholds.png`가 들어가 있다. 그러나 이
그림들은 `make_figures.py`가 **deterministic demo 리포트**(`validation_report.json`,
control_source=synthetic, **12장**, FPR **0/12**)로 렌더링한 것이다.

즉 본문 표는 EVK 100장 결과(FPR 4/100)를 말하는데, 같은 섹션의 그림은 demo 12장
결과(FPR 0/12)를 보여준다. 발표 중 "그림과 숫자가 다르다"는 질문을 받을 수 있고,
증거 시스템의 신뢰도를 떨어뜨린다.

**권장 조치(택1):**
- `make_figures.py`에 `--validation-report docs/assets/evk_validation_report.json`,
  `--demo-report docs/assets/evk_demo_report.json` 옵션으로 EVK 전용 figure
  (`fig_evk_*`)를 생성하고 EVK 섹션엔 그것을 삽입, 또는
- EVK 섹션의 그림을 빼고 demo 섹션에만 두고, 캡션에 "deterministic demo 데이터"임을 명시.

### 3.3 [Minor] 문서·의존성 소소한 불일치

- `docs/EXPERIMENT_PLAN.md` "준비물"이 여전히 `numpy, Pillow`만 명시. figure 생성에
  `matplotlib`이 필요하므로 추가 권장(`requirements.txt`에는 이미 반영됨).
- QRNG 원천 증명: 저장소만으로는 이 `.bin`이 양자 하드웨어 출력인지 일반 PRNG인지
  암호학적으로 증명 불가. 통계적으로 깨끗하고 deterministic fallback과는 다름을
  확인했으나, 발표 시 "출처는 EVK 실습 수집 절차에 근거"라고 정확히 표현할 것
  (이미 §9 발표 금지 표현 가이드와 부합).

## 4. 파일별 요약

| 파일 | 상태 | 비고 |
|---|---|---|
| `scripts/qtracemark.py` | 양호 | host-bias 제거 + Bonferroni, 핵심 로직 견고 |
| `scripts/run_demo.py` | 양호 | evidence에 timestamp/schema 포함 |
| `scripts/measure_fpr.py` | 양호 | controls-dir + threshold sweep, 재사용 헬퍼 분리 |
| `scripts/run_validation_suite.py` | 양호 | 검출+FPR 통합 리포트 |
| `scripts/make_figures.py` | 양호(주의) | EVK 전용 figure 미생성 (§3.2) |
| `scripts/analyze_qrng_files.py` | 양호 | 그룹 통계 재현 일치 |
| `tests/test_qtracemark.py` | 양호 | 양성/음성 2 케이스, 통과 |
| `docs/*.md` | 양호(수정요) | 수치 정확, figure 일관성만 보완 |
| `data/qrng/*.bin` | **문제** | 커밋 금지 대상 (§3.1) |
| `docs/assets/evk_*.json` | 양호 | hash·통계 기반, 재현 일치 |

## 5. 권장 조치 우선순위

1. **(즉시)** §3.1 — `.gitignore` 추가 + `git rm --cached`로 raw `.bin` 추적 해제.
2. **(발표 전)** §3.2 — EVK 섹션 그림을 EVK 데이터로 교체하거나 캡션 정정.
3. **(선택)** §3.3 — EXPERIMENT_PLAN 준비물에 matplotlib 추가, QRNG 출처 문구 점검.

세 가지를 반영하면 "데모가 잘 되는 PoC"를 넘어 **재현 가능하고 저장소 위생까지 갖춘
연구형 증거 시스템**으로 제출 가능한 상태가 된다. 알고리즘·통계·재현성은 이미 그 수준에
도달해 있다.
