# 스마트팩토리 AI — 3D 치수검사 코드 (D435 x2 + 아두이노 턴테이블)

2026-10-06 기준 v2.6 (v2.1 + 베타 테스트 패치 v2.1.1~v2.4.2 + 인터락 병합 v2.5 + 놓임 검사 병합 v2.6). 실기 결과: 장난감 자동차 5회 반복 오차 평균 전장 −0.50 / 전폭 +1.16 / 높이 +0.68mm, 정상/재검/불량 3단계 판정으로 높이 불량 2/2 검출. 실험 절차는 Claude Docs "3D 스캔 실험 절차서"를 따르세요.

## 카메라 역할

| 카메라 | 용도 | 쓰는 스크립트 |
| --- | --- | --- |
| 스캔용 D435 2대 (A·B, 같은 높이 수평 일직선, 상자 밖) | 3D 스캔 → 치수 측정, Visual Hull | calibrate_rig, turntable_scan, merge, measure, visual_hull |
| 결함진단 아이폰 14 Pro (내장 조명) | PatchCore·YOLO 데이터 수집 + 결함 검출 | 추후 개발 (이 폴더에 없음) |

## 환경

- **Python 3.11 또는 3.12** (Open3D가 3.13 미지원 — 팀 전원 같은 버전으로 통일)
- `pip install -r requirements.txt`
- 아두이노(턴테이블 + 인터락 + 놓임 검사, **보드 1개**): `turntable/turntable.ino` 업로드 (AccelStepper 라이브러리 필요, 우노 R3). **v2.5부터 모터 핀이 D2/D3/D6/D7, v2.6부터 레이저가 A2/A3로 바뀌었으니 아래 "인터락" 절의 배선표대로 연결**

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `config.py` | 모든 설정(카메라 시리얼, 해상도, 포트, 체커보드, ROI, 공차, 보정계수) |
| `d435_common.py` | D435 공통 함수. 단독 실행 시 카메라 목록·USB 규격 표시 |
| `rig.py` | 좌표 변환 수학 (카메라 A/B ↔ 턴테이블 좌표, 회전축 추정, 코너 순서 보정) |
| `turntable.py` | 아두이노 시리얼 핸드셰이크 + `--test` 회전 테스트 (v2.1.2: 포트 설정 고정, v2.5: 인터락 대기·재개, STAT/EVT/HINT 줄 무시, v2.6: `calibrate_placement()`·`check_placement()`·`--placement`·`--align`) |
| `serial_check.py` | (v2.1.2 신규) 턴테이블 원시 시리얼 진단 — 부팅 메시지와 P/Z/R10 응답을 그대로 출력 |
| `calibrate_rig.py` | [1/3] 카메라 간(여러 자세) → [2/3] 회전축 → [3/3] 원판 높이. 칸 크기 교차 검증, 카메라별 depth 스케일 출력, 회전축 측정 전 유격 제거 |
| `turntable_scan.py` | 자동 스캔 (`N_VIEWS`, 현재 5도 × 72뷰). 시작 전 유격 제거, 깊이 경계 픽셀은 점에서 제외 |
| `merge_turntable_scans.py` | 뷰 병합 + ICP 미세 보정 + 다시점 지지 필터 + 잡음 정리. 세션 폴더를 인자로 주면 기존 스캔 재병합, 생략하면 `views/`가 있는 최신 세션 |
| `measure_object.py` | 치수 측정(가로/세로는 양 끝 1% 제외, 최소~최대 병기) + 3단계 공차 판정(정상/재검/불량) + 캘리퍼스 비교 + JSON |
| `visual_hull.py` | (스트레치) 실루엣 복셀 카빙 + 포인트클라우드와 겹쳐 보기 |
| `turntable/turntable.ino` | 아두이노 펌웨어 (v2.6: 28BYJ-48 턴테이블 + 인터락 + 레이저 놓임 검사 통합 — 초음파 2개·부저·리셋 버튼·릴레이 선택, 논블로킹, 센서 고장(FAULT) 감지, 워치독, 맨 위 `ENABLE_TURNTABLE`/`ENABLE_PLACEMENT` 스위치) |
| `turntable/turntable_v2_5_interlock.ino.bak` | v2.5 펌웨어(인터락만) 백업 |
| `turntable/turntable_before_interlock.ino.bak` | 인터락 병합 전 원본 펌웨어(v2.1, 롤백용) |
| `placement/placement.ino` | (참고용 원본) v2.5까지 별도 보드로 쓰던 단독 놓임 검사 스케치. v2.6부터는 `turntable.ino`에 통합되어 쓰지 않음 (레이저 핀도 D6/D7 → A2/A3) |
| `interlock_centering/final_turntable.ino` | 이상훈이 올려 둔 병합 펌웨어 사본 — `turntable/turntable.ino`와 **바이트 단위로 동일**(10-06 확인). 기준 파일은 `turntable/turntable.ino` 하나로 두고 이 폴더는 지워도 됨. 한쪽만 고치면 어긋나니 고칠 땐 같이 |
| `sketch_oct6a/`, `sketch_oct6b/` | 아두이노 IDE가 만든 원본 스케치(각각 `turntable.ino`·`placement.ino`와 같은 코드). 정리해도 됨 |
| `tests/test_pipeline.py` | 카메라 없이 도는 합성 데이터 테스트 24개 (v2.5에서 인터락 재개·거부 2개, v2.6에서 놓임 검사 4개 추가, 마지막: `test_scan_ensure_placed_retry`) |

