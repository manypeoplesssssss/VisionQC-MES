"""
turntable.py — 아두이노 턴테이블(turntable/turntable.ino) 시리얼 제어

핸드셰이크: PC가 명령(R10 등)을 보내면 아두이노가 회전 + 잔진동 대기를 마친 뒤
"DONE"을 돌려준다. rotate()는 DONE이 올 때까지 기다렸다가 반환하므로, 그 다음
줄에서 바로 촬영하면 된다.

주의
    - 28BYJ-48 기어 백래시 때문에 항상 한 방향(+)으로만 돌린다. 한 바퀴 스캔 후
      0도로 돌아갈 때도 역회전(A0) 대신 남은 각도만큼 정방향으로 돌리고 Z로 리셋.
    - 아두이노 IDE의 시리얼 모니터가 열려 있으면 포트를 쓸 수 없다.

단독 테스트 (36 x 10도 = 한 바퀴 돈 뒤 펜 마킹 위치로 돌아오는지 확인):
    python turntable.py --test
    python turntable.py --port COM6 --test
"""

import argparse
import time

import config

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover
    serial = None


# 3D 펌웨어(v2.6)가 0.5초마다 보내는 상태 줄. 명령 응답이 아니므로 건너뛴다
STATUS_PREFIXES = ("STAT,", "EVT,", "HINT,", "BEAM,")


