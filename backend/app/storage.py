"""
이미지 로컬 저장 + 파일명 규칙 + 서명된 이미지 주소 (storage.py)   [기능 F06 저장=B · F13 서명 주소=D]

파일명 : yyyy-mm-dd-품목-공정-시리얼.확장자
         예) 2026-10-05-Redcar-DIM3D-SN0001.jpg
         같은 제품을 같은 공정에서 재검사하면 뒤에 _r2, _r3 ... 이 붙음 (덮어쓰기 없음)
저장경로: STORAGE_DIR/yyyy-mm-dd/파일명
DB에는 image_filename(파일명)과 image_path(STORAGE_DIR 기준 상대경로)를 같이 기록

이미지 주소: /api/images/<상대경로>?exp=<만료시각>&sig=<서명>
         <img> 태그는 로그인 토큰을 헤더로 못 보내기 때문에, API 응답에 서명된 주소를 담아준다.
         만료시각을 1시간 단위로 맞춰서 대시보드가 30초마다 새로고침해도 주소가 그대로 → 브라우저 캐시 사용
"""
import hashlib
import hmac
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from .config import settings

# ===================== 저장 · 파일명 (F06 · 담당 B) =====================

# 받아주는 이미지 확장자
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
# 파일명에 쓸 수 없는 문자 (영문/숫자/_ 외 전부)
_SAFE = re.compile(r"[^A-Za-z0-9_]")


def build_filename(inspected_at: datetime, item: str, process: str,
                   serial_no: str, ext: str, retry: int = 1) -> str:
    """
    규칙대로 파일명을 만든다.
    retry=1 이면 그대로, 2 이상이면 _r2 처럼 재검사 표시를 붙인다.
    """
    serial = _SAFE.sub("_", serial_no)  # 파일명 구분자 '-' 와 섞이지 않게
    suffix = "" if retry == 1 else f"_r{retry}"
    return f"{inspected_at:%Y-%m-%d}-{item}-{process}-{serial}{suffix}{ext}"


def save_image(file: UploadFile, inspected_at: datetime, item: str,
               process: str, serial_no: str) -> tuple[str, str]:
    """이미지를 저장하고 (파일명, 상대경로) 를 돌려준다"""
    # 1) 확장자 확인
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"지원하지 않는 이미지 형식입니다: {ext or '확장자 없음'}")

    # 2) 크기 확인 - 최대 크기보다 1바이트만 더 읽어서, 넘으면 거절 (큰 파일을 메모리에 다 올리지 않게)
    max_bytes = settings.MAX_IMAGE_MB * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"이미지가 너무 큽니다 (최대 {settings.MAX_IMAGE_MB}MB)")
    if not data:
        raise HTTPException(400, "빈 이미지 파일입니다")

    # 3) 날짜 폴더 준비
    day = f"{inspected_at:%Y-%m-%d}"
    day_dir = settings.STORAGE_DIR / day
    day_dir.mkdir(parents=True, exist_ok=True)

    # 4) 파일 쓰기. 같은 이름이 이미 있으면 _r2, _r3 ... 로 바꿔가며 시도
    retry = 1
    while True:
        filename = build_filename(inspected_at, item, process, serial_no, ext, retry)
        try:
            with open(day_dir / filename, "xb") as f:  # 'x' : 이미 있으면 덮어쓰지 않고 실패
                f.write(data)
            break
        except FileExistsError:
            retry += 1

    return filename, f"{day}/{filename}"


def delete_image(rel_path: str) -> None:
    """이미지 파일 삭제 (없거나 경로가 이상하면 조용히 넘어감)"""
    try:
        resolve_image(rel_path).unlink(missing_ok=True)
    except HTTPException:
        pass


def resolve_image(rel_path: str) -> Path:
    """상대경로 → 실제 파일 경로. STORAGE_DIR 밖으로 나가는 경로(../ 등)는 거부"""
    root = settings.STORAGE_DIR.resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents:  # 실제 위치가 이미지 폴더 아래가 아니면 막음
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return target


# ===================== 서명된 이미지 주소 (F13 · 담당 D) =====================
def _sign(rel_path: str, exp: int) -> str:
    """경로 + 만료시각을 비밀키로 HMAC 서명 (키를 모르면 같은 서명을 만들 수 없음)"""
    msg = f"{rel_path}:{exp}".encode()
    return hmac.new(settings.JWT_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]


def image_url(rel_path: str) -> str:
    """API 응답에 넣어줄 이미지 주소를 만든다"""
    ttl = settings.IMAGE_URL_TTL_SECONDS
    # 만료시각을 ttl 단위로 올림 → 1시간 동안은 같은 주소가 나와서 브라우저 캐시가 먹힌다
    exp = (int(time.time()) // ttl + 2) * ttl  # 최소 ttl, 최대 2*ttl 동안 유효
    return f"/api/images/{quote(rel_path)}?exp={exp}&sig={_sign(rel_path, exp)}"


def verify_signature(rel_path: str, exp: int, sig: str) -> bool:
    """이미지 요청이 들어왔을 때 서명과 만료를 확인"""
    if exp < time.time():
        return False
    return hmac.compare_digest(_sign(rel_path, exp), sig)
