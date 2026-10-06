"""
serial_check.py — 턴테이블 시리얼 원시(raw) 통신 진단

아두이노가 보내는 바이트를 가공 없이 그대로 보여 준다. turntable.py가 ERR 등
예상 밖 응답을 받을 때, 보드에 어떤 펌웨어가 올라가 있고 명령을 어떻게 받는지 확인용.

    python serial_check.py            # config.SERIAL_PORT 사용
    python serial_check.py --port COM5
    python serial_check.py --placement      # (v2.6) 놓임 검사 응답도 확인

※ 아두이노 IDE 시리얼 모니터는 닫고 실행하세요. R10 명령으로 원판이 10도 돕니다.
"""
import argparse
import time

import config
import serial


def dump(ser, wait_s):
    """wait_s 동안 들어온 바이트를 그대로 모아 반환."""
    end = time.time() + wait_s
    buf = b""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            end = max(end, time.time() + 0.3)   # 더 올 수 있으니 조금 더 기다림
        else:
            time.sleep(0.02)
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=config.SERIAL_PORT)
    ap.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    ap.add_argument("--placement", action="store_true",
                    help="놓임 검사 원시 응답도 확인 (K 보정 → C 검사). 빔 사이를 비운 상태에서")
    args = ap.parse_args()

    print(f"포트 {args.port}, {args.baud}bps 열기 (우노는 여기서 리셋됨)")
    ser = serial.Serial(args.port, args.baud, timeout=1)
    boot = dump(ser, 4.0)
    print(f"[부팅 직후 수신] {boot!r}")

    for cmd in ["P", "Z", "P", "R10", "P", "p", "X"]:
        ser.write((cmd + "\n").encode())
        wait = 6.0 if cmd.startswith("R") else 1.5
        reply = dump(ser, wait)
        print(f"[보냄] {cmd!r:7} → [받음] {reply!r}")
    if args.placement:
        for cmd, wait in (("C", 12.0), ("K", 6.0), ("C", 12.0)):
            ser.write((cmd + "\n").encode())
            print(f"[보냄] {cmd!r:7} → [받음] {dump(ser, wait)!r}")
    ser.close()

    print("\n정상(v2.6 인터락 + 놓임 검사 펌웨어)이라면:")
    print("  부팅 직후 b'READY' 와 EVT,RUN / STAT,RUN,<cm>,<cm> 줄(0.5초마다 계속 옴 — 정상),")
    print("  P → '0.00', Z → 'DONE', R10 → (10도 회전 후) 'DONE', 그 다음 P → '10.00', p → 숫자, X → 'ERR'")
    print("  인터락 중(EVT,TRIPPED/FAULT)이면 R은 'ERR,INTERLOCK'으로 거부됨 → 구역을 비우고 리셋 버튼.")
    print("  STAT/EVT/HINT/BEAM 줄이 섞여 있어도 turntable.py는 이를 응답으로 보지 않는다.")
    print("  --placement: 첫 C(보정 전) → 'PLACE,ERR,BEAM_FAULT', K → 'CAL,OK', 두 번째 C → 'PLACE,OK' 또는 'PLACE,ERR,<원인>'.")


if __name__ == "__main__":
    main()
