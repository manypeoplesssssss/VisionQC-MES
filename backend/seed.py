"""
초기 데이터 넣기 (seed.py) - backend 폴더에서 실행

  python seed.py            → 관리자 계정 3개 + 불량 종류 D01~D05
  python seed.py --demo     → + 최근 7일 더미 검사 데이터/사진 (화면 확인용)
  python seed.py --reset    → 모든 테이블과 storage 이미지를 지우고 다시 생성 (주의!)
  (옵션은 같이 쓸 수 있음: python seed.py --reset --demo)

계정: admin / admin1234 (최고관리자), manager / manager1234 (관리자), viewer / viewer1234 (조회 전용)

여러 번 실행해도 이미 있는 계정/불량 종류/더미데이터는 다시 만들지 않는다.
더미 검사는 실제 검사 PC 와 같은 흐름(3D 치수 → PatchCore → YOLO)을 따른다.
"""
import json
import random
import shutil
import sys
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import (AdminUser, DefectType, ProductDimensionInspection, ProductInspection, Role,
                        StageResult, YoloStatus)
from app.security import hash_password
from app.services.query import refresh_recommended
from app.storage import build_filename

# 공정 불량 5가지 (원인은 확정이 아닌 후보)
PAINT_CAUSES = ["페인트 공급 부족", "노즐 막힘", "분사 위치 오류"]
DEFECT_TYPES = [
    dict(defect_code="D01", defect_name="측면 도장 부족", defect_category="도장 부족", defect_location="측면",
         description="제품 측면의 도장이 부족함", cause_candidates=PAINT_CAUSES,
         recommended_action="페인트 공급 상태, 노즐, 측면 분사 위치 확인"),
    dict(defect_code="D02", defect_name="정면 도장 부족", defect_category="도장 부족", defect_location="정면",
         description="제품 정면의 도장이 부족함", cause_candidates=PAINT_CAUSES,
         recommended_action="페인트 공급 상태, 노즐, 정면 분사 위치 확인"),
    dict(defect_code="D03", defect_name="상단(천장) 도장 부족", defect_category="도장 부족", defect_location="상단",
         description="제품 상단(천장)의 도장이 부족함", cause_candidates=PAINT_CAUSES,
         recommended_action="페인트 공급 상태, 노즐, 상단 분사 위치 확인"),
    dict(defect_code="D04", defect_name="지그 조립 불완전으로 인한 스크래치", defect_category="스크래치",
         defect_location="지그 접촉부", description="지그 부품이 덜 조립되어 작동 중 제품과 접촉",
         cause_candidates=["지그 부품 조립 불완전"],
         recommended_action="지그 조립·고정 상태와 작동 중 제품 접촉 확인"),
    dict(defect_code="D05", defect_name="턴테이블 안착 중 발생한 스크래치", defect_category="스크래치",
         defect_location="하단·턴테이블 접촉부", description="턴테이블에 올리는 과정에서 접촉",
         cause_candidates=["안착 과정에서 발생한 접촉"],
         recommended_action="제품 안착 과정과 턴테이블 접촉 부위 확인"),
]
# YOLO 결함 종류 → 그럴듯한 불량 코드 (더미 데이터에서 일부만 지정)
CLASS_CODES = {"white_paint": ["D01", "D02", "D03"], "scratch": ["D04", "D05"]}


def ensure_base(db):
    """기본 계정 3개와 불량 종류 5개 (없을 때만 생성)"""
    for username, pw, name, role, email in [
        ("admin", "admin1234", "최고관리자", Role.SUPER_ADMIN, "admin@visionqc.local"),
        ("manager", "manager1234", "관리자", Role.ADMIN, "manager@visionqc.local"),
        ("viewer", "viewer1234", "조회자", Role.VIEWER, None),
    ]:
        if not db.query(AdminUser).filter_by(username=username).first():
            db.add(AdminUser(username=username, password_hash=hash_password(pw), name=name, role=role,
                             email=email, receive_defect_reports=role != Role.VIEWER))
            print(f"계정 생성: {username} / {pw}")
    for t in DEFECT_TYPES:
        if not db.get(DefectType, t["defect_code"]):
            db.add(DefectType(**t))
    db.commit()