class Turntable:
    """아두이노 턴테이블 1대. with 문으로 쓰면 끝날 때 포트를 자동으로 닫는다.

    명령 → 아두이노 응답
        R<각도> 상대 회전, A<각도> 절대 위치 이동, Z 현재 위치를 0도로 → DONE
        S 저속 연속 회전 시작 → STARTED
        X 즉시 정지 + 1초 안정화 → DONE
        P 현재 각도 → 숫자
    """
    def __init__(self, port=config.SERIAL_PORT, baud=config.SERIAL_BAUD,
                 timeout=config.SERIAL_TIMEOUT_S):
        if serial is None:
            raise RuntimeError("pyserial이 필요합니다: pip install pyserial")
        # 포트 설정(timeout 포함)은 연 뒤에 절대 바꾸지 않는다. Windows에서는 timeout을
        # 바꿀 때마다 포트가 재설정되며 아두이노 쪽에 잡음 바이트가 들어가, 다음 명령
        # 앞에 붙어 ERR이 나는 것으로 추정됨(P-27: 설정을 안 바꾸는 진단 스크립트는 정상). 짧은 고정 timeout으로 열고
        # 대기 시간은 _readline()이 직접 센다.
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.cmd_timeout = timeout
        self.position_deg = 0.0      # 누적 명령 각도 (한 바퀴 넘어도 계속 증가)
        # 연속 회전(S/X)을 지원하는가. 3D 펌웨어(v2.6)는 R/A/Z/P 만 있어서 stop() 때 False 로 바뀐다
        self.continuous = True
        self._wait_ready()

    def _wait_ready(self, wait_s=4.0):
        # 우노는 포트를 열면 리셋되고 부팅 후 READY를 보낸다. 리셋이 안 되는
        # 보드(또는 이미 켜져 있던 경우)는 P 명령으로 살아 있는지 확인한다.
        deadline = time.time() + wait_s
        while time.time() < deadline:
            line = self._readline(timeout=0.5)
            if line == "READY":
                time.sleep(0.5)
                self._sync()
                return
        self._sync()
        reply = self._command("P", expect_done=False)
        try:
            float(reply)
        except ValueError:
            raise RuntimeError(f"턴테이블 응답이 없습니다 (P -> {reply!r}). 포트/전원을 확인하세요.")

    def _readline(self, timeout=None):
        """한 줄 읽기. 포트 timeout은 건드리지 않고 마감 시각까지 조각을 모은다."""
        deadline = time.time() + (self.cmd_timeout if timeout is None else timeout)
        buf = b""
        while True:
            buf += self.ser.readline()          # '\n'이 오거나 0.1초가 지나면 반환
            if buf.endswith(b"\n") or time.time() >= deadline:
                return buf.decode(errors="ignore").strip()

    def _reply(self, timeout=None):
        """명령 응답 1줄. 3D 펌웨어의 상태 줄(STAT, 등)은 건너뛴다"""
        deadline = time.time() + (self.cmd_timeout if timeout is None else timeout)
        while True:
            line = self._readline(timeout=max(0.1, deadline - time.time()))
            if not line.startswith(STATUS_PREFIXES):
                return line
            if time.time() >= deadline:
                return ""

    def _sync(self):
        """아두이노 쪽 수신 버퍼 정리 (보험).
        아두이노 버퍼에 잡음 바이트가 남아 있으면 다음 명령 앞에 붙어 ERR이 된다
        (예: '\\x00P'). 빈 줄을 한 번 보내 잡음을 별도 줄로 끊고, 그 응답은 버린다."""
        self.ser.write(b"\n")
        time.sleep(0.3)
        for _ in range(5):
            if not self._readline(timeout=0.2):
                break
        self.ser.reset_input_buffer()

    def _command(self, cmd, expect_done=True, _retry=True):
        """명령 1줄을 보내고 응답 1줄을 돌려준다.
        expect_done=True 면 응답이 DONE 이 아닐 때 RuntimeError (회전·정지 명령용)"""
        self.ser.reset_input_buffer()  # 이전 명령의 남은 응답이 섞이지 않게 비운다
        self.ser.write((cmd + "\n").encode())
        reply = self._reply()
        if reply == "ERR" and _retry:
            # 명령 앞에 잡음이 붙어 인식 못한 경우 → 버퍼 정리 후 한 번만 재시도
            print(f"  [참고] {cmd!r}에 ERR 응답 → 시리얼 버퍼 정리 후 재시도")
            self._sync()
            return self._command(cmd, expect_done, _retry=False)
        if expect_done and reply != "DONE":
            raise RuntimeError(f"턴테이블 응답 이상: {cmd!r} -> {reply!r}")
        return reply

    # ---- 공개 API --------------------------------------------------------
    def start(self):
        """저속 연속 회전 시작/재개."""
        if not self.continuous:
            raise RuntimeError("이 보드의 펌웨어(3D 용)는 연속 회전(S)이 없습니다. R 로 각도씩 돌리세요")
        reply = self._command("S", expect_done=False)
        if reply != "STARTED":
            raise RuntimeError(f"연속 회전 시작 실패: {reply!r}")

    def stop(self):
        """즉시 스텝 정지 후 안정화 DONE까지 대기."""
        reply = self._command("X", expect_done=False)
        if reply == "ERR":
            # 3D 펌웨어: X 가 없다 (R 로 정한 각도만 이동하고 스스로 멈추므로 정지할 것이 없음)
            self.continuous = False
        elif reply != "DONE":
            raise RuntimeError(f"턴테이블 응답 이상: 'X' -> {reply!r}")
        self.position_deg = self.reported_angle()

    def rotate(self, deg):
        """현재 위치에서 deg만큼 회전(정방향 권장). DONE까지 기다린다."""
        if deg < 0:
            print("  [주의] 역방향 회전은 기어 백래시로 위치 오차가 생길 수 있습니다.")
        self._command(f"R{deg:.3f}")
        self.position_deg += deg

    def zero(self):
        """현재 위치를 0도로 설정."""
        self._command("Z")
        self.position_deg = 0.0

    def take_up_backlash(self, deg=None):
        """기어 유격(백래시) 제거: 정방향으로 조금 돌린 뒤 그 자리를 0도로 삼는다.
        손으로 원판을 반대로 돌렸거나 역회전한 뒤에는 첫 정방향 이동의 몇 도가 유격을
        메우는 데 쓰여 실제로는 덜 돈다(10-01 실측: 첫 10도 명령 → 5.4도, P-31).
        이후 명령은 모두 정방향이므로 유격이 다시 생기지 않는다."""
        deg = getattr(config, "BACKLASH_TAKEUP_DEG", 8.0) if deg is None else deg
        if deg > 0:
            self.rotate(deg)
        self.zero()

    def finish_turn(self):
        """정방향으로 남은 각도만큼 돌려 0도(360의 배수) 위치로 돌아간 뒤 Z."""
        rest = (-self.position_deg) % 360.0
        if rest > 1e-6:
            self.rotate(rest)
        self.zero()

    def reported_angle(self):
        """아두이노가 실제로 센 현재 각도(P 명령). 연속 회전 중에도 쓸 수 있다"""
        reply = self._command("P", expect_done=False)
        try:
            return float(reply)
        except ValueError:
            raise RuntimeError(
                f"현재 각도(P) 응답이 숫자가 아닙니다: {reply!r}. v2.1 turntable.ino가 업로드됐는지, "
                "시리얼 모니터에서 P를 보내 숫자가 오는지 확인하세요.") from None

    def close(self):
        """시리얼 포트 닫기 (다른 프로그램이나 아두이노 IDE 가 포트를 쓸 수 있게 된다)"""
        self.ser.close()

    # with Turntable(...) as tt: 형태로 쓰기 위한 메서드
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main():
    """단독 실행: 연결 확인만 하거나(--test 없이), 한 바퀴 회전 정확도 테스트(--test)"""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=config.SERIAL_PORT)
    ap.add_argument("--test", action="store_true", help="config의 각도 간격 x N_VIEWS회 한 바퀴 회전 테스트")
    args = ap.parse_args()

    with Turntable(args.port) as tt:
        print("연결 완료. 현재 각도:", tt.reported_angle())
        if not args.test:
            return
        input("펜 마킹을 0도에 맞춘 뒤 Enter를 누르세요...")
        tt.zero()
        t0 = time.time()
        for i in range(config.N_VIEWS):
            t = time.time()
            tt.rotate(config.ANGLE_STEP_DEG)
            print(f"  {i + 1:2d}/{config.N_VIEWS}  {tt.position_deg:6.1f}도  ({time.time() - t:.2f}s)")
        tt.zero()
        print(f"한 바퀴 완료: {time.time() - t0:.1f}s. 펜 마킹이 0도 위치로 돌아왔는지 눈으로 확인하세요.")


if __name__ == "__main__":
    main()
