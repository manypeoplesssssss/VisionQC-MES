"""S: 검사 시작, X: 수동 정지, E: 검사 영역 변경, Q: 정지 후 종료.
결함 검출 -> X/DONE -> 새 프레임 저장 -> S 자동 재회전.

키보드로 조작하는 실시간 턴테이블 + YOLO 검사 프로그램.
버튼 화면으로 조작하려면 inspection_app.py 를 쓴다 (이 파일의 함수를 그대로 가져다 쓴다).

검사 흐름
    S 입력 → 0도 기준 설정 → 저속 연속 회전
      → 매 프레임 검사 영역 안에서 YOLO 검출
      → 신뢰도 0.80 이상 결함 발견 (직전 촬영 위치에서 8도 이상 이동한 경우만)
      → X 로 정지, Arduino 1초 안정화 DONE 대기
      → 새 프레임으로 다시 검출 → 여전히 0.80 이상이면 사진·정보 저장
      → 자동 재회전 → 360도가 되면 정지하고 PASS/FAIL 출력
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.engine.results import Results
import config
from turntable import Turntable

# ---------------------------------------------------------------- 설정값
ROOT = Path(__file__).resolve().parent          # 이 파일이 있는 폴더 (best.pt, captures 기준 위치)
DEFECT_CLASSES = {"scratch", "white_paint"}     # 결함으로 취급할 YOLO 클래스 이름
ROI_FILE = ROOT / "inspection_roi.json"         # 마우스로 지정한 검사 영역 저장 파일
WINDOW = "VisionQC"                             # 검사 화면 창 이름
ROI_NORMALIZED = []                             # 현재 검사 영역 꼭짓점 (0~1 비율 좌표). 실행 중에 채워진다
CAPTURE_INTERVAL_DEG = 8.0  # 직전 촬영 위치에서 이 각도 이상 이동하면 재촬영 허용
CAPTURE_CONFIDENCE = 0.80   # 이 신뢰도 이상인 결함만 정지·촬영을 일으킨다 (낮은 건 화면 표시만)


def imwrite(path, picture):
    """사진 저장. cv2.imwrite 는 Windows 에서 경로에 한글(예: 사용자 폴더 이름)이 있으면
    실패하므로, OpenCV 로 jpg 인코딩만 하고 파일 쓰기는 numpy 로 한다. 성공하면 True"""
    ok, data = cv2.imencode(Path(path).suffix or ".jpg", picture)
    if ok:
        data.tofile(str(path))
    return ok


def capture_allowed(angle, last_capture_angle):
    """같은 결함을 반복해서 찍지 않도록, 직전 촬영 각도에서 충분히 돌았을 때만 촬영 허용"""
    return last_capture_angle is None or angle - last_capture_angle >= CAPTURE_INTERVAL_DEG


def validate_roi(points):
    """검사 영역 꼭짓점 목록이 올바른 다각형인지 확인하고 리스트로 돌려준다.
    점 3개 이상, 0~1 범위, 중복 점 없음, 변끼리 교차 없음, 너무 작지 않음. 문제가 있으면 ValueError"""
    polygon = np.asarray(points, dtype=np.float32)
    if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3:
        raise ValueError("검사 영역은 점 3개 이상 필요합니다")
    if not np.isfinite(polygon).all() or (polygon < 0).any() or (polygon > 1).any():
        raise ValueError("검사 영역 좌표가 잘못되었습니다")
    if len(np.unique(polygon, axis=0)) != len(polygon):
        raise ValueError("같은 위치를 중복해서 선택했습니다")
    def cross(a, b, c):
        # 벡터 ab 와 ac 의 외적 (부호로 c 가 선분 ab 의 어느 쪽에 있는지 판단)
        return float((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]))
    def on_segment(a, b, p):
        # p 가 선분 ab 를 감싸는 사각형 안에 있는지 (일직선 위에 있을 때 접촉 판정용)
        return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and
                min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))
    # 이웃하지 않는 두 변이 교차하거나 맞닿으면 꼬인 다각형이므로 거부
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # 꼭짓점을 공유하는 이웃 변은 검사하지 않음
            c, d = polygon[j], polygon[(j + 1) % n]
            ab_c, ab_d = cross(a, b, c), cross(a, b, d)
            cd_a, cd_b = cross(c, d, a), cross(c, d, b)
            intersects = (ab_c * ab_d < 0 and cd_a * cd_b < 0)
            touches = ((abs(ab_c) < 1e-8 and on_segment(a, b, c)) or
                       (abs(ab_d) < 1e-8 and on_segment(a, b, d)) or
                       (abs(cd_a) < 1e-8 and on_segment(c, d, a)) or
                       (abs(cd_b) < 1e-8 and on_segment(c, d, b)))
            if intersects or touches:
                raise ValueError("경계가 겹칩니다. 가장자리를 순서대로 선택하세요")
    if abs(cv2.contourArea(polygon)) < 0.001:
        raise ValueError("검사 영역이 너무 작습니다")
    return polygon.tolist()


def load_roi(frame):
    """저장된 검사 영역을 불러온다. 파일이 없거나, 망가졌거나, 영상 비율이 바뀌었으면 [] (다시 지정 필요)"""
    if not ROI_FILE.exists():
        return []
    try:
        saved = json.loads(ROI_FILE.read_text(encoding="utf-8"))
        points = validate_roi(saved["points"])
        height, width = frame.shape[:2]
        if abs(saved["aspect_ratio"] - width / height) > 0.02:
            print("영상 비율이 바뀌었습니다. 검사 영역을 다시 지정하세요.")
            return []
        return points
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"검사 영역 설정을 불러오지 못했습니다: {exc}")
        return []


def save_roi(points, frame):
    """검사 영역을 영상 비율과 함께 저장. 임시 파일에 쓴 뒤 교체해서 저장 중 꺼져도 파일이 망가지지 않게 한다"""
    height, width = frame.shape[:2]
    payload = {"version": 1, "points": validate_roi(points),
               "aspect_ratio": width / height}
    temporary = ROI_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(ROI_FILE)


def select_roi(frame):
    """정지 상태의 영상을 사용. 취소하면 기존 설정을 유지한다.
    별도 창에서 마우스로 꼭짓점을 찍어 검사 영역을 지정한다. 저장하면 꼭짓점 목록, 취소하면 None"""
    height, width = frame.shape[:2]
    # 큰 영상은 화면에 들어가도록 줄여서 보여 준다 (좌표는 0~1 비율로 저장하므로 크기와 무관)
    scale = min(1.0, 1100 / width, 750 / height)
    preview = cv2.resize(frame, (round(width * scale), round(height * scale)))
    ph, pw = preview.shape[:2]
    points = []
    message = "Click around the target | Right click: undo | Enter: save | Esc: cancel"
    def mouse(event, x, y, flags, param):
        # 왼쪽 클릭: 점 추가 / 오른쪽 클릭: 마지막 점 취소
        if event == cv2.EVENT_LBUTTONDOWN and 0 <= x < pw and 0 <= y < ph:
            points.append((x / (pw - 1), y / (ph - 1)))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
    cv2.namedWindow("Set inspection area", cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback("Set inspection area", mouse)
    print("검사 영역 가장자리를 순서대로 클릭하세요. Enter: 저장 / 우클릭: 되돌리기 / C: 초기화 / Esc: 취소")
    try:
        while True:
            # 지금까지 찍은 점과 다각형을 미리보기 위에 그린다
            picture = preview.copy()
            if points:
                vertices = np.array([(round(x * (pw-1)), round(y * (ph-1)))
                                     for x, y in points], dtype=np.int32)
                if len(points) >= 3:
                    overlay = picture.copy()
                    cv2.fillPoly(overlay, [vertices], (80, 210, 150))
                    picture = cv2.addWeighted(overlay, 0.2, picture, 0.8, 0)
                cv2.polylines(picture, [vertices], len(points) >= 3, (80, 210, 150), 2)
                for vertex in vertices:
                    cv2.circle(picture, tuple(vertex), 4, (80, 210, 150), -1)
            cv2.rectangle(picture, (0, 0), (pw, 34), (25, 25, 25), -1)
            cv2.putText(picture, message, (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        min(0.5, pw / 1500), (240, 240, 240), 1, cv2.LINE_AA)
            cv2.imshow("Set inspection area", picture)
            key = cv2.waitKey(20) & 0xFF
            # Esc 또는 창 닫기 → 취소
            if key == 27 or cv2.getWindowProperty("Set inspection area", cv2.WND_PROP_VISIBLE) < 1:
                return None
            if key == ord("c"):
                points.clear()
            # Enter → 검증 후 저장
            if key in (10, 13):
                try:
                    selected = validate_roi(points)
                    save_roi(selected, frame)
                    print("검사 영역을 저장했습니다.")
                    return selected
                except (ValueError, OSError) as exc:
                    print(exc)
                    message = "Invalid area or save failed. C: clear | Esc: cancel"
    finally:
        cv2.destroyWindow("Set inspection area")


def roi_polygon(frame):
    """0~1 비율 검사 영역을 이 프레임의 픽셀 좌표 다각형으로 바꾼다"""
    height, width = frame.shape[:2]
    return np.array([(round(x * (width - 1)), round(y * (height - 1)))
                     for x, y in ROI_NORMALIZED], dtype=np.int32)


def inspect_roi(model, frame):
    """검사 영역 안만 YOLO 로 검사한다.
    영역을 감싸는 사각형만 잘라 영역 밖은 검게 가리고 검출한 뒤, 좌표를 원래 프레임 기준으로 되돌린다"""
    polygon = roi_polygon(frame)
    x, y, width, height = cv2.boundingRect(polygon)
    crop = frame[y:y + height, x:x + width].copy()
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon - np.array([x, y])], 255)
    crop = cv2.bitwise_and(crop, crop, mask=mask)
    # conf=0.25: 화면 표시용으로 낮은 신뢰도까지 받는다 (촬영 기준은 CAPTURE_CONFIDENCE)
    predicted = model.predict(source=crop, conf=0.25, device="cpu", verbose=False)[0]
    boxes = predicted.boxes.data.clone()
    # 잘라낸 이미지 기준 좌표 → 원본 프레임 좌표
    boxes[:, [0, 2]] += x
    boxes[:, [1, 3]] += y
    # 검출 상자의 중심이 경계 밖에 있으면 판정에서 제외한다.
    keep = []
    for box in boxes:
        cx = float((box[0] + box[2]) / 2)
        cy = float((box[1] + box[3]) / 2)
        keep.append(cv2.pointPolygonTest(polygon, (cx, cy), False) >= 0)
    indices = [i for i, valid in enumerate(keep) if valid]
    # 원본 프레임 기준의 새 Results 로 만들어 plot() 등을 그대로 쓸 수 있게 한다
    return Results(orig_img=frame, path=predicted.path,
                   names=predicted.names, boxes=boxes[indices])


def annotated_frame(result):
    """검출 상자 + 검사 영역 경계선을 그린 화면용 이미지"""
    picture = result.plot()
    cv2.polylines(picture, [roi_polygon(picture)], True, (80, 210, 150), 1)
    return picture


class LatestCamera:
    """정지 대기 중에도 영상을 계속 받아 오래된 프레임을 버린다.
    별도 스레드가 카메라를 계속 읽어 가장 최신 프레임 1장만 들고 있는다.
    (카메라 버퍼에 쌓인 옛 프레임으로 검사하는 것을 막기 위함)"""
    def __init__(self):
        # 1번 카메라 (OBS Virtual Camera / DroidCam 등). DirectShow 로 연다
        self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError("카메라 연결 실패")
        self.lock = threading.Lock()
        self.frame = None        # 가장 최근 프레임
        self.timestamp = 0.0     # 그 프레임을 받은 시각 (time.monotonic)
        self.failed = False
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        """백그라운드 스레드: 계속 읽어서 최신 프레임만 덮어쓴다"""
        while not self.closed.is_set():
            ok, frame = self.cap.read()
            with self.lock:
                if not ok:
                    self.failed = True
                    return
                self.frame = frame
                self.timestamp = time.monotonic()

    def fresh(self, after=0.0, timeout=3.0):
        """after 시각 이후에 들어온 새 프레임을 기다려 (프레임 사본, 받은 시각)을 돌려준다"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.failed:
                    raise RuntimeError("카메라 프레임 읽기 실패")
                if self.frame is not None and self.timestamp > after:
                    return self.frame.copy(), self.timestamp
            time.sleep(0.005)
        raise RuntimeError("새 카메라 프레임 대기 시간 초과")

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2.0)
        self.cap.release()


