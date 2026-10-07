"""Shared pixel-exact crop. No resize, padding or polygon masking here."""
import config


def validate_frame(frame):
    expected = (config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3)
    if frame.shape != expected:
        raise ValueError(f"카메라 frame shape={frame.shape}; 필요한 shape={expected}. "
                         "카메라/가상 카메라 출력 해상도를 확인하세요 (자동 확대하지 않음).")


def roi_bounds():
    x, y = config.ROI_X, config.ROI_Y
    w, h = config.ROI_WIDTH, config.ROI_HEIGHT
    if type(x) is not int or type(y) is not int:
        raise ValueError("config.py의 ROI_X, ROI_Y에 학습 당시 ROI 시작 좌표를 입력하세요.")
    if (w, h) != (600, 320):
        raise ValueError("학습 ROI 크기는 가로 600 × 세로 320이어야 합니다.")
    if x < 0 or y < 0 or x + w > config.CAMERA_WIDTH or y + h > config.CAMERA_HEIGHT:
        raise ValueError(f"ROI {(x, y, w, h)}가 원본 영상 범위를 벗어납니다.")
    return x, y, w, h


def crop_roi(frame):
    validate_frame(frame)
    x, y, w, h = roi_bounds()
    return frame[y:y + h, x:x + w].copy()


def input_description(frame):
    roi = crop_roi(frame)
    return (f"frame shape={frame.shape}; ROI(x,y,w,h)={roi_bounds()}; "
            f"ROI shape={roi.shape}; PatchCore input=(1, 3, 320, 600); "
            f"YOLO source shape={roi.shape}, imgsz={config.YOLO_IMGSZ}, "
            "rect=False (letterbox; 강제 정사각형 resize 없음)")
