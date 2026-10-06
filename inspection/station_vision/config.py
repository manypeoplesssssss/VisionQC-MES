"""TAuto 아두이노 연결 설정. D435용 captures/config.py와 독립적으로 관리한다.

turntable.py, yolo_live.py, inspection_app.py 가 import 해서 쓴다.
MES 전송 설정(MES_URL, MES_API_KEY, MES_ITEM, MES_SERIAL_PREFIX)을 여기에 추가하면
inspection_app.py 가 그 값을 기본값으로 쓴다 (없으면 inspection_app.py 안의 기본값).
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