def defects(result):
    """검출 결과 중 결함 클래스만 [{"class", "confidence", "xyxy"}] 로 뽑는다 (신뢰도 무관)"""
    found = []
    for box in result.boxes:
        name = result.names[int(box.cls.item())]
        if name in DEFECT_CLASSES:
            found.append({"class": name, "confidence": float(box.conf.item()),
                          "xyxy": box.xyxy[0].tolist()})
    return found


def capture_defects(result):
    """촬영 기준(CAPTURE_CONFIDENCE) 이상인 결함만"""
    return [item for item in defects(result)
            if item["confidence"] >= CAPTURE_CONFIDENCE]


def new_inspection_folder():
    """검사 1회(한 바퀴)용 폴더 생성: captures/날짜/inspection_시분초_순번"""
    now = datetime.now()
    parent = ROOT / "captures" / now.strftime("%Y%m%d")
    parent.mkdir(parents=True, exist_ok=True)
    base = "inspection_" + now.strftime("%H%M%S")
    sequence = 1
    # 같은 초에 두 번 시작해도 겹치지 않게 순번을 올린다
    while True:
        folder = parent / f"{base}_{sequence:03d}"
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            sequence += 1


def save_capture(frame, result, angle, folder, number):
    """결함 사진 1장 저장: 원본(.jpg), 검출 표시(_annotated.jpg), 검출 정보(.json)를 같은 번호로"""
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{folder.name}_{number:03d}"
    for suffix, picture in (("", frame), ("_annotated", annotated_frame(result))):
        if not imwrite(folder / (stem + suffix + ".jpg"), picture):
            raise RuntimeError("이미지 저장 실패: 재회전을 중단합니다")
    metadata = {"time": datetime.now().isoformat(), "angle_deg": angle,
                "inspection_id": folder.name, "capture_number": number,
                "defects": defects(result), "roi_normalized": ROI_NORMALIZED}
    (folder / (stem + ".json")).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"촬영 저장 완료: {folder / (stem + '.jpg')}")


