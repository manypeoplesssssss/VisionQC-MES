# station_3d — 3D 스캔 치수 검사 프로그램 (자리)

3D 모델링 코드를 이 폴더에 넣습니다. 3D 환경 전용 가상환경을 이 폴더에 따로 만듭니다.

MES 로 보내는 부분은 `../common/mes_client.py` 를 씁니다.

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from mes_client import MESClient

mes = MESClient("http://<MES서버IP>:8000", api_key="<INGEST_API_KEY>")
iid = "20261006_inspection_143000_001"              # 날짜 포함 검사번호
mes.start(iid, "redcar", product_serial="RC-0001")   # 검사 시작
mes.send_dimension(iid, width, length, height,       # 실측 (mm). 합불은 MES 가 ±3mm 로 자동 판정
                   scan_file_path="scans/....ply")
```

이후 할 일
- 3D 측정 코드 넣기
- 측정이 끝나면 `../handoff/` 에 검사번호를 기록해서, 환경을 바꾼 뒤 `station_vision` 이 같은 검사에 이어 붙이게 하기
- `requirements.txt` (3D 환경 패키지 + requests)

# 실행 가이드 (코드 v2.6, 2026-10-06)

폴더 `D:\scanner_v2_1\scanner_v2_1`에서 실행하는 명령을 순서대로 정리한 문서다. 전체 변경 이력과 배선표는 `README.md`, 놓임 검사 병합 내용은 `claude/놓임검사_병합_기록.md`, 인터락은 `claude/인터락_병합_기록.md`를 본다.

*펌웨어(인터락·놓임 검사)는 아직 실기 검증 전이다. B단계에서 이상이 보이면 출력을 기록해 둔다.*

## A. 처음 한 번만 (배선·업로드·점검)

1. **터미널 열기 + 가상환경 켜기**

   ```text
   cd D:\scanner_v2_1\scanner_v2_1
   scanner\Scripts\activate
   ```

   폴더 안의 `scanner` 가상환경을 켠다. 이후 명령은 모두 이 창에서 실행한다.

2. **재배선** (명령 아님): 레이저를 D6/D7에서 **A2/A3**로 옮긴다. 모터 D2/D3/D6/D7, 초음파 D9~D12, 부저 D8, 리셋 버튼 D4, 광센서 A0/A1. 자세한 표는 README "인터락 + 놓임 검사 배선".

3. **펌웨어 업로드** (명령 아님): Arduino IDE에서 `turntable\turntable.ino`를 열어 우노 R3에 컴파일·업로드한다(AccelStepper 라이브러리 필요). 끝나면 **시리얼 모니터를 반드시 닫는다**(포트는 한 프로그램만 열 수 있음).

4. **코드 테스트**

   ```text
   python tests\test_pipeline.py
   ```

   카메라 없이 도는 테스트. "통과"가 **24개**면 최신 코드다.

5. **카메라 시리얼 확인** (카메라를 바꿨을 때만)

   ```text
   python d435_common.py
   ```

   D435 2대가 USB 3.x로 잡히는지 확인하고, 나온 시리얼을 `config.py`의 `CAM_A_SERIAL` / `CAM_B_SERIAL`에 따옴표로 넣는다.

## B. 아두이노 동작 확인 (펌웨어를 새로 올린 뒤)

6. **시리얼 원시 통신 확인**

   ```text
   python serial_check.py
   ```

   `READY`와 `STAT,RUN,...` 줄이 0.5초마다 나오면 정상. 거리값은 평소 35cm 이상이어야 한다. 부팅 때 `HINT,S1 reads ...`가 나오면 센서가 구조물을 향한 것이니 위치를 조정한다.

7. **인터락 손 시험** (명령 아님): 센서 앞에 손을 넣으면 정지하고 부저가 울린다. 손을 빼고 1초 뒤 부저가 깜빡이면 리셋 버튼으로 복귀.

8. **턴테이블 회전 테스트**

   ```text
   python turntable.py --test
   ```

   펜 마킹을 0도에 맞추고 Enter. 10도씩 36번 돌아 한 바퀴. 마킹이 제자리로 돌아오면 정상. 도는 중에 손을 넣어 정지·재개도 확인한다.

9. **레이저 빔 정렬**

   ```text
   python turntable.py --align
   ```

   두 빔이 광센서에 맞는 정도(%)가 나온다. 둘 다 **90% 이상**이면 LED가 켜진다. Ctrl+C로 종료.

10. **놓임 검사 시험**

    ```text
    python turntable.py --placement
    ```

    빔 사이를 완전히 비우고 Enter(보정) → 물체를 중앙 / 한쪽으로 치우침 / 없음 순서로 놓고 Enter(검사)를 반복해 `OK`, `OFFSET_X/Y`, `MISSING`이 맞는지 본다. `q`로 종료. 응답을 원시 그대로 보려면 `python serial_check.py --placement`.

## C. 캘리브레이션 (처음 설치했거나 카메라·턴테이블을 건드렸을 때만)

11. **리그 캘리브레이션**

    ```text
    python calibrate_rig.py --recalibrate
    python calibrate_rig.py --check
    ```

    체커보드로 카메라 간 → 회전축 → 원판 높이를 맞춘다. 첫 명령이 계산, 둘째가 두 카메라 정합 확인. 이미 `rig_calibration.npz`가 있고 장비를 안 건드렸다면 건너뛴다.

## D. 스캔·측정 (물체마다)

12. **놓임 검사 포함 자동 스캔**

    ```text
    python turntable_scan.py --name S01 --placement
    ```

    ① 턴테이블을 비우고 펜 마킹 0도 → Space (배경 촬영) ② 놓임 검사 보정(빔 사이 비어 있어야 함) ③ 물체를 올리고 Space → 놓임 검사. 불량이면 코드·설명이 나오니 다시 놓고 Enter, 중단은 `q` ④ 통과하면 72뷰 자동 스캔.

    - 항상 놓임 검사를 쓰려면 `config.py`에서 `PLACEMENT_CHECK = True` (그러면 `--placement` 생략 가능). 없이 스캔: `python turntable_scan.py --name S01`.
    - 두 카메라 IR 패턴 간섭이 보이면 `--alternate-emitter`.
    - 스캔 중 인터락이 걸리면 리셋 후 남은 각도부터 이어 간다(횟수는 `meta.json`의 `interlock_events`). 물체가 건드려졌다면 그 스캔은 버리고 다시 한다.

13. **병합**

    ```text
    python merge_turntable_scans.py
    ```

    최신 스캔 세션의 72뷰를 하나의 포인트클라우드로 합친다.

14. **측정·판정**

    ```text
    python measure_object.py --sample S01 --ref 195.0 83.8 58
    ```

    `--ref`는 캘리퍼스로 잰 긴 변·짧은 변·높이(mm). 전장·전폭·높이와 정상/재검/불량 판정을 출력하고 JSON으로도 저장한다.

15. **(선택) Visual Hull**

    ```text
    python visual_hull.py
    ```

    Open3D가 있는 Python 3.11/3.12 환경에서 실행.

## 참고

- 문제가 생기면 먼저 `python serial_check.py`로 보드가 응답하는지 본다.
- 포트가 `COM6`이 아니면 `config.py`의 `SERIAL_PORT`를 고치거나 명령에 `--port COM5`를 붙인다.
- 새 펌웨어를 올릴 때마다 시리얼 모니터를 닫는 것을 잊지 않는다.
- 놓임 검사는 보정(`K`) 후에만 동작한다. 부팅 직후 `BEAM_FAULT`는 정상이며 보정이 필요하다는 뜻이다.