def make_image(rel, label, boxes=()):
    """빨간 자동차 비슷한 더미 사진 (640x480). boxes 가 있으면 표시 사진처럼 상자를 그린다"""
    img = Image.new("RGB", (640, 480), (225, 228, 232))
    d = ImageDraw.Draw(img)
    d.ellipse([170, 330, 470, 400], fill=(240, 240, 240))              # 턴테이블
    d.rounded_rectangle([200, 220, 440, 330], radius=30, fill=(200, 40, 40))  # 차체
    d.ellipse([220, 310, 270, 360], fill=(40, 40, 40))                 # 바퀴
    d.ellipse([370, 310, 420, 360], fill=(40, 40, 40))
    for b in boxes:
        d.rectangle(b, outline=(30, 90, 230), width=3)
    d.text((12, 12), label, fill=(60, 60, 60))
    path = settings.STORAGE_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def save_named(ts, product, ident, ext, writer):
    """파일명 규칙대로 경로를 정하고 writer(상대경로)로 파일을 만든다"""
    retry = 1
    while True:
        rel = f"{ts:%Y-%m-%d}/" + build_filename(ts, product, "YOLO", ident, ext, retry)
        if not (settings.STORAGE_DIR / rel).exists():
            break
        retry += 1
    writer(rel)
    return rel


def add_inspection(db, ts, k, now):
    """검사 1회 생성. 공정 흐름: 치수(5% 불합격) → PatchCore(10% 불합격) → YOLO(불합격일 때만)"""
    product = "redcar"
    iid = f"{ts:%Y%m%d}_inspection_{ts:%H%M%S}_{k:03d}"
    insp = ProductInspection(inspection_id=iid, product_name=product, product_serial=f"RC-{ts:%y%m%d}-{k:04d}",
                             capture_folder=f"captures/{ts:%Y%m%d}/inspection_{ts:%H%M%S}_{k:03d}",
                             created_at=ts, yolo_defect_data=[], image_files=[])
    db.add(insp)
    stages_done = (now - ts).total_seconds()  # 오늘 막 들어온 검사는 단계 진행 중

    # 1) 3D 치수
    if stages_done < 20:
        return
    std = settings.PRODUCT_STANDARDS[product]
    bad = random.random() < 0.05
    vals = [round(s + random.gauss(0, 1.0) + (random.choice([-4, 4]) if bad and i == 0 else 0), 2)
            for i, s in enumerate(std)]
    insp.dimension = ProductDimensionInspection(
        width_mm=vals[0], length_mm=vals[1], height_mm=vals[2],
        standard_width_mm=std[0], standard_length_mm=std[1], standard_height_mm=std[2],
        scan_file_path=f"scans/{iid}.ply")
    db.flush()
    db.refresh(insp.dimension)
    dim = insp.dimension
    insp.dimension_result = dim.dimension_result
    insp.scan_file_path = dim.scan_file_path
    insp.dimension_data = {"tolerance_mm": 3.0, "width_mm": vals[0], "length_mm": vals[1], "height_mm": vals[2],
                           "standard_width_mm": std[0], "standard_length_mm": std[1], "standard_height_mm": std[2],
                           "width_result": dim.width_result, "length_result": dim.length_result,
                           "height_result": dim.height_result}
    if dim.dimension_result != StageResult.PASS.value:
        return  # 치수 불합격이면 검사 종료

    # 2) PatchCore
    if stages_done < 40:
        return
    score = round(random.uniform(0.62, 0.95) if random.random() < 0.10 else random.uniform(0.1, 0.55), 3)
    insp.patchcore_score, insp.patchcore_threshold, insp.patchcore_model_version = score, 0.6, "patchcore-demo-v1"
    insp.patchcore_result = StageResult.FAIL if score >= 0.6 else StageResult.PASS
    if insp.patchcore_result == StageResult.PASS:
        return

    # 3) YOLO: 결함 사진 1~3장, 사진마다 결함 1~2개
    insp.yolo_status = YoloStatus.IN_PROGRESS
    insp.yolo_model_version = "yolo-demo-v1"
    images, defects = [], []
    for n in range(1, random.randint(1, 3) + 1):
        t = ts + timedelta(seconds=40 + 8 * n)
        cls = random.choice(list(CLASS_CODES))
        found = []
        for _ in range(random.randint(1, 2)):
            x, y = random.randint(210, 380), random.randint(225, 290)
            found.append({"capture_number": n, "defect_class": cls,
                          "confidence": round(random.uniform(0.8, 0.98), 4),
                          "box": [x, y, x + random.randint(20, 50), y + random.randint(15, 35)],
                          "angle_deg": round(n * 95.0 + random.uniform(0, 30), 1),
                          "defect_code": random.choice(CLASS_CODES[cls]) if random.random() < 0.5 else None})
        ident = f"{iid}_c{n:03d}"
        label = f"{iid} #{n}"
        orig = save_named(t, product, ident, ".png", lambda rel: make_image(rel, label))
        ann = save_named(t, product, ident + "_annotated", ".png",
                         lambda rel: make_image(rel, label, [f["box"] for f in found]))
        meta = save_named(t, product, ident, ".json", lambda rel: (settings.STORAGE_DIR / rel).write_text(
            json.dumps({"inspection_id": iid, "capture_number": n, "defects": found}, ensure_ascii=False),
            encoding="utf-8"))
        images.append({"capture_number": n, "original_path": orig, "annotated_path": ann, "metadata_path": meta})
        defects += found
    insp.image_files, insp.yolo_defect_data = images, defects
    if stages_done >= 90:
        insp.yolo_status = YoloStatus.COMPLETED
    refresh_recommended(insp, db)