## 실행 순서 (요약)

```text
python tests\test_pipeline.py           # 24개 통과 확인 (개수로 최신 코드인지도 확인)
python d435_common.py                    # 시리얼·USB 3.x 확인 → config.py에 CAM_A/B_SERIAL (따옴표!)
python turntable.py --test               # 360도 후 펜 마킹 복귀 확인 (이상하면 python serial_check.py)
python turntable.py --align              # (v2.6) 레이저 빔 정렬: 두 값 90%↑ (Ctrl+C 종료)
python turntable.py --placement          # (v2.6) 놓임 검사 보정·시험 (빔 사이를 비우고 시작)
python calibrate_rig.py --recalibrate    # 설치 후 1회: 카메라 간(6~8자세) → 회전축 → 원판
python calibrate_rig.py --check          # 두 카메라 정합 눈으로 확인
python turntable_scan.py --name S01      # 자동 스캔 (config N_VIEWS, --views 36 으로 10도도 가능)
python turntable_scan.py --name S01 --placement   # (v2.6) 스캔 전 레이저 놓임 검사 통과 후 시작
python merge_turntable_scans.py
python measure_object.py --sample S01 --ref 195.0 83.8 58   # mm, 긴 변·짧은 변·높이(원판 윗면~최고점)
python visual_hull.py                    # (스트레치)
```

## v2.1 변경 (2026-09-30)

- 결함진단 카메라가 아이폰으로 바뀌어 D435 결함진단 설정과 `capture_defect_images.py` 제거
- 컬러 1920×1080 / depth 848×480 / 15fps로 분리 (depth는 1920×1080 불가, 최대 1280×720)
- 카메라 간 정합을 **여러 자세(최소 4, 권장 6~8)**로 모아 계산, 자세별 오차 표시·이상 자세 자동 제외
- 체커보드 **코너 순서 뒤집힘 자동 보정** (카메라 간: 회전이 작은 해 선택 / 회전축: 앞 각도에 맞춤)
- 시리얼 미지정 시 저장된 캘리브레이션의 A/B 시리얼을 따름, 스캔 때 시리얼이 다르면 중단
- 체커보드 기본 15mm, ROI 반경 13cm·높이 10cm (장난감 차체 기준), 스캔 사진 JPG 저장
- 미리보기는 960px로 줄여 표시 (1920 그대로는 느림)

