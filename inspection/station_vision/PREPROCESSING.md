# 검사 입력 조건

`config.py`의 `ROI_X`, `ROI_Y`에 **학습 데이터 수집 때 사용한 왼쪽 위 원본 픽셀 좌표**를
입력한 뒤 프로그램을 재시작한다. 좌표를 모르면 임의로 중앙이나 기존 다각형 좌표를 사용하지 않는다.
좌표가 없거나 프레임 범위를 벗어나면 검사를 시작하지 않는다.

- 카메라: 1920×1080을 요청하고 실제 프레임 shape `(1080, 1920, 3)`을 처음과 매 프레임 확인.
- 공통 ROI: `[y:y+320, x:x+600]`. resize, 마스킹, padding 없이 복사.
- PatchCore: BGR → RGB → CHW/255. 체크포인트의 학습 전처리·정규화는 유지.
  모델 입력 크기가 `(320, 600)`인지 검사하고 실제 특징 추출 직전 tensor도 `(1, 3, 320, 600)`인지 확인.
- YOLO: 같은 ROI를 `model.predict(source=roi, imgsz=608, rect=False)`에 전달.
  Ultralytics 내부 letterbox가 비율을 유지해 약 608×324로 확대하고 608×608까지 padding.
  직접 정사각형 resize하거나 letterbox를 중복 적용하지 않음.
- `predict_roi()` 반환 박스는 600×320 ROI 좌표 그대로. `inspect_roi()`는 기존 원본 표시·DB 저장에 맞춰
  x/y 오프셋만 한 번 더한 Results를 반환. 기존 저장 JSON의 박스는 원본 프레임 좌표.
- PatchCore 검사 활성화 시 불합격 이후에만 YOLO 검사. 명시적인 YOLO 단독 모드는 유지.
- 기존 `inspection_roi.json`의 비율 다각형은 사용하지 않음. 화면의 ROI 버튼은 고정 좌표 확인용.
- 원본 사진, 점수·좌표·shape 메타데이터, 히트맵을 저장하며 PatchCore 입력 ROI도 `_roi.png`로 보관.
- `--sim`은 1920×1080 원본만 사용. 이전 640×480 사진을 자동 확대하지 않음.

실행 화면 기록에서 frame/ROI shape, PatchCore tensor와 전처리 후 shape, YOLO imgsz를 확인한다.
해상도 설정 성공 응답만으로 정상 취급하지 않는다. 카메라가 다른 크기를 반환하면 오류로 중단한다.

검증: 검사 환경에 pytest 설치 후 `python -m pytest inspection/station_vision/tests -q`.
기하/전처리 테스트는 합성 영상과 모의 모델 출력을 사용하며 실제 카메라·모델 성능 검증을 대체하지 않는다.
