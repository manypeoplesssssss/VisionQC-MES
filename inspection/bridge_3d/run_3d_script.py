r"""
run_3d_script.py — station_3d 스크립트를 코드 수정 없이, 설정 일부만 바꿔서 실행하는 실행기

    python run_3d_script.py <3D 코드 폴더> <스크립트.py> [스크립트 인자...]

3D 코드(station_3d)는 건드리지 않는다. 대신 실행 직전에 그 폴더의 config 모듈 값을 환경변수로 덮어쓴다.
    VISIONQC_3D_SERIAL_PORT   턴테이블 아두이노 포트 (config.SERIAL_PORT 를 덮어씀. 예: COM3)
    VISIONQC_3D_GO_FILE       스캔의 Space 대기를 이 파일이 생길 때도 넘김 (wait_patch.py, 검사 프로그램 버튼)
검사 프로그램(inspection_app.py)이 station_vision/config.py 의 SERIAL_PORT 를 이 변수로 넘겨 준다.
"""
import os
import runpy
import sys

folder, script, *args = sys.argv[1:]
folder = os.path.abspath(folder)
os.chdir(folder)                      # 3D 코드는 현재 폴더 기준 상대경로(scans/, rig_calibration.npz)를 쓴다
sys.path.insert(0, folder)
import config  # noqa: E402  (3D 폴더의 config.py)

port = os.environ.get("VISIONQC_3D_SERIAL_PORT")
if port and getattr(config, "SERIAL_PORT", None) != port:
    print(f"(3D 설정 SERIAL_PORT {config.SERIAL_PORT} → {port} 로 덮어씀, 3D 코드는 수정하지 않음)", flush=True)
    config.SERIAL_PORT = port

if script == "turntable_scan.py" and os.environ.get("VISIONQC_3D_GO_FILE"):
    # 스캔의 Space 대기를 검사 프로그램 버튼으로도 넘길 수 있게 한다 (3D 코드는 수정하지 않음)
    import d435_common  # noqa: E402
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import wait_patch  # noqa: E402
    wait_patch.install(d435_common, config)

sys.argv = [script, *args]
runpy.run_path(os.path.join(folder, script), run_name="__main__")