## v2.1.1 / v2.1.2 패치 (2026-09-30, 베타 테스트 중)

- 증상: `turntable.py --test`에서 현재 각도(`P`) 응답이 `ERR` → `ValueError`. 펌웨어를 다시 올려도 동일
- 진단: `serial_check.py`로 보면 펌웨어·배선·포트는 정상. 실패하던 코드는 읽을 때마다 포트 timeout을 바꿨는데, Windows에서는 그때마다 포트가 재설정되며 아두이노 쪽으로 잡음 바이트가 들어가 다음 명령 앞에 붙음(`"\x00P"` → ERR)
- v2.1.1: 연결 직후 버퍼 정리(`_sync`) + ERR 1회 재시도 + 원인 안내 오류 (보험으로 유지)
- v2.1.2: **포트를 timeout 0.1초로 한 번 열고 이후 설정을 바꾸지 않음**(대기 시간은 코드가 직접 계산), READY 후 0.5초 대기, 재현 테스트 2개 추가
- 펌웨어(`turntable.ino`)는 변경 없음

## v2.1.3 ~ v2.3 패치 (2026-10-01, 베타 테스트 2일차)

| 버전 | 문제 (진행 기록 번호) | 수정 |
| --- | --- | --- |
| v2.1.3 | 칸 크기 설정 15mm vs 실제 20mm → 회전축 약 10cm 어긋나 병합이 도넛 모양 (P-28) | depth로 칸 크기를 재서 config와 8% 넘게 다르면 중단 (`check_square_size`, `rig.grid_square_size`) |
| v2.1.4 | 카메라 간 RMSE가 3.2mm로 증가한 원인 진단 | 카메라별 depth 칸 크기 출력 (1% 넘게 다르면 depth 스케일 차이 의심) |
| v2.1.5~2.1.6 | 원판을 손으로 거꾸로 돌려 기어 유격 → 첫 10도가 5.4도 (P-31) | `Turntable.take_up_backlash()`: 정방향 `BACKLASH_TAKEUP_DEG`(8도) 후 0도 지정. 스캔은 물체를 올리고 Space 직후, 회전축은 보드를 놓은 뒤 0도 촬영 직전 |
| v2.2 | 차 끝 깊이 경계의 회색 가짜 점, ICP가 2도 기준에 자주 걸림 (P-32) | 깊이 경계 필터 `DEPTH_EDGE_*`(스캔, 실루엣 마스크는 유지), 다시점 지지 필터 `MV_*`(병합), ICP 회전 한도 3도 |
| v2.3 | 측정이 가장자리 잡음 1%까지 포함해 +13mm 부풀림 (P-32) | 가로/세로 양 끝 `MEASURE_TRIM_PCT`(1%) 제외 + 최소~최대 병기, `--ref` cm 입력 경고, ICP 이동 한도 4mm |

## v2.4 ~ v2.4.2 패치 (2026-10-02, 자동차 5회 검증 + 불량 테스트)

| 버전 | 문제 (진행 기록 번호) | 수정 |
| --- | --- | --- |
| v2.4 | 캘리퍼스 기준 ±2mm 단일 공차면 스캐너 고유 편향(전폭 +1.16mm) 때문에 정상 차 2/5가 불량 (D-21) | `judge(dims, nominal, tol, recheck)`: 축별 한계(dict) + 3단계 판정 `OK`/`RECHECK`/`NG`, 종합 `result`. config `NOMINAL_MM` = 정상 차 5회 평균, `TOLERANCE_MM`(불량, 3σ) / `RECHECK_MM`(정상, 2σ) |
| v2.4.1 | 분석용 `scans/_analysis_tmp` 폴더가 이름순 맨 뒤라 "최신 세션"으로 잡혀 병합 실패 (P-34) | `latest_session()`이 `views/` 폴더가 있는 세션만 선택 |
| v2.4.2 | 불량 샘플에도 "추천 보정계수 0.9304"가 출력됨 | 종합 불량이면 보정계수 대신 "정상 샘플로만 보정" 안내 |

