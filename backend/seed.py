"""
초기 데이터 넣기 (seed.py) - backend 폴더에서 실행   [기능 F02 · 담당 C]

  python seed.py            → 계정(admin, operator) + 품목 규격 3개
  python seed.py --demo     → + 최근 7일 더미 검사 데이터/이미지 (화면 확인용)
  python seed.py --reset    → 모든 테이블과 storage 이미지를 지우고 다시 생성 (주의!)
  (옵션은 같이 쓸 수 있음: python seed.py --reset --demo)

계정: admin / admin1234 (관리자), operator / oper1234 (작업자)

여러 번 실행해도 이미 있는 계정/규격/더미데이터는 다시 만들지 않는다.
"""
import random
import shutil
import sys
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import (PROCESS_ORDER, DefectResult, DimensionResult, Inspection, ItemSpec, Judge,
                        Process, Role, User)
from app.schemas import DimensionIn
from app.security import hash_password
from app.services.judge import judge_dimension
from app.storage import build_filename

# 더미 품목과 이미지에 칠할 색 (R, G, B)
ITEMS = {"Redcar": (200, 50, 50), "Bluecar": (50, 80, 200), "Greencar": (40, 160, 70)}
# 품목별 치수 규격 (mm)
SPECS = {
    "Redcar": dict(width_nominal=40.0, width_tol=0.5, length_nominal=90.0, length_tol=0.5,
                   height_nominal=30.0, height_tol=0.5),
    "Bluecar": dict(width_nominal=42.0, width_tol=0.5, length_nominal=95.0, length_tol=0.6,
                    height_nominal=31.0, height_tol=0.5),
    "Greencar": dict(width_nominal=38.0, width_tol=0.4, length_nominal=85.0, length_tol=0.5,
                     height_nominal=28.0, height_tol=0.4),
}
DEFECT_TYPES = ["scratch", "dent", "crack", "stain"]


def ensure_base(db):
    """기본 계정 2개와 규격 3개 (없을 때만 생성)"""
    for username, pw, name, role in [("admin", "admin1234", "관리자", Role.ADMIN),
                                     ("operator", "oper1234", "작업자", Role.OPERATOR)]:
        if not db.query(User).filter_by(username=username).first():
            db.add(User(username=username, password_hash=hash_password(pw), name=name, role=role))
            print(f"계정 생성: {username} / {pw}")
    for item, spec in SPECS.items():
        if not db.query(ItemSpec).filter_by(item=item).first():
            db.add(ItemSpec(item=item, **spec))
    db.commit()


def make_image(path, color, label):
    """자동차 모양 비슷한 더미 이미지 (640x480 PNG)"""
    img = Image.new("RGB", (640, 480), (225, 228, 232))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([140, 160, 500, 340], radius=30, fill=color)  # 차체
    d.ellipse([180, 310, 240, 370], fill=(40, 40, 40))                # 바퀴
    d.ellipse([400, 310, 460, 370], fill=(40, 40, 40))
    d.text((12, 12), label, fill=(60, 60, 60))                        # 왼쪽 위 글씨 (시리얼 공정)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def add_inspection(db, serial, item, proc, ts, specs):
    """검사 1건 생성 (이미지 파일 + DB 행). 실제 업로드 API 와 같은 판정 함수를 쓴다"""
    dim, defects = None, []
    if proc == Process.DIM3D:
        # 기준값 근처로 정규분포 난수 → 가끔 공차를 벗어나 NG 가 나온다
        s = specs[item]
        vals = {f"{a}_mm": round(random.gauss(s[f"{a}_nominal"], s[f"{a}_tol"] * 0.45), 2)
                for a in ("width", "length", "height")}
        status = judge_dimension(DimensionIn(**vals), db.query(ItemSpec).filter_by(item=item).first())
        dim = DimensionResult(**vals, status=status, reported_status=status)
        result = status
    else:
        # PatchCore 6%, YOLO 5% 확률로 결함 1~2개
        rate = 0.06 if proc == Process.PATCHCORE else 0.05
        if random.random() < rate:
            for _ in range(random.choice([1, 1, 2])):
                x, y = random.randint(150, 420), random.randint(170, 280)
                box = [x, y, x + random.randint(30, 70), y + random.randint(25, 50)]
                defects.append(DefectResult(defect_detected=True, type=random.choice(DEFECT_TYPES),
                                            confidence=round(random.uniform(0.55, 0.99), 3), box=box))
            result = Judge.NG
        else:
            defects.append(DefectResult(defect_detected=False))
            result = Judge.OK

    # 파일명 규칙은 실제 저장과 동일 (같은 이름이 있으면 _r2 ...)
    retry = 1
    while True:
        fname = build_filename(ts, item, proc.value, serial, ".png", retry)
        rel = f"{ts:%Y-%m-%d}/{fname}"
        if not (settings.STORAGE_DIR / rel).exists():
            break
        retry += 1
    make_image(settings.STORAGE_DIR / rel, ITEMS[item], f"{serial} {proc.value}")
    db.add(Inspection(serial_no=serial, item=item, process=proc, inspected_at=ts, result=result,
                      model_version="demo-v1", image_filename=fname, image_path=rel,
                      dimension=dim, defects=defects))
    return result


def demo(db, days=7, per_day=(40, 70)):
    """최근 days 일 동안 하루 40~70개 제품이 08~18시에 라인을 지나간 것처럼 생성"""
    # model_version='demo-v1' 로 더미 데이터를 구분 → 이미 있으면 중복 생성 안 함
    if db.query(Inspection).filter(Inspection.model_version == "demo-v1").first():
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
        for k in range(1, n + 1):
            serial = f"SN{day:%y%m%d}{k:04d}"   # 예) SN2610050001
            item = random.choice(list(ITEMS))
            ts = day + timedelta(seconds=random.randint(0, max(1, span - 120)))
            # 공정 순서대로 40초 간격
            for i, proc in enumerate(PROCESS_ORDER):
                if back == 0 and ts + timedelta(seconds=40 * i) > now:
                    break  # 오늘 막 들어온 제품은 공정 진행 중
                t = ts + timedelta(seconds=40 * i)
                res = add_inspection(db, serial, item, proc, t, SPECS)
                if res == Judge.NG and random.random() < 0.3:   # 일부는 재검사
                    t = t + timedelta(seconds=20)
                    res = add_inspection(db, serial, item, proc, t, SPECS)
                if res == Judge.NG:
                    break  # 불량이면 다음 공정으로 안 넘어감
            total += 1
        db.commit()  # 하루치씩 저장
    print(f"더미 제품 {total}개 생성 완료 (최근 {days}일)")


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
