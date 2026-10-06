# 다른 PC 에서 MySQL(DB) 접속하기

같은 Wi-Fi(같은 공유기)에 있는 다른 PC 에서 MES 의 MySQL DB 에 접속하는 방법입니다.
MES 서버·MySQL 이 설치된 PC 를 아래에서 **서버 PC** 라고 부릅니다.

## 1. 접속 정보

| 항목 | 값 |
|---|---|
| 호스트 | 서버 PC 의 Wi-Fi IP (`<서버 PC IP>`, 2장에서 확인) |
| 포트 | `3306` |
| 아이디 / 비밀번호 | `mes_user` / `mes_pass` (프로젝트 기본값) |
| DB 이름 | `visionqc` |

- DB 프로그램(DBeaver, MySQL Workbench 등): 위 값을 그대로 입력
- 파이썬 프로그램(검사 프로그램 등): `mysql+pymysql://mes_user:mes_pass@<서버 PC IP>:3306/visionqc?charset=utf8mb4`

> 서버 PC 자신은 `localhost` 로 접속합니다 (`backend\.env` 의 `DATABASE_URL`).

## 2. 서버 PC 의 IP 확인

서버 PC 에서 PowerShell 또는 cmd:
```powershell
ipconfig
```
`무선 LAN 어댑터 Wi-Fi` 아래 `IPv4 주소` 가 접속할 주소입니다. (예: `192.168.0.10` 처럼 생긴 주소)

공유기가 주소를 바꿀 수 있으니, 접속이 갑자기 안 되면 먼저 다시 확인하세요.
매번 바뀌는 게 불편하면 공유기 설정에서 서버 PC 에 고정 IP(DHCP 예약)를 주면 됩니다.

## 3. 서버 PC 에 필요한 설정 (처음 한 번)

2026-10-06 에 아래 항목이 모두 되어 있는 것을 확인했습니다. 다른 서버 PC 에 새로 설치할 때 참고하세요.

| 항목 | 확인 방법 | 필요한 상태 |
|---|---|---|
| MySQL 이 네트워크 접속을 받음 | `SELECT @@bind_address;` | `*` 또는 `0.0.0.0` (MySQL 8 기본값) |
| 다른 PC 용 계정 | `SELECT user, host FROM mysql.user;` | `mes_user` / `%` 가 있음 |
| 계정 권한 | `SHOW GRANTS FOR 'mes_user'@'%';` | `visionqc`.* 에 ALL PRIVILEGES |
| 방화벽 3306 허용 | `Get-NetFirewallRule -DisplayName "Port 3306"` | 허용(Allow) 규칙이 있음 (MySQL 설치 때 생성) |

계정이 없으면 서버 PC 에서 root 로 MySQL 에 접속해 만듭니다 (Workbench 가 없으면 명령줄):
```powershell
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p
```
`mysql>` 가 나오면:
```sql
CREATE USER IF NOT EXISTS 'mes_user'@'%' IDENTIFIED BY 'mes_pass';
CREATE USER IF NOT EXISTS 'mes_user'@'localhost' IDENTIFIED BY 'mes_pass';
GRANT ALL PRIVILEGES ON visionqc.* TO 'mes_user'@'%';
GRANT ALL PRIVILEGES ON visionqc.* TO 'mes_user'@'localhost';
FLUSH PRIVILEGES;
exit
```
- `'mes_user'@'%'` : 다른 PC 에서 접속하는 계정 / `'mes_user'@'localhost'` : 서버 PC 자신에서 접속하는 계정

방화벽 규칙이 없으면 **관리자 권한 PowerShell** 에서 한 번:
```powershell
New-NetFirewallRule -DisplayName "MySQL 3306" -Direction Inbound -Protocol TCP -LocalPort 3306 -Action Allow -Profile Any
```

## 4. 다른 PC 에서 확인

