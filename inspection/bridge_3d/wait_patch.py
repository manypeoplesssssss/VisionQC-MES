r"""
wait_patch.py — 3D 스캔의 "카메라 창에서 Space 를 누르세요" 대기를 검사 프로그램 버튼으로도 넘길 수 있게 하는 덮어쓰기

3D 코드(station_3d)는 수정하지 않는다. run_3d_script.py 가 실행 직전에 d435_common.preview_and_wait 를
이 파일의 함수로 바꿔 끼운다. 동작은 원래 함수와 같고(카메라 창 미리보기, Space 진행, Esc 중단),
환경변수 VISIONQC_3D_GO_FILE 이 있으면 그 파일이 생겼을 때도 진행한다 (검사 프로그램의 [배경 촬영]·[스캔 시작] 버튼).
대기 시작·진행을 알리려고 표준 출력에 `@@WAIT <종류>` / `@@GO` 줄을 찍는다 (검사 프로그램이 읽어서 버튼을 켜고 끔).
    종류: background (1) 배경 촬영) / scan (2) 물체 올리고 스캔 시작) — 그 밖의 대기(손으로 돌리기 등)는 Space 만 쓴다
"""
import os

import cv2


def install(dc, config):
    """dc: d435_common 모듈. dc.preview_and_wait 를 버튼도 받는 버전으로 바꾼다"""
    go_file = os.environ.get("VISIONQC_3D_GO_FILE")

    def preview_and_wait(cams, message="", show_checkerboard=False, extra_keys=""):
        names = [f"Camera {c.role} ({c.serial})" for c in cams]
        for n in names:
            cv2.namedWindow(n, cv2.WINDOW_NORMAL)
        if message:
            print(message, flush=True)
        kind = "background" if "1)" in message else "scan" if "2)" in message else None
        use_button = bool(go_file) and kind is not None
        if use_button:
            if os.path.exists(go_file):
                os.remove(go_file)  # 이전 신호가 남아 있으면 바로 넘어가 버리므로 지운다
            print(f"@@WAIT {kind}", flush=True)
        try:
            while True:
                for cam, name in zip(cams, names):
                    img = cam.color()
                    s = config.PREVIEW_WIDTH / img.shape[1]
                    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                    if show_checkerboard:
                        corners = dc.detect_checkerboard(small, fast=True)
                        ok = corners is not None
                        if ok:
                            cv2.drawChessboardCorners(small, config.CHECKERBOARD, corners, True)
                        cv2.putText(small, "FOUND" if ok else "not found", (15, 35),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0) if ok else (0, 0, 255), 2)
                    cv2.imshow(name, small)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    raise KeyboardInterrupt("사용자가 Esc를 눌러 중단했습니다.")
                if key == 32:
                    if use_button:
                        print("@@GO", flush=True)
                    return "space"
                if use_button and os.path.exists(go_file):
                    os.remove(go_file)
                    print("@@GO", flush=True)
                    return "space"
                if key != 255 and chr(key).lower() in extra_keys:
                    return chr(key).lower()
        finally:
            for n in names:
                cv2.destroyWindow(n)

    dc.preview_and_wait = preview_and_wait