판정 기준(config, 10-02):

```python
NOMINAL_MM   = {"width": 194.50, "depth": 84.96, "height": 58.68}   # 정상 차 5회 스캔 평균 (골든 샘플)
TOLERANCE_MM = {"width": 2.5,    "depth": 3.5,   "height": 2.0}     # 넘으면 불량 (3σ)
RECHECK_MM   = {"width": 1.5,    "depth": 2.0,   "height": 1.5}     # 넘으면 재검 = 다시 스캔 (2σ)
```

재캘리브레이션 후에는 정상 차를 다시 스캔해 기준값을 새로 계산할 것.

## v2.5 패치 (2026-10-06, 인터락 병합)

| 버전 | 내용 | 수정 |
| --- | --- | --- |
| v2.5 | 안전 인터락을 3D 스캔 흐름에 통합 (D-25, P-38) | `turntable/turntable.ino` = 턴테이블 + 인터락 통합 펌웨어(논블로킹). `turntable.py`: 인터락 중 대기 → RUN 복귀 후 `P`로 정지 각도를 읽어 남은 각도만 이어서 회전(`rotate`), 상태 줄 `STAT,`/`EVT,`/`HINT,`를 응답으로 오인하지 않음. `turntable_scan.py`: `meta.json`에 `interlock_events`, `placement_check`(v2.6, `--placement`일 때 {ok, attempts, errors}) 기록. 테스트 2개 추가(20개) |

## v2.6 패치 (2026-10-06, 놓임 검사 병합)

| 버전 | 내용 | 변경 |
| --- | --- | --- |
| v2.6 | 인터락 보드와 놓임 검사(레이저 + 광센서)를 **한 보드·한 펌웨어·한 COM 포트**로 통합 (D-26) | `turntable.ino`: 놓임 검사를 논블로킹 상태머신으로 재작성(워치독 500ms·초음파 타이밍 유지), 명령 `C`(검사)·`K`(보정)·`L1/L0`(정렬; 턴테이블 `A<deg>`와 겹쳐 `A`에서 변경), 레이저 핀 D6/D7 → **A2/A3**(D6/D7은 모터), 인터락 시 검사·보정·정렬 즉시 중단(`PLACE,ERR,INTERLOCK`), 인터락 상태에선 `C/K/L` 거부, 이동 중·검사 중엔 서로 `ERR,BUSY`, 놓임 오류음은 인터락 경보보다 낮은 우선순위. `turntable.py`: `calibrate_placement()`·`check_placement()`(인터락이면 리셋 대기 후 재검사)·`--placement`·`--align`. `turntable_scan.py`: `--placement`(또는 `config.PLACEMENT_CHECK=True`)이면 배경 촬영 뒤 보정, 물체를 올린 뒤 `ensure_placed()`가 OK일 때까지 반복(통과해야 스캔 시작), 결과를 `meta.json`의 `placement_check`에 기록. 테스트 4개 추가(24개) |

## 출력 파일 (세션 폴더 `scans/<날짜_시각_이름>/`)

