# Q-TraceMark 아키텍처

## 전체 흐름

```mermaid
flowchart LR
  A["Creator uploads image"] --> B["QRNG seed issuance"]
  B --> C["Randomness quality report"]
  C --> D["Watermark weaving"]
  D --> E["Watermarked copy delivery"]
  E --> F["Leak or repost"]
  F --> G["Detector"]
  G --> H["Registry lookup"]
  H --> I["Evidence package"]
```

## 발급 계층

Q-TraceMark는 하나의 seed만 쓰지 않습니다. 목적별로 계층을 나눕니다.

| 계층 | 의미 | 생성 시점 |
|---|---|---|
| `work_seed` | 원작품 식별 | 최초 등록 시 |
| `copy_seed` | 사용자/플랫폼 사본 식별 | 조회, 다운로드, 렌더링 시 |
| `session_seed` | 고위험 콘텐츠 세션 추적 | 선택적으로 실시간 발급 |

## Watermark Weaving

워터마크는 한 지점에 도장을 찍듯 넣지 않고, 이미지 전체에 직조하듯 분산 삽입합니다.

```text
work_id      = 굵은 실: 작품 전체에 반복
platform_id  = 중간 실: 플랫폼별 배포 경로
copy_id      = 얇은 실: 사용자/세션별 사본 경로
```

검출 시에는 남아 있는 조각에서 correlation peak를 찾아 어떤 실이 남아 있는지 복원합니다.

## PoC 삽입 방식

현재 PoC는 YCbCr의 Y 채널을 사용합니다.

1. RGB 이미지를 YCbCr로 변환
2. Y 채널을 8x8 블록으로 분할
3. 각 블록에 2D DCT 적용
4. QRNG seed로 선택한 중주파수 계수에 `+alpha` 또는 `-alpha` 삽입
5. inverse DCT로 이미지 복원

주파수 계수는 DC 성분과 고주파 끝단을 피하고, 중주파 영역만 사용합니다.

## 검출 방식

1. 의심 이미지의 Y 채널을 DCT로 변환
2. registry의 후보 seed를 사용해 동일한 계수 위치와 부호를 재생성
3. coefficient별 평균을 뺀 뒤 `sum(sign * centered_coefficient)` 형태의 correlation score 계산
4. crop offset을 모르는 상황을 가정해 phase 후보 전체에서 최고 z-score 탐색
5. `period^2`회 phase 탐색에 대해 Bonferroni 보정 p-value 계산
6. `confidence = 1 - corrected_p_value`가 threshold 이상이면 해당 work/copy seed 검출

이 보정은 중요합니다. 여러 phase를 동시에 시험하면 무워터마크 이미지에서도 우연히
높은 단일 z-score가 나올 수 있습니다. 따라서 evidence package에는 원시 z-score뿐 아니라
보정 전/후 p-value와 phase trial 수를 함께 기록합니다.

### 보정 범위의 한계 (registry-level FPR)

현재 Bonferroni 보정은 **한 seed 안의 phase 탐색 횟수(`period^2`)만** 보정합니다
(`qtracemark.py`의 `detect_layer`). `detect_registry`는 여러 후보 seed/layer를 각각
독립적으로 돌리므로, **후보 수에 대한 보정은 들어가지 않습니다.**

- 현재 PoC는 work/copy 2-layer만 조회하고, 경험적 FPR(무워터마크 대조군) sweep으로
  실제 오탐을 직접 측정하므로 안전합니다.
- 그러나 문서가 언급하는 "registry lookup / 대규모 seed index"로 확장하면, 후보가
  N개일 때 family-wise 오탐이 다시 N배로 부풀 수 있습니다.
- 대규모 서비스에서는 (1) phase + 후보 수를 함께 보정하거나, (2) registry 전체에 대한
  **registry-level 경험적 FPR**을 측정해 threshold를 정해야 합니다.

발표 시에는 "현재는 소규모 registry PoC이며, 대규모 운영에는 registry-level FPR 또는
후보 수 보정이 추가로 필요하다"고 명시하는 것이 안전합니다.

## 증거 패키지 구조

발급부터 검출까지의 hash 체인을 하나의 감사 가능한 패키지로 묶습니다.

## 유통 경로 추적

작품 지문과 사본 지문을 동시에 읽으면 다음과 같이 경로를 재구성할 수 있습니다.

```text
work_id ART-2026-0017
  -> platform_id WEBTOON-A
  -> copy_id USER-8832
  -> repost image detected
```

이는 "인터넷 전체 경로를 자동 추적"하는 기술이 아니라, Q-TraceMark가 발급한 사본
기록을 기준으로 유출 출발점을 좁히는 포렌식 기술입니다.
