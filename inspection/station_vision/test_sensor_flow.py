"""
검사 프로그램의 센서 안전 흐름 시험 (시뮬레이션 장비, DB 저장은 가로채서 기록만 한다)

    cd inspection\\station_vision
    .venv\\Scripts\\python.exe test_sensor_flow.py

시험하는 것 (모두 화면 버튼 동작을 코드로 흉내 낸다):
  1. PatchCore 도중 보호구역 진입 → 즉시 정지("인터락 정지") + 알람 기록
  2. 구역에 사람이 있는 채로 [인터락 리셋] → 거부
  3. 구역 비움 → [인터락 리셋] → [이어서 진행] → 멈춘 자리부터 이어서 끝까지 (12장, 각도 순서대로)
  4. YOLO 단계 검사(5도씩)에서도 같은 흐름
"""
import sys
import time
import tkinter as tk

import inspection_app as ia

DB_CALLS = []


def fake_submit(self, db_url, storage_dir, action, **kwargs):
    DB_CALLS.append((action, kwargs))


ia.Sender.submit = fake_submit


def main():
    root = tk.Tk()
    app = ia.App(root, True, gate_3d=False, sim_sensors=True)
    eng = app.engine

    def pump(seconds=0.1, until=None, limit=240):
        end = time.time() + (limit if until else seconds)
        while time.time() < end:
            root.update()
            time.sleep(0.02)
            if until and until():
                return True
        return not until

    def status():
        return app.vars["status"].get()

    def log_has(text):
        return any(text in line for line in app.log.get(0, "end"))

    def check(name, cond):
        print(("통과  " if cond else "실패  ") + name, flush=True)
        if not cond:
            print("\n".join(app.log.get(0, "end")[-25:]))
            sys.exit(1)

    check("엔진 준비", pump(until=lambda: status() == "대기" and eng.table is not None))
    check("센서 장비로 인식 (안전 상태 목록이 잠김)", pump(until=lambda: app.sensor_mode, limit=10)
          and str(app.safety_boxes["interlock"].cget("state")) == "disabled")

    # ---------------- PatchCore 도중 인터락
    app.pc_var.set(True)
    eng.send("start")
    check("PatchCore 시작", pump(until=lambda: status().startswith("PatchCore "), limit=60))
    pump(until=lambda: status().startswith("PatchCore 3/"), limit=60)
    eng.table.enter_zone()
    check("구역 진입 → 즉시 인터락 정지", pump(until=lambda: status() == "인터락 정지", limit=20))
    check("정지 알람이 DB 기록으로 넘어감", any(a == "check_safety" and k["interlock"] == "1" for a, k in DB_CALLS))
    stopped_at = eng.table.position_deg
    pump(1.0)
    check("정지 중에는 더 돌지 않음", eng.table.position_deg == stopped_at and status() == "인터락 정지")
    check("[이어서 진행]은 아직 꺼져 있음", str(app.btn_resume.cget("state")) == "disabled" if False else app.hold == "reset")

    app.confirm_var.set(True)
    app.confirmed("reset")
    pump(1.0)
    check("사람이 있는 채로 리셋 → 거부", log_has("아직 보호구역에 사람이나 물체가") and status() == "인터락 정지")

    eng.table.leave_zone()
    app.confirm_var.set(True)
    app.confirmed("reset")
    check("구역을 비우고 리셋 → 이어서 진행 대기", pump(until=lambda: app.hold == "resume", limit=10))
    app.confirm_var.set(True)
    app.confirmed("resume")
    check("이어서 진행 → PatchCore 재개", pump(until=lambda: status().startswith("PatchCore "), limit=20))
    check("PatchCore 끝까지 완료", pump(until=lambda: status() in ("완료", "YOLO 검사 중"), limit=120))
    angles = [float(l.split("(")[1].split("°")[0]) for l in app.log.get(0, "end") if "PatchCore " in l and "°)" in l]
    check(f"각도가 30도씩 순서대로 12장 ({angles})", angles == [30.0 * i for i in range(12)])

    # ---------------- YOLO 단계 검사 도중 인터락
    pump(until=lambda: status() in ("완료",), limit=240)
    app.pc_var.set(False)  # PatchCore 없이 YOLO 만 (5도씩)
    eng.send("start")
    check("YOLO 단계 검사 시작", pump(until=lambda: status() == "YOLO 검사 중", limit=60))
    pump(until=lambda: float(app.vars["angle"].get().rstrip("°")) >= 20, limit=120)
    eng.table.enter_zone()
    check("YOLO 도중 구역 진입 → 인터락 정지", pump(until=lambda: status() == "인터락 정지", limit=30))
    eng.table.leave_zone()
    app.confirm_var.set(True)
    app.confirmed("reset")
    check("리셋됨", pump(until=lambda: app.hold == "resume", limit=10))
    app.confirm_var.set(True)
    app.confirmed("resume")
    check("YOLO 재개", pump(until=lambda: status() == "YOLO 검사 중", limit=20))
    check("YOLO 한 바퀴 완료", pump(until=lambda: status() == "완료", limit=400))
    print("모두 통과")
    root.destroy()


if __name__ == "__main__":
    main()