| 파일 | 만드는 스크립트 | 내용 |
| --- | --- | --- |
| `views/view_NN_XXXdeg.ply` | turntable_scan | 뷰별 점 구름(턴테이블 좌표, 캘리브레이션 자세) |
| `images/`, `masks/` | turntable_scan | 뷰별 컬러 사진·물체 마스크 |
| `rig_calibration.npz` | turntable_scan | 스캔 당시 캘리브레이션 복사본(numpy) |
| `meta.json` | turntable_scan (+merge가 `merged` 추가) | `created`, `views[]`(index·theta_deg·stem·n_points_a/b), `angle_step_deg`, `manual`, `alternate_emitter`, `cameras.A/B`(시리얼·컬러 내부 파라미터), `roi`(radius_m·height_m·plate_margin_m), `interlock_events`(v2.5), `placement_check`(v2.6, `--placement`일 때 `{ok, attempts, errors}`, 아니면 null), `merged`(path·n_points·icp) |
| `merged_model.ply` | merge | 병합 모델(x,y,z,법선,색, 미터). CloudCompare·MeshLab 등에서 바로 열림 |
| `measurement.json` | measure | `dimensions`(width=전장·depth=전폭·height), `dimensions_raw_minmax`, `trim_pct`, `n_points`(측정 직전 정리 후), `scale_correction`, `tolerance_mm`·`recheck_mm`, `judgement`(축별 nominal·deviation·ok_limit·ng_limit·status·ok + `result`·`pass`), `caliper_comparison`(caliper·scanned·error·error_pct) |

- 주의: 재검도 `ok: true`(불량만 false). 판정은 `status`/`result`로 볼 것.
- 아직 JSON에 없는 것: ICP 무시 뷰 수·뷰별 보정량, 캘리브레이션 수치(RMSE·축 잔차) — P-33 핵심 지표라 `meta.json`에 추가 예정(제안).

## 설정 입력 주의

- 시리얼·포트는 **문자열**: `CAM_A_SERIAL = "044122070500"`, `SERIAL_PORT = "COM6"` (따옴표 없으면 `SyntaxError: leading zeros`)
- 숫자는 따옴표 없이: `SQUARE_SIZE_M = 0.02005`

- `--ref`는 **mm**, 순서는 **긴 변 · 짧은 변 · 높이**(놓인 방향과 무관). 높이는 원판 윗면부터 최고점(자석 큐브로 들린 높이 포함)
- 체커보드는 10×7칸 = 내부 코너 9×6(`CHECKERBOARD = (9, 6)`), 20mm 보드면 `SQUARE_SIZE_M = 0.020`
- 회전축 측정 때 보드는 **원판 위에서 돌려** 비껴 놓기(원판을 손으로 거꾸로 돌리지 않기)

## 이전 상태 (10-02)

- 합성 테스트 18개 통과. 재캘리브레이션 5회차(카메라 간 0.97mm, 축 잔차 0.57mm). 자동차 5회 반복: 전장·높이 5/5 ±2mm, 전폭 3/5(평균 +1.16mm, P-33 조사 중). 불량 테스트 2회(높이 +11.86 / +7.33mm) 모두 불량 판정
- 사용자 PC config 주요값: 시리얼 A 044122070500 / B 044322072076, COM6, `SQUARE_SIZE_M` 0.020, `N_VIEWS` 72, `ROI_RADIUS_M` 0.115, `PLATE_MARGIN_M` 0.012, ICP 4mm/3도, `MEASURE_TRIM_PCT` 1.0, `NOMINAL_MM`·`TOLERANCE_MM`·`RECHECK_MM`(위 판정 기준)
- 남은 확인: P-33(ICP 무시 뷰 → 전폭 증가) — `ICP_MAX_CORRECTION_M` 0.006 재병합 실험, 작은 결함(3~6mm) 검출, 다른 물체로 재현성, MES 표시(3D 보기)

## 인터락 + 놓임 검사 배선 (v2.6, 아두이노 우노 R3)

`turntable/turntable.ino`는 턴테이블과 인터락이 합쳐진 펌웨어다. **기존(v2.1)과 모터 핀이 다르니 다시 연결할 것.**

