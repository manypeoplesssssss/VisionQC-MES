r"""
camera_check.py — 연결된 카메라를 확인하고 YOLO 검사 카메라 번호를 찾는 프로그램

    .venv\Scripts\python.exe camera_check.py

1) RealSense(인텔) 카메라 목록: 이름, 시리얼, USB 속도 (3D 검사용, station_3d/config.py 의 CAM_A_SERIAL / CAM_B_SERIAL 과 비교)
2) 일반 카메라 번호(0~7)별 미리보기 창: 어떤 번호가 어떤 영상인지 눈으로 확인
   → YOLO 검사에 쓸 영상의 번호를 config.py 의 CAMERA_INDEX 에 적는다
   창에서 q 또는 Esc 로 종료. 카메라 앱(OBS, DroidCam)은 먼저 켜 둔다.
   주의: RealSense 는 일반 카메라 번호에도 (색 영상 등) 잡힐 수 있다. 3D 스캔 중에는 이 프로그램을 끌 것.
"""
import cv2
import numpy as np

import config

MAX_INDEX = 8
TILE = (320, 240)


def realsense_list():
    try:
        import pyrealsense2 as rs
    except ImportError:
        print("pyrealsense2 가 설치되어 있지 않아 RealSense 목록은 건너뜁니다")
        return
    devices = list(rs.context().query_devices())
    print(f"[RealSense] {len(devices)}대")
    for d in devices:
        usb = d.get_info(rs.camera_info.usb_type_descriptor) if d.supports(rs.camera_info.usb_type_descriptor) else "?"
        warn = "" if str(usb).startswith("3") else "   ← USB 3.x 포트에 꽂으세요"
        print(f"  {d.get_info(rs.camera_info.name)}  시리얼 {d.get_info(rs.camera_info.serial_number)}  USB {usb}{warn}")


def open_cameras():
    found = {}
    for i in range(MAX_INDEX):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                found[i] = cap
                continue
        cap.release()
    return found


def main():
    realsense_list()
    print(f"\n현재 YOLO 검사 카메라 번호(config.CAMERA_INDEX): {getattr(config, 'CAMERA_INDEX', 1)}")
    cams = open_cameras()
    if not cams:
        print("열리는 일반 카메라가 없습니다. 카메라 앱(OBS/DroidCam)을 켜고 다시 실행하세요")
        return
    print("열린 카메라 번호:", ", ".join(map(str, cams)), "\n미리보기 창에서 번호별 영상을 확인하세요 (q / Esc 종료)")
    while True:
        tiles = []
        for i, cap in cams.items():
            ok, frame = cap.read()
            tile = cv2.resize(frame, TILE) if ok else np.zeros((TILE[1], TILE[0], 3), np.uint8)
            h, w = frame.shape[:2] if ok else (0, 0)
            cv2.putText(tile, f"#{i}  {w}x{h}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            tiles.append(tile)
        cols = min(3, len(tiles))
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
        cv2.imshow("camera_check (q: quit)", np.vstack(rows))
        if cv2.waitKey(30) & 0xFF in (ord("q"), 27):
            break
    for cap in cams.values():
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
