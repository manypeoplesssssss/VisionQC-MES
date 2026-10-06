# station_3d — 3D 스캔 치수 검사 프로그램 (자리)

3D 모델링 코드를 이 폴더에 넣습니다. 3D 환경 전용 가상환경을 이 폴더에 따로 만듭니다.

MES 로 보내는 부분은 `../common/mes_client.py` 를 씁니다.

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from mes_client import MESClient

mes = MESClient("http://<MES서버IP>:8000", api_key="<INGEST_API_KEY>")
iid = "20261006_inspection_143000_001"              # 날짜 포함 검사번호
mes.start(iid, "redcar", product_serial="RC-0001")   # 검사 시작
mes.send_dimension(iid, width, length, height,       # 실측 (mm). 합불은 MES 가 ±3mm 로 자동 판정
                   scan_file_path="scans/....ply")
```

이후 할 일
- 3D 측정 코드 넣기
- 측정이 끝나면 `../handoff/` 에 검사번호를 기록해서, 환경을 바꾼 뒤 `station_vision` 이 같은 검사에 이어 붙이게 하기
- `requirements.txt` (3D 환경 패키지 + requests)