| 부품 | 핀 |
| --- | --- |
| ULN2003 IN1 / IN2 / IN3 / IN4 | D2 / D3 / D6 / D7 (v2.1의 D8~D11에서 변경, 드라이버 +5V는 외부 전원·GND 공통) |
| HC-SR04 #1 | TRIG D9 / ECHO D10 |
| HC-SR04 #2 | TRIG D11 / ECHO D12 |
| KY-006 패시브 부저 | S D8 / − GND |
| KY-008 레이저 #1 / #2, KY-018 광센서 #1 / #2 (v2.6 놓임 검사) | 레이저 A2 / A3, 광센서 A0 / A1 (자세한 사용법은 "놓임 검사" 절) |
| 리셋 버튼 | D4 ↔ GND (내부 풀업). **위험 구역 바깥에서 구역 전체가 보이는 위치에 설치** |
| 릴레이 입력(선택) | D5 — 모터 드라이버 +5V 차단. Active-LOW 릴레이면 `MOTOR_RUN`/`MOTOR_STOP` 값을 서로 바꿈 |
| 상태 LED | D13 (RUN이면 꺼짐, 정지 상태면 켜짐) |

**상태와 동작**

- `RUN`: 평소. 모터 사용 가능.
- `TRIPPED`: 30cm 이내를 2회 연속 감지 → 모터 즉시 정지(코일 OFF, 릴레이 차단), 부저 3000Hz 연속음.
- `FAULT`: 센서가 5회 연속 무응답(`EXPECT_WALL`: 정상이면 벽에서 항상 에코가 돌아온다고 가정, 배선 끊김·가림 감지) → 사이렌음. 안전 쪽(fail-safe)으로 정지.
- 해제: 두 센서 모두 35cm 밖이 1초 이상 유지되면 부저가 깜빡이고(리셋 가능), 그때 리셋 버튼을 눌러야 `RUN` 복귀. 음소거 기능 없음.
- 부팅 시 센서 워밍업 후 `READY`. 부팅 직후 정지 범위 안에 구조물이 있으면 `HINT,S1 reads ...`로 알려 줌(센서 위치·각도 조정).
- 워치독(500ms)이 걸려 있어 펌웨어가 멈추면 보드가 리셋됨.

**시리얼 프로토콜**: 기존 `R<deg>`/`A<deg>`/`Z`/`P` + 응답 `DONE`에 더해 `ERR,INTERLOCK[,<각도>]`(이동 중 정지 / 정지 상태에서 명령 거부), `ERR,BUSY`, 그리고 0.5초마다 `STAT,<상태>,<cm1>,<cm2>`, 상태 전환 시 `EVT,<상태>`, 설치 힌트 `HINT,...`가 계속 온다. `STAT/EVT/HINT`는 응답이 아니라 상태 보고다.

**`turntable.py`의 처리**

1. `R` 명령 후 `ERR,INTERLOCK,<각도>`가 오면 경고를 출력하고 `RUN`이 될 때까지 무기한 대기(FAULT가 10초 넘게 이어지면 안내 반복).
2. 복귀하면 `P`로 실제 각도를 읽어 목표까지 남은 각도만 `R`로 이어서 회전 → 각도 오차 없음. 정지 상태에서 명령이 거부된 경우도 같은 방식(남은 각도 = 전체).
3. `turntable_scan.py`는 아무것도 할 필요 없이 `tt.rotate()`가 블로킹으로 기다린다. 발동 횟수는 `meta.json`의 `interlock_events`에 기록.

**주의**

- 인터락이 걸렸다 풀린 뒤 찍은 뷰는 사람이 들어갔다 나오며 물체가 밀렸을 수 있다 → 물체가 움직였으면 그 스캔을 폐기하고 다시 스캔(명령 각도를 믿는 구조, P-31과 같은 원리). 정지는 감속 없이 즉시이므로 스텝이 소폭 어긋날 수 있음.
- 센서 시야에 물체·원판·상자 벽이 30cm 안에 들어오면 항상 걸린다 → 설치 후 `STAT` 값(`python serial_check.py`)으로 평상시 거리가 35cm 넘는지 확인.
- HC-SR04는 안전 인증 센서가 아니며 손·천 반사가 약함 → 발표에서는 "데모용 인터록"으로 표현.
- 우노는 포트를 열 때마다 리셋되고 센서 워밍업까지 2~3초 걸림(`turntable.py`가 READY를 기다림). 안돈/MES가 같은 COM 포트를 쓰면 충돌하므로 한 프로그램만 열 것.