def main():
    global ROI_NORMALIZED
    # 학습한 YOLO 모델 불러오기 + 결함 클래스가 들어 있는지 확인
    model = YOLO(str(ROOT / "best.pt"))
    names = set(model.names.values())
    if not DEFECT_CLASSES.intersection(names):
        raise RuntimeError(f"모델에 결함 클래스가 없습니다: {names}")
    camera = None
    table = None
    running = False              # 지금 연속 회전하며 검사 중인지
    last_capture_angle = None    # 마지막으로 촬영(시도)한 각도
    angle = 0.0                  # 턴테이블 현재 각도 (0.5초마다 갱신)
    captures = 0                 # 이번 바퀴에서 저장한 결함 사진 수
    inspection_folder = None     # 이번 바퀴의 저장 폴더
    last_frame = 0.0             # 마지막으로 처리한 프레임 시각
    last_poll = 0.0              # 마지막으로 각도를 물어본 시각
    try:
        camera = LatestCamera()
        table = Turntable(port=config.SERIAL_PORT)
        # 연결 시 이미 회전 중인 보드도 정지 상태로 맞춘다.
        table.stop()
        frame, last_frame = camera.fresh()
        # 저장된 검사 영역이 없으면 처음에 지정받는다
        ROI_NORMALIZED = load_roi(frame)
        if not ROI_NORMALIZED:
            ROI_NORMALIZED = select_roi(frame) or []
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        print("연결 완료. S: 검사 시작 / X: 정지 / E: 영역 변경 / Q: 종료")
        while True:
            # ---- 매 프레임: 검출하고 화면에 표시
            frame, last_frame = camera.fresh(after=last_frame)
            result = inspect_roi(model, frame) if ROI_NORMALIZED else None
            found = capture_defects(result) if result is not None else []
            picture = annotated_frame(result) if result is not None else frame.copy()
            status = "INSPECTING" if running else "READY" if ROI_NORMALIZED else "SET AREA: E"
            cv2.rectangle(picture, (0, 0), (picture.shape[1], 30), (25, 25, 25), -1)
            cv2.putText(picture, f"{status}   S: start   X: stop   E: area   Q: quit", (8, 21),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.imshow(WINDOW, picture)

            # ---- 키 입력 처리
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("e"):
                # 정지한 뒤 새 프레임으로 검사 영역 다시 지정
                table.stop()
                running = False
                edit_frame, last_frame = camera.fresh(after=time.monotonic())
                selected = select_roi(edit_frame)
                if selected is not None:
                    ROI_NORMALIZED = selected
                continue
            if key == ord("x"):
                table.stop()
                running = False
                print("검사 수동 정지")
                continue
            if key == ord("s") and not running:
                if not ROI_NORMALIZED:
                    print("E를 눌러 검사 영역을 먼저 지정하세요.")
                    continue
                # 새 바퀴 시작: 현재 위치를 0도로, 새 폴더, 카운터 초기화 후 회전
                table.zero()
                inspection_folder = new_inspection_folder()
                captures = 0
                last_capture_angle = None
                angle = 0.0
                table.start()
                running = True
                last_poll = 0.0
                # 시작 전 정지 영상으로 검출하지 않도록 다음 프레임부터 검사.
                last_frame = time.monotonic()
                print(f"한 바퀴 검사 시작: {inspection_folder.name}")
                continue
            if not running:
                continue

            # ---- 회전 중: 0.5초마다 각도 확인, 한 바퀴(360도)가 되면 종료
            if time.monotonic() - last_poll >= 0.5:
                angle = table.reported_angle()
                last_poll = time.monotonic()
                if angle >= 360.0:
                    table.stop()
                    running = False
                    print(f"한 바퀴 검사 완료: {'FAIL' if captures else 'PASS'} / 촬영 {captures}회")
                    continue

            # ---- 결함 발견 → 정지 → 새 프레임으로 재검출 → 저장 → 재회전
            if found and capture_allowed(angle, last_capture_angle):
                table.stop()  # Arduino의 1초 안정화 DONE까지 대기.
                running = False
                # DONE 이후 0.2초간 계속 수신한 뒤 새 프레임 사용.
                # 카메라 자체 지연이 큰 경우 이 대기를 늘려야 한다.
                fresh_after = time.monotonic() + 0.2
                stopped_frame, last_frame = camera.fresh(after=fresh_after)
                stopped_result = inspect_roi(model, stopped_frame)
                if capture_defects(stopped_result):
                    save_capture(stopped_frame, stopped_result, table.position_deg,
                                 inspection_folder, captures + 1)
                    captures += 1
                else:
                    print("정지 후 신뢰도 0.80 이상 결함 없음: 저장 없이 검사 계속")
                last_capture_angle = table.position_deg
                angle = table.position_deg
                last_poll = 0.0
                if table.position_deg >= 360.0:
                    print(f"한 바퀴 검사 완료: {'FAIL' if captures else 'PASS'} / 촬영 {captures}회")
                else:
                    table.start()
                    running = True
                    last_frame = time.monotonic()
                    print("자동 재회전")
    finally:
        # 어떤 이유로 끝나든 턴테이블을 멈추고 장비를 닫는다
        if table is not None:
            try:
                table.stop()
            except Exception as exc:
                print(f"정지 응답 확인 실패: {exc}. 턴테이블 상태를 확인하세요.")
            finally:
                table.close()
        if camera is not None:
            camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
