r"""
interlock_patch.py — 3D 스캔 중 인터락·놓임 불량 때 검사 프로그램 버튼으로 이어 가게 하는 덮어쓰기

3D 코드(station_3d)는 수정하지 않는다. run_3d_script.py 가 실행 직전에 turntable.Turntable._wait_run 과
builtins.input 을 이 파일의 함수로 바꿔 끼운다 (그 프로세스 안에서만 바뀌고 파일은 그대로).

1) 인터락 대기 (_wait_run)
   원래 3D 코드는 구역이 비워진 뒤 물리 리셋 버튼(D4)을 누를 때까지 기다린다. 동작은 그대로 두고,
   환경변수 VISIONQC_3D_RESET_FILE 의 파일이 생기면(검사 프로그램의 [인터락 리셋] 버튼) 펌웨어에 'U'(리셋 요청)를 보낸다.
   펌웨어가 구역이 1초 이상 비어 있을 때만 받아들이므로 사람이 있는 채로 풀리지는 않는다.
   표준 출력에 `@@INTERLOCK` (멈춤) / `@@INTERLOCK_CLEARED` (풀림, 이어서 회전) 줄을 찍는다 (검사 프로그램이 읽는다).
   'U' 가 없는 펌웨어(3D 원본 펌웨어)면 'U' 에 ERR 이 올 뿐이라 물리 리셋 버튼으로 풀면 된다.
2) 놓임 불량 재시도 (input)
   turntable_scan.ensure_placed() 가 "물체를 다시 놓은 뒤 Enter" 를 input() 으로 기다린다. 검사 프로그램에서 실행하면
   키보드가 없으므로, 이 대기도 VISIONQC_3D_GO_FILE 이 생길 때(검사 프로그램의 진행 버튼)까지 기다렸다가 Enter 로 처리한다.
   (`@@WAIT retry` 를 찍는다. 중단은 [정지] 버튼)
"""
import builtins
import os
import time


def install_reset(turntable_module):
    reset_file = os.environ.get("VISIONQC_3D_RESET_FILE")
    Turntable = turntable_module.Turntable

    def _wait_run(self):
        print("  [인터락] 보호구역 감지 → 턴테이블 정지.\n"
              "           구역을 비우고(30cm 밖) 1초 뒤 검사 프로그램의 [인터락 리셋] 또는 보드의 리셋 버튼을 누르세요...", flush=True)
        print("@@INTERLOCK", flush=True)
        self.fw_state = None
        last_msg = time.time()
        if reset_file and os.path.exists(reset_file):
            os.remove(reset_file)  # 이전 신호가 남아 있으면 바로 리셋해 버리므로 지운다
        while self.fw_state != "RUN":
            line = self._readline(timeout=1.0)
            if line.startswith(self._STATUS_PREFIXES):
                self._note_status(line)
            elif line.startswith("RESET,"):
                print(f"  [인터락] 프로그램 리셋 응답: {line}", flush=True)
            if reset_file and os.path.exists(reset_file):
                os.remove(reset_file)
                self.ser.write(b"U\n")
            if self.fw_state == "FAULT" and time.time() - last_msg > 10:
                print("  [인터락] 센서 고장(FAULT) 상태입니다. 센서 배선/가림을 확인하세요.", flush=True)
                last_msg = time.time()
        print("  [인터락] 리셋됨(RUN). 물체가 움직이지 않았는지 확인하세요. 이어서 진행합니다.", flush=True)
        print("@@INTERLOCK_CLEARED", flush=True)

    Turntable._wait_run = _wait_run


def install_input(go_file):
    real_input = builtins.input

    def patched_input(prompt=""):
        if not go_file:
            return real_input(prompt)
        print(prompt, flush=True)
        if os.path.exists(go_file):
            os.remove(go_file)
        print("@@WAIT retry", flush=True)
        while not os.path.exists(go_file):
            time.sleep(0.2)
        os.remove(go_file)
        print("@@GO", flush=True)
        return ""

    builtins.input = patched_input