## 놓임 검사 (v2.6, 같은 보드)

KY-008 레이저 2개와 KY-018(LDR) 2개로 물체가 십자 위치에 정확히 놓였는지 확인한다. 시나리오: 로봇팔이 놓음 → **놓임 검사 OK → 3D 스캔·객체 검출 시작**.

| 부품 | 핀 |
| --- | --- |
| KY-008 레이저 #1 / #2 | A2 / A3 (디지털 출력) |
| KY-018 광센서 #1 / #2 | A0 / A1 |
| 부저·LED | D8 / D13 (인터락과 공용. 인터락 경보가 항상 우선) |

| 명령 | 응답 |
| --- | --- |
| `K` 빔 보정 (빔 사이를 비우고, 약 2.5초) | `CAL,OK` / `CAL,ERR,<마스크>` / `CAL,ERR,INTERLOCK` |
| `C` 검사 (약 2.5~9초) | `PLACE,OK` / `PLACE,ERR,<OFFSET_X\|OFFSET_Y\|MISSING\|BEAM_FAULT\|UNSTABLE\|INTERLOCK>` |
| `L1` / `L0` 정렬 모드 | `BEAM,<a%>,<b%>` 0.3초마다 (둘 다 90%↑이면 LED) |

사용 순서:

1. **빔 정렬**: `python turntable.py --align` → 두 값이 90% 이상이 되도록 레이저/광센서 위치를 조정 (Ctrl+C 종료).
2. **단독 테스트**: `python turntable.py --placement` → 빔 사이를 비우고 Enter(보정) → 물체를 놓고 Enter(검사) 반복.
3. **스캔에 연결**: `python turntable_scan.py --placement` (또는 `config.py`의 `PLACEMENT_CHECK = True`). 배경 촬영 직후 보정하고, 물체를 올린 뒤 놓임 검사가 OK일 때까지 다시 놓으라고 안내한 다음 스캔을 시작한다.

부팅 직후에는 보정 전이라 `C`가 `BEAM_FAULT`를 낸다(보정 `K`를 먼저). 검사·보정 중 손이 들어와 인터락이 걸리면 즉시 중단되고, 호스트는 리셋 후 검사를 다시 한다. `ENABLE_PLACEMENT`를 0으로 하면 놓임 검사가 펌웨어에서 빠진다.

## 현재 상태 (10-06)

- 합성 테스트 24개 통과(인터락 2개·놓임 검사 4개 포함). 펌웨어는 Arduino 컴파일러 없이 스텁 헤더로 문법만 검사(4가지 스위치 조합 통과, 실제 컴파일 아님). **인터락·놓임 검사 포함 펌웨어는 실기 미검증** — 업로드 후 확인 순서: ① `python serial_check.py`로 STAT 거리값 확인(평상시 35cm 초과) ② 손을 넣어 TRIPPED·부저·모터 정지 ③ 구역을 비우고 1초 뒤 부저 깜빡임 → 리셋 버튼 ④ `python turntable.py --test` 중 손을 넣어 정지·재개 후 한 바퀴 뒤 펜 마킹 복귀 확인.
- 놓임 검사 실기 확인 순서: ⑤ `python turntable.py --align`으로 두 빔 90%↑ ⑥ `--placement`로 보정·검사(중앙/좌우 치우침/없음) ⑦ 검사 중 손을 넣어 인터락 중단·리셋 후 재검사 ⑧ `turntable_scan.py --placement`.
- 남은 확인: P-33(ICP 무시 뷰 → 전폭 증가), 다른 물체로 재현성, MES 3D 표시, MES와의 상태·판정 연동(재검 처리).
