# camera_turntable_test.py — 카메라와 턴테이블을 같이 연결해 보는 테스트
# 카메라 영상을 보면서 R 키로 턴테이블을 10도씩 돌려 본다. R: 10도 회전 / Q: 종료
#     python camera_turntable_test.py
import cv2
from turntable import Turntable

# 턴테이블 연결
table = Turntable(port="COM3")

# OBS Virtual Camera
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("카메라 연결 실패")
    table.close()
    exit()

print("카메라 + 턴테이블 연결 성공")
print("R : 턴테이블 10도 회전")
print("Q : 종료")

while True:
    ret, frame = cap.read()

    if not ret:
        print("프레임 읽기 실패")
        break

    cv2.imshow("VisionQC Camera + Turntable Test", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("r"):
        # rotate() 는 회전 + 안정화(DONE)가 끝날 때까지 기다린다. 그동안 화면은 멈춘다
        print("10도 회전...")
        table.rotate(10)
        print("회전 완료")

    elif key == ord("q"):
        break

# 카메라, 턴테이블 포트, 창 정리
cap.release()
table.close()
cv2.destroyAllWindows()