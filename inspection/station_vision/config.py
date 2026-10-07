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

# ---- PatchCore (1단계 검사, inspection_app.py)
PATCHCORE_VIEWS = 8        # 한 바퀴에 멈춰서 찍는 장수 (8 → 45도씩)
PATCHCORE_CROP = "roi"     # "roi": 검사 영역을 감싸는 사각형만 / "full": 카메라 전체 화면
# PatchCore 모델 파일. 비워 두면 inspection/visionPatchCore/patchcore_export/models/v3/model.ckpt
# PATCHCORE_MODEL = r"C:\...\models\v4\model.ckpt"