def demo(db, days=7, per_day=(30, 50)):
    """최근 days 일 동안 하루 30~50회 검사가 08~18시에 들어온 것처럼 생성"""
    # patchcore_model_version / 검사번호 규칙으로 더미 구분 → 이미 있으면 중복 생성 안 함
    if db.query(ProductInspection).filter(ProductInspection.capture_folder.like("captures/%")).first():
        print("더미 데이터가 이미 있습니다. 다시 만들려면 --reset 을 같이 쓰세요")
        return
    now = datetime.now().replace(microsecond=0)
    total = 0
    for back in range(days - 1, -1, -1):  # 오래된 날부터 오늘까지
        day = (now - timedelta(days=back)).replace(hour=8, minute=0, second=0)
        end = now if back == 0 else day.replace(hour=18)  # 오늘은 지금 시각까지만
        if end <= day:
            continue  # 오늘인데 아직 08시 전이면 건너뜀
        span = int((end - day).total_seconds())
        n = random.randint(*per_day) if back else max(5, int(per_day[1] * span / 36000))
        times = sorted(day + timedelta(seconds=random.randint(0, max(1, span - 1))) for _ in range(n))
        for k, ts in enumerate(times, 1):
            add_inspection(db, ts, k, now)
            total += 1
        db.commit()  # 하루치씩 저장
    print(f"더미 검사 {total}건 생성 완료 (최근 {days}일)")


def reset():
    """모든 테이블 삭제 + 이미지 폴더 비우기 (되돌릴 수 없음)"""
    Base.metadata.drop_all(bind=engine)
    if settings.STORAGE_DIR.exists():
        shutil.rmtree(settings.STORAGE_DIR)
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    print("DB 테이블과 이미지 폴더를 비웠습니다")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    Base.metadata.create_all(bind=engine)  # 테이블이 없으면 생성
    with SessionLocal() as db:
        ensure_base(db)
        if "--demo" in sys.argv:
            demo(db)
