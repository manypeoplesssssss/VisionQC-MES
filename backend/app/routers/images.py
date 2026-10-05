"""
검사 이미지 제공 API (routers/images.py)   [기능 F13 · 담당 D]

GET /api/images/{상대경로}?exp=...&sig=...

서명된 주소로만 검사 이미지를 내려준다 (주소는 검사 조회 API 응답의 image_url).
<img> 태그는 로그인 토큰 헤더를 못 보내기 때문에, 로그인 확인 대신 '서명'으로 확인한다.
서명은 서버 비밀키로만 만들 수 있으므로, 로그인해서 API 응답을 받은 사람만 주소를 알 수 있다.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..storage import resolve_image, verify_signature

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{rel_path:path}")  # :path → '2026-10-05/파일명.png' 처럼 / 가 들어간 경로를 통째로 받음
def get_image(rel_path: str, exp: int, sig: str):
    if not verify_signature(rel_path, exp, sig):
        raise HTTPException(403, "이미지 주소가 만료되었거나 올바르지 않습니다")
    path = resolve_image(rel_path)  # ../ 같은 경로 조작 차단
    if not path.is_file():
        raise HTTPException(404, "이미지 파일이 없습니다")
    # 주소 자체가 만료시각을 품고 있으므로 브라우저 캐시 허용
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
