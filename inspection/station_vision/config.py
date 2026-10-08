"""TAuto 아두이노 연결 설정. D435용 captures/config.py와 독립적으로 관리한다.

turntable.py, yolo_live.py, inspection_app.py 가 import 해서 쓴다.
DB 저장 설정(DB_URL, STORAGE_DIR, PRODUCT)을 여기에 추가하면 inspection_app.py 가 그 값을 기본값으로 쓴다.
없으면 backend/.env 의 DATABASE_URL 과 backend/storage/images (MES 와 같은 PC 일 때).
  예) DB_URL = "mysql+pymysql://mes_user:mes_pass@192.168.0.10:3306/visionqc_mes?charset=utf8mb4"
      STORAGE_DIR = "//MES서버/images"   (MES 서버의 사진 폴더를 공유한 경로)
"""

# ---- 아두이노 시리얼 연결

SERIAL_PORT = "COM3"       # 아두이노 IDE에 표시되는 연결 포트
SERIAL_BAUD = 115200       # turntable/turntable.ino의 Serial.begin 값과 일치해야 함
SERIAL_TIMEOUT_S = 15      # 회전 + 1초 안정화 이후 DONE 응답 대기 제한

# ---- 회전 테스트 / 백래시(기어 유격)
N_VIEWS = 72              # 한 바퀴 회전 테스트에 사용
ANGLE_STEP_DEG = 360.0 / N_VIEWS   # 테스트 1회 회전 각도 (360 / 72 = 5도)
# 촬영 전에 이 각도만큼 정방향으로 회전한 뒤 그 위치를 0도로 삼는다.
# 실제 유격을 충분히 메울 수 있는 양수로 설정한다. 촬영 후 이 기준점으로 복귀한다.
BACKLASH_TAKEUP_DEG = 8.0

# ---- 3D 검사 (inspection_app.py 의 [3D 검사] 버튼)
# 축별 판정 한계 덮어쓰기 {축: (정상 한계, 불량 한계)} mm. 3D 코드(station_3d/config.py)는 수정하지 않고 실행할 때만 바꾼다.
# 축 이름은 3D 코드 기준: width 가로 / depth 세로(짧은 변, MES 의 length) / height 높이
# MES 쪽(backend/app/models.py 의 DIM_RECHECK_MM / DIM_TOLERANCE_MM, sql/schema.sql)과 같은 값으로 맞출 것
DIM_LIMITS_3D = {"width": (10.0, 10.0), "depth": (6.0, 6.0), "height": (6.0, 6.0)}   # 가로 ±10.0, 길이·높이 ±6.0 (정상 한계 = 불량 한계)
# 3D 스크립트를 돌릴 파이썬. 비워 두면 이 프로그램과 같은 환경 (open3d 가 이 환경에서 열려야 함)
# PYTHON_3D = r"C:\...\station_3d\.venv\Scripts\python.exe"
# 3D 코드 폴더. 최신 v2.6 (놓임 검사·인터락, rig_calibration.npz 포함)을 쓴다.
# 맨 위 station_3d 에는 rig_calibration.npz 가 없어서 스캔이 안 된다
import os as _os
STATION_3D_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "station_3d", "scanner_v2_6")

# ---- 카메라 / 학습 당시의 고정 ROI (PatchCore·YOLO 공통, 좌표는 원본 픽셀 기준. PREPROCESSING.md 참고)
CAMERA_INDEX = 5           # YOLO 검사 카메라 번호 (OpenCV/DirectShow). 카메라를 더 꽂으면 번호가 밀리므로 camera_check.py 로 확인
CAMERA_WIDTH = 1920        # 카메라가 이 크기(1920×1080)를 못 돌려주면 오류로 중단한다 (자동 확대하지 않음)
CAMERA_HEIGHT = 1080
ROI_WIDTH = 600
ROI_HEIGHT = 320
ROI_X = 640                # 학습·양품 촬영 기록에서 확인한 원본 픽셀 좌표 (왼쪽 위). 좌표를 모르면 임의로 바꾸지 말 것
ROI_Y = 390
YOLO_IMGSZ = 608           # YOLO 입력 크기: ROI 를 letterbox 로 608 에 맞춤 (직접 정사각형 resize 안 함)

# ---- PatchCore (1단계 검사, inspection_app.py)
PATCHCORE_VIEWS = 12       # 한 바퀴에 멈춰서 찍는 장수 (12 → 30도씩. 72 → 5도씩. 8 → 45도씩)
PATCHCORE_THRESHOLD = 0.7  # 판정 기준 (정규화 점수 0~1, 점수 >= 기준이면 불합격). 모델 기본값은 0.5
# PatchCore 모델 파일. 비워 두면 inspection/visionPatchCore/patchcore_export/models/v3/model.ckpt
# PATCHCORE_MODEL = r"C:\...\models\v4\model.ckpt"
