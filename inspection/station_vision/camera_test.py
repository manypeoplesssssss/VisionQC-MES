# camera_test.py — 카메라 연결만 확인하는 테스트
# 1번 카메라(OBS Virtual Camera 등) 영상을 창에 띄운다. Q: 종료
#     python camera_test.py
import cv2

# 1번 카메라를 DirectShow 로 연다 (0번은 보통 노트북 내장 카메라)
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("카메라 연결 실패")
    exit()

print("카메라 연결 성공")

while True:
    # 프레임 1장 읽기 (ret 이 False 면 카메라가 끊긴 것)
    ret, frame = cap.read()

    if not ret:
        print("프레임 읽기 실패")
        break

    cv2.imshow("OBS Virtual Camera Test", frame)

    # Q 를 누르면 종료
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# 카메라와 창 정리
cap.release()
cv2.destroyAllWindows()