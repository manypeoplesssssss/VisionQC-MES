"""
turntable.py 의 센서 기능 시험 (가짜 보드 사용, 장비 필요 없음)

    cd inspection\\station_vision
    .venv\\Scripts\\python.exe test_turntable_sensors.py

가짜 보드는 3D 펌웨어(v2.6) + 'U' 명령 복사본(turntable_safety)처럼 행동한다:
0.5초마다 STAT 줄, 인터락 중에는 회전 명령에 ERR,INTERLOCK, 구역이 1초 이상 비어야 U 가 먹힘, C/K 놓임 검사.
"""
import threading
import time
import types

import turntable as tt


class FakeBoard:
    """시리얼 포트처럼 보이는 가짜 보드 (스레드로 STAT 을 계속 보낸다)"""
    def __init__(self, *a, **k):
        self.out = bytearray(b"READY\n")
        self.lock = threading.Lock()
        self.angle = 0.0
        self.state = "RUN"            # RUN / TRIPPED / FAULT
        self.person_in_zone = False
        self.clear_since = None
        self.placement = "PLACE,OK"   # C 명령의 답
        self.buf = b""
        self.running = True
        threading.Thread(target=self._stat_loop, daemon=True).start()

    # ---- 보드 동작
    def _send(self, text):
        with self.lock:
            self.out += (text + "\n").encode()

    def _stat_loop(self):
        while self.running:
            cm = 12 if self.person_in_zone else 80
            if self.state == "RUN" and self.person_in_zone:
                self.state = "TRIPPED"
                self._send("EVT,TRIPPED")
            if self.person_in_zone:
                self.clear_since = None
            elif self.clear_since is None:
                self.clear_since = time.monotonic()
            self._send(f"STAT,{self.state},{cm},80")
            time.sleep(0.1)  # 시험이 빠르도록 실제(0.5초)보다 자주

    def _exec(self, cmd):
        k = cmd[:1].upper()
        if k in "RA":
            if self.state != "RUN":
                self._send("ERR,INTERLOCK")
            else:
                self.angle = self.angle + float(cmd[1:]) if k == "R" else float(cmd[1:])
                self._send("DONE")
        elif k == "P":
            self._send(f"{self.angle:.2f}")
        elif k == "Z":
            self.angle = 0.0
            self._send("DONE")
        elif k == "C":
            self._send("PLACE,ERR,INTERLOCK" if self.state != "RUN" else self.placement)
        elif k == "K":
            self._send("CAL,ERR,INTERLOCK" if self.state != "RUN" else "CAL,OK")
        elif k == "U":
            if self.state == "RUN":
                self._send("RESET,OK")
            else:
                time.sleep(0.15)
                ready = (not self.person_in_zone and self.clear_since is not None
                         and time.monotonic() - self.clear_since >= 0.5)
                if ready:
                    self.state = "RUN"
                    self._send("EVT,RUN")
                    self._send("RESET,OK")
                else:
                    self._send("RESET,ERR,NOT_CLEAR")
        else:
            self._send("ERR")

    # ---- pyserial 흉내
    @property
    def in_waiting(self):
        with self.lock:
            return len(self.out)

    def readline(self):
        deadline = time.time() + 0.1
        while time.time() < deadline:
            with self.lock:
                i = self.out.find(b"\n")
                if i >= 0:
                    line = bytes(self.out[:i + 1])
                    del self.out[:i + 1]
                    return line
            time.sleep(0.005)
        return b""

    def write(self, data):
        for c in data.decode().split("\n"):
            if c.strip():
                self._exec(c.strip())

    def reset_input_buffer(self):
        with self.lock:
            self.out.clear()

    def close(self):
        self.running = False


def main():
    tt.serial = types.SimpleNamespace(Serial=FakeBoard)
    t = tt.Turntable(port="FAKE")
    board = t.ser

    # 1) 센서가 있는 펌웨어로 인식, 인터락 정상
    assert t.has_sensors and t.interlock_state() == "0", "센서 인식 실패"
    print("1. 센서 있는 펌웨어로 인식, 인터락 0(정상)")

    # 2) 사람이 들어오면 인터락 1 (상태 줄만 듣고도 알 수 있다)
    board.person_in_zone = True
    time.sleep(0.4)
    assert t.interlock_state() == "1"
    print("2. 구역 진입 → 인터락 1(비정상)")

    # 3) 정지 중 회전 명령 → InterlockStop, 위치는 안 변함
    start = t.position_deg
    try:
        t.rotate(5)
        raise AssertionError("InterlockStop 이 안 났다")
    except tt.InterlockStop:
        assert t.position_deg == start
    print("3. 정지 중 회전 → InterlockStop, 누적 각도 그대로")

    # 4) 사람이 아직 구역에 있으면 리셋 거부
    ok, why = t.reset_interlock()
    assert (ok, why) == (False, "NOT_CLEAR")
    print("4. 구역에 사람이 있을 때 리셋 → 거부 (NOT_CLEAR)")

    # 5) 구역을 비우고 잠시 뒤 리셋 성공, 이어서 회전
    board.person_in_zone = False
    time.sleep(0.8)
    ok, why = t.reset_interlock()
    assert (ok, why) == (True, "OK"), (ok, why)
    t.resume_rotation(start + 5)
    assert abs(board.angle - 5) < 1e-6 and t.position_deg == start + 5
    assert t.interlock_state() == "0"
    print("5. 구역을 비운 뒤 리셋 성공 → 남은 각도만 이어서 회전, 인터락 0")

    # 6) 놓임 검사 · 보정
    assert t.calibrate_placement() is True
    assert t.check_placement() == (True, "OK")
    board.placement = "PLACE,ERR,OFFSET_X"
    assert t.check_placement() == (False, "OFFSET_X")
    print("6. 놓임 보정 OK, 놓임 검사 OK / OFFSET_X")

    # 7) 상태 줄이 끊기면 미확인
    board.running = False
    time.sleep(tt.STAT_STALE_S + 0.3)
    assert t.interlock_state() == "UNKNOWN"
    print("7. 상태 줄이 끊기면 인터락 미확인(UNKNOWN)")

    # 8) 비전용 펌웨어(상태 줄 없음)는 센서 없음
    class NoSensorBoard(FakeBoard):
        def _stat_loop(self):
            pass
    tt.serial = types.SimpleNamespace(Serial=NoSensorBoard)
    t2 = tt.Turntable(port="FAKE")
    assert not t2.has_sensors and t2.interlock_state() is None
    print("8. 상태 줄이 없는 펌웨어는 센서 없음(수동 입력)")
    print("모두 통과")


if __name__ == "__main__":
    main()
