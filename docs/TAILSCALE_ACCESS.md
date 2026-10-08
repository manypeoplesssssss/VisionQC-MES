# 다른 PC(작업자)에서 접속하기 — Tailscale

MES 서버·MySQL 이 켜진 PC(아래 **서버 PC**)에 다른 작업자의 PC 가 **Tailscale** 로 접속하는 방법입니다.
공유기 설정(포트포워딩)이 필요 없고 인터넷에 공개되지 않아서, 같은 Wi-Fi 가 아니어도 접속됩니다.
같은 Wi-Fi 안에서만 쓸 때는 [DB_REMOTE_ACCESS.md](DB_REMOTE_ACCESS.md) 의 방법도 됩니다.

| 이름 | 값 |
|---|---|
| 서버 PC 의 Tailscale 주소 | `<서버 PC 의 Tailscale IP>` (서버 PC 에서 `tailscale ip -4`, 100.x.x.x 모양) |
| 서버 PC 이름 | `<서버 PC 이름>` (Tailscale 앱에서 확인, 이름으로도 접속됨) |

## 1. 작업자 PC 준비 (처음 한 번)

1. https://tailscale.com/download 에서 Tailscale 을 설치하고 실행합니다.
2. **팀 Tailscale 네트워크에 들어가야** 합니다. 서버 PC 관리자가 보낸 초대(메일 또는 링크)로 가입합니다.
   (이미 같은 네트워크에 있으면 Tailscale 아이콘에 서버 PC 이름이 보입니다.)
3. 연결 확인 (PowerShell):
   ```powershell
   Test-NetConnection <서버 PC 의 Tailscale IP> -Port 5173
   Test-NetConnection <서버 PC 의 Tailscale IP> -Port 3306
   ```
   둘 다 `TcpTestSucceeded : True` 면 됩니다.

## 2. MES 화면 보기

브라우저에서 **`http://<서버 PC 의 Tailscale IP>:5173`** (또는 `http://<서버 PC 이름>:5173`)

| 계정 | 권한 |
|---|---|
| `viewer` / `viewer1234` | **조회 전용** — 작업자는 이 계정을 씁니다 |
| `manager` / `manager1234` | 관리자 (불량 코드 지정 등) |
| `admin` / `admin1234` | 최고관리자 — 서버 PC 관리자만 |

## 3. DB(MySQL) 직접 접속

| 항목 | 값 |
|---|---|
| 호스트 | `<서버 PC 의 Tailscale IP>` |
| 포트 / DB | `3306` / `visionqc` |
| 계정 | `mes_user` / `mes_pass` (**쓰기·삭제 가능한 전체 권한** — 아래 조회 전용 계정을 권장) |

DBeaver·Workbench 에 위 값을 입력하거나, 명령줄:
```powershell
mysql -h <서버 PC 의 Tailscale IP> -u mes_user -p visionqc
```

**조회 전용 계정 `viewer_user` 는 2026-10-08 에 만들어 두었습니다** (SELECT 만 가능, `admin_user` 테이블은 읽을 수 없음, 비밀번호는 서버 PC 관리자에게 받으세요).
새로 만들거나 다시 만들어야 할 때는 아래 방법을 씁니다.

### 조회 전용 계정 만들기 (서버 PC 관리자가 한 번만, MySQL root 필요)

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p
```
```sql
CREATE USER 'viewer_user'@'%' IDENTIFIED BY '새비밀번호';
GRANT SELECT ON visionqc.product_inspection TO 'viewer_user'@'%';
GRANT SELECT ON visionqc.product_dimension_inspection TO 'viewer_user'@'%';
GRANT SELECT ON visionqc.defect_type TO 'viewer_user'@'%';
GRANT SELECT ON visionqc.equipment_safety_alarm TO 'viewer_user'@'%';
FLUSH PRIVILEGES;
```
이후 작업자에게는 `viewer_user` 를 알려 주고 `mes_user` 는 서버 PC 와 검사 프로그램만 씁니다.
(`admin_user` 테이블에는 비밀번호 해시가 있어서 일부러 권한을 주지 않았습니다.)

## 4. 서버 PC 관리자가 지켜야 할 것

- 서버 PC 가 **켜져 있고, 잠자기 모드가 아니며**, Tailscale 이 실행 중이어야 합니다.
  (전원 연결 시 잠자기 끄기: 관리자 PowerShell 에서 `powercfg /change standby-timeout-ac 0`)
- MES 서버 터미널(8000)과 MES 화면 터미널(5173, `npm run dev -- --host`)이 열려 있어야 합니다. 켜는 법은 [RUN_AFTER_REBOOT.md](RUN_AFTER_REBOOT.md).
- 컴퓨터 **이름**으로 여는 주소(`http://<서버 PC 이름>:5173`)는 `frontend/vite.config.js` 의 `server.allowedHosts` 에
  그 이름이 있어야 합니다 (`.ts.net` 으로 끝나는 이름과 `node` 는 이미 들어 있음). 숫자 주소(100.x.x.x)는 항상 됩니다.
- 새 작업자 추가·접근 제한은 Tailscale 관리 화면(https://login.tailscale.com/admin)에서 합니다
  (Users → Invite users, 또는 Machines → 서버 PC → Share).

## 5. 안 될 때

| 증상 | 해결 |
|---|---|
| `Blocked request. This host ... is not allowed` | 주소의 이름을 `vite.config.js` 의 `allowedHosts` 에 추가하거나, 숫자 주소로 접속 |
| `TcpTestSucceeded : False` | 작업자 PC 의 Tailscale 이 켜져 있는지, 서버 PC 가 켜져 있는지, 서버 PC 방화벽에서 5173 / 3306 허용인지 |
| 서버 PC 이름이 Tailscale 앱에 안 보임 | 같은 Tailscale 네트워크에 초대되지 않은 것 → 4번의 관리 화면에서 초대·공유 |
| 로그인이 안 됨 / 요청 실패 (500) | 서버 PC 의 MES 서버(8000) 터미널이 켜져 있는지 |
| MySQL `Access denied` | 계정·비밀번호 확인 (`mes_user` 는 `%` 호스트 계정이 있어야 함, DB_REMOTE_ACCESS.md 3장) |

## 6. 주의

- 기본 비밀번호(`admin1234`, `mes_pass` 등)는 저장소에 공개돼 있습니다. Tailscale 네트워크 안에서만 접속되더라도, 여러 사람이 쓰면 **비밀번호를 바꾸세요**
  (MES: 화면의 [내 계정], MySQL: `ALTER USER 'mes_user'@'%' IDENTIFIED BY '새비밀번호';` 후 서버 PC 의 `backend\.env` 와 검사 프로그램 DB 주소도 같이 변경).
- 이 문서에는 서버 PC 의 실제 주소를 적지 않았습니다. 주소는 서버 PC 관리자에게 받으세요.