다른 PC 에서 PowerShell:
```powershell
Test-NetConnection <서버 PC IP> -Port 3306
```
`TcpTestSucceeded : True` 면 네트워크는 열려 있는 것입니다. 그다음 DB 프로그램으로 1장의 정보로 접속해 봅니다.

## 5. 검사 프로그램을 다른 PC 에서 돌릴 때

검사 프로그램은 결과를 DB 에 직접 저장하고, 사진은 MES 가 읽는 폴더로 복사합니다. 다른 PC 에서 돌리려면 두 가지를 바꿉니다.

1. **DB 주소**: 버튼 화면의 [DB 저장] → DB 주소 칸, 또는 `inspection\station_vision\config.py` 에
   ```python
   DB_URL = "mysql+pymysql://mes_user:mes_pass@<서버 PC IP>:3306/visionqc?charset=utf8mb4"
   ```
   3D 쪽은 `save_3d_to_db.py --db "mysql+pymysql://..."` 또는 환경변수 `VISIONQC_DB_URL`
2. **사진 폴더**: 서버 PC 의 `backend\storage\images` 폴더를 Windows 공유 폴더로 열고,
   버튼 화면의 [사진 폴더] 칸 또는 `config.py` 의 `STORAGE_DIR` 에 그 경로(예: `//서버PC이름/images`)를 넣습니다.
   사진 폴더를 안 바꾸면 DB 에는 저장되지만 MES 화면에서 사진이 안 보입니다.

## 6. MES 화면을 다른 PC 에서 열기 (참고)

DB 가 아니라 MES 웹 화면을 다른 PC 에서 보려면:
- 서버 PC 에서 화면 서버를 `--host` 로 켭니다: `cd frontend` → `npm run dev -- --host`
- 관리자 권한 PowerShell 에서 한 번:
  ```powershell
  New-NetFirewallRule -DisplayName "VisionQC MES 화면 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Any
  ```
- 다른 PC 브라우저에서 `http://<서버 PC IP>:5173` (MES 서버 8000 번은 열 필요 없음)

## 7. 주의

- **보안**: 같은 Wi-Fi 에 있는 누구나 `mes_user` / `mes_pass` 로 접속할 수 있습니다. 여럿이 쓰는 Wi-Fi 라면 비밀번호를 바꾸세요.
  ```sql
  ALTER USER 'mes_user'@'%' IDENTIFIED BY '새비밀번호';
  ALTER USER 'mes_user'@'localhost' IDENTIFIED BY '새비밀번호';
  ```
  바꾸면 서버 PC 의 `backend\.env` 의 `DATABASE_URL` 과 검사 PC 의 DB 주소도 같이 바꿔야 합니다.
- **네트워크 종류**: 서버 PC 의 Wi-Fi 가 "공용 네트워크" 면 접속이 막힐 수 있습니다.
  설정 → 네트워크 및 인터넷 → Wi-Fi → 연결된 Wi-Fi → **개인 네트워크** 로 바꾸세요.
- **서버 PC 가 켜져 있어야** 합니다. MySQL 은 Windows 서비스(`MySQL84`)로 자동 실행됩니다.

## 8. 안 될 때

| 증상 | 원인 | 해결 |
|---|---|---|
| `Test-NetConnection` 이 `False` | 방화벽 / 공용 네트워크 / IP 바뀜 / 다른 Wi-Fi | 3장 방화벽, 7장 네트워크 종류, 2장 IP 재확인 |
| `Access denied for user 'mes_user'@'192.168.…'` | `'mes_user'@'%'` 계정이 없거나 비밀번호 다름 | 3장 계정 만들기 다시 실행 |
| `Unknown database 'visionqc'` | DB 이름 틀림 | `visionqc` 로 정확히 입력 |
| `Host '…' is not allowed to connect` | `%` 계정 없이 `localhost` 계정만 있음 | 3장 `'mes_user'@'%'` 만들기 |
| 접속은 되는데 테이블이 없음 | MES 서버를 한 번도 안 켬 | 서버 PC 에서 MES 서버를 실행하면 테이블이 만들어짐 |
