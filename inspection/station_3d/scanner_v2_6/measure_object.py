"""
measure_object.py — 병합 모델에서 가로/세로/높이 측정 + 공차 판정 + JSON 출력

모델이 턴테이블 좌표계(원판 윗면 = y 0, Y = 회전축)로 저장되므로:
    높이      = 물체 최고점의 y (원판 윗면부터). 구버전의 "y 범위"는 원판 노이즈를
                자르느라 버린 바닥 몇 mm만큼 작게 나왔는데, 이제 원판 기준이라 정확하다.
    가로/세로 = X-Z 평면(위에서 내려다본 모양) 최소 외접 사각형 방향의 긴 변/짧은 변.
                물체가 비스듬히 놓여도 실제 폭·깊이가 나온다. 양 끝 MEASURE_TRIM_PCT %
                (기본 1%)의 가장자리 잡음은 제외하고 잰다(최소~최대 값도 함께 기록).

출력: 콘솔 + <세션>/measurement.json (LLM 리포트 입력용)

실행:
    python measure_object.py                          # 최근 세션의 merged_model.ply
    python measure_object.py scans/20261001_1030      # 세션 지정
    python measure_object.py 파일.ply                 # ply 직접 지정
    python measure_object.py --ref 60.02 40.10 80.05  # 캘리퍼스 실측(가로 세로 높이, mm)과 비교
                                                      # → 오차표 + 추천 SCALE_CORRECTION 출력
    python measure_object.py --slice 0.02 0.05        # 높이 2~5cm 구간만으로 가로/세로
"""

import argparse
import datetime as dt
import json
import os

import cv2
import numpy as np

import config

DIM_KEYS = ("width", "depth", "height")
DIM_KO = {"width": "가로(긴 변)", "depth": "세로(짧은 변)", "height": "높이"}


def measure_points(pts, height_slice=None, scale=1.0, trim_pct=None):
    """(N,3) 턴테이블 좌표 점 → 치수 dict (mm). numpy/cv2만 사용.

    가로/세로: 위에서 본 최소 외접 사각형의 방향으로 점을 정렬한 뒤, 각 방향 양 끝
    trim_pct %를 뺀 범위(기본 config.MEASURE_TRIM_PCT). 물체 끝 깊이 경계에 남는
    얇은 잡음 층(전체 점의 약 1%)이 최소~최대 범위를 몇 mm씩 부풀리는 문제 대응
    (10-01, S13 자동차: 최소~최대 208.6×89.6mm → 1~99% 195.1×83.4mm, 실측 195.0×83.8mm).
    trim_pct=0이면 예전처럼 최소~최대. 높이는 지붕 면적이 작아 자르지 않고 최고점 사용."""
    if len(pts) < 5:
        raise ValueError("측정할 점이 너무 적습니다.")
    if trim_pct is None:
        trim_pct = getattr(config, "MEASURE_TRIM_PCT", 1.0)
    height = pts[:, 1].max()               # 원판 윗면(y=0)부터
    sl = pts
    if height_slice is not None:
        lo, hi = height_slice
        sl = pts[(pts[:, 1] >= lo) & (pts[:, 1] <= hi)]
        if len(sl) < 5:
            raise ValueError("높이 구간 안에 점이 너무 적습니다.")
    xz = sl[:, [0, 2]].astype(np.float64)
    rect = cv2.minAreaRect(xz.astype(np.float32))
    a = np.radians(rect[2])
    u = np.array([np.cos(a), np.sin(a)])
    v = np.array([-np.sin(a), np.cos(a)])
    pu, pv = xz @ u, xz @ v

    def extent(x, t):
        lo, hi = np.percentile(x, [t, 100 - t]) if t > 0 else (x.min(), x.max())
        return hi - lo, (hi + lo) / 2

    eu, cu = extent(pu, trim_pct)
    ev, cv = extent(pv, trim_pct)
    w, d = max(eu, ev), min(eu, ev)
    center = cu * u + cv * v
    raw_w, raw_d = max(rect[1]), min(rect[1])
    return dict(
        width=float(w * 1000 * scale),
        depth=float(d * 1000 * scale),
        height=float(height * 1000 * scale),
        height_range=float((pts[:, 1].max() - pts[:, 1].min()) * 1000 * scale),
        raw_width=float(raw_w * 1000 * scale),
        raw_depth=float(raw_d * 1000 * scale),
        trim_pct=float(trim_pct),
        center_offset_mm=[float(center[0] * 1000), float(center[1] * 1000)],
        n_points=int(len(pts)),
    )


def _per_axis(v, k):
    """숫자면 세 축 공통, dict면 축별 값. 없으면 None."""
    if v is None:
        return None
    return v.get(k) if isinstance(v, dict) else float(v)


def judge(dims, nominal, tol, recheck=None):
    """공차 판정. nominal: {width, depth, height} (mm).

    tol: 불량(NG) 한계 — 숫자(세 축 공통) 또는 축별 dict.
    recheck: 정상(OK) 한계 — 주면 3단계 판정(10-02, 자동차 5회 기준):
      |편차| <= recheck → OK, recheck < |편차| <= tol → RECHECK(다시 스캔해 평균으로 재판정),
      |편차| > tol → NG. recheck가 없으면 예전처럼 OK/NG 2단계."""
    out = {}
    for k in DIM_KEYS:
        if nominal and k in nominal:
            dev = dims[k] - nominal[k]
            t, r = _per_axis(tol, k), _per_axis(recheck, k)
            status = "NG" if abs(dev) > t else ("RECHECK" if r is not None and abs(dev) > r else "OK")
            out[k] = dict(nominal=nominal[k], deviation=round(dev, 2), ng_limit=t,
                          ok_limit=r if r is not None else t, status=status, ok=status != "NG")
    if out:
        st = [v["status"] for v in out.values()]
        out["result"] = "NG" if "NG" in st else ("RECHECK" if "RECHECK" in st else "OK")
        out["pass"] = out["result"] != "NG"
    return out


def compare_reference(dims, ref):
    """캘리퍼스 실측과 비교. 반환: 축별 오차와 추천 보정계수."""
    rows, ratios = {}, []
    for k, r in zip(DIM_KEYS, ref):
        rows[k] = dict(caliper=r, scanned=round(dims[k], 2), error=round(dims[k] - r, 2),
                       error_pct=round((dims[k] - r) / r * 100, 2))
        ratios.append(r / dims[k])
    return rows, float(np.mean(ratios))


def clean_for_measurement(pcd):
    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=1.5)
    labels = np.array(pcd.cluster_dbscan(eps=0.01, min_points=8, print_progress=False))
    valid = labels[labels >= 0]
    if len(valid):
        pcd = pcd.select_by_index(np.where(labels == np.bincount(valid).argmax())[0])
    return pcd


def resolve_input(path):
    if path is None:
        from merge_turntable_scans import latest_session
        path = latest_session()
    if os.path.isdir(path):
        return os.path.join(path, "merged_model.ply"), path
    return path, os.path.dirname(os.path.abspath(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=None, help="세션 폴더 또는 .ply")
    ap.add_argument("--ref", nargs=3, type=float, metavar=("W", "D", "H"),
                    help="캘리퍼스 실측 가로 세로 높이 (mm)")
    ap.add_argument("--slice", nargs=2, type=float, metavar=("Y_LO", "Y_HI"),
                    help="가로/세로를 잴 높이 구간 (m, 원판 윗면 기준)")
    ap.add_argument("--sample", default=None, help="샘플 ID (JSON 기록용)")
    args = ap.parse_args()

    import open3d as o3d
    ply, session = resolve_input(args.path)
    pcd = o3d.io.read_point_cloud(ply)
    if len(pcd.points) == 0:
        raise RuntimeError(f"'{ply}'에 포인트가 없습니다.")
    pcd = clean_for_measurement(pcd)
    dims = measure_points(np.asarray(pcd.points), args.slice, config.SCALE_CORRECTION)

    print(f"\n=== 측정 결과: {ply} ===")
    for k in DIM_KEYS:
        print(f"  {DIM_KO[k]:10s}: {dims[k]:7.2f} mm")
    if dims["trim_pct"] > 0:
        print(f"  (가로/세로는 양 끝 {dims['trim_pct']:.1f}% 잡음 제외. 최소~최대 기준: "
              f"{dims['raw_width']:.2f} x {dims['raw_depth']:.2f} mm)")
    if config.SCALE_CORRECTION != 1.0:
        print(f"  (보정계수 {config.SCALE_CORRECTION:.4f} 적용)")
    off = np.hypot(*dims["center_offset_mm"])
    if off > 15:
        print(f"  [참고] 물체 중심이 회전축에서 {off:.0f}mm 떨어져 있습니다. 중앙에 둘수록 가림이 줄어듭니다.")

    result = dict(
        timestamp=dt.datetime.now().isoformat(timespec="seconds"),
        sample=args.sample, source=os.path.relpath(ply), unit="mm",
        dimensions={k: round(dims[k], 2) for k in DIM_KEYS},
        dimensions_raw_minmax={"width": round(dims["raw_width"], 2), "depth": round(dims["raw_depth"], 2)},
        trim_pct=dims["trim_pct"],
        n_points=dims["n_points"], scale_correction=config.SCALE_CORRECTION,
        tolerance_mm=config.TOLERANCE_MM,
        recheck_mm=getattr(config, "RECHECK_MM", None),
        judgement=judge(dims, config.NOMINAL_MM, config.TOLERANCE_MM, getattr(config, "RECHECK_MM", None)),
    )
    if result["judgement"]:
        ko = {"OK": "정상", "RECHECK": "재검(다시 스캔)", "NG": "불량"}
        print("\n=== 공차 판정 (기준 = 정상 차 스캔 평균) ===")
        for k in DIM_KEYS:
            j = result["judgement"].get(k)
            if j:
                print(f"  {DIM_KO[k]:10s}: 기준 {j['nominal']:.2f}  편차 {j['deviation']:+.2f}  "
                      f"(정상 ±{j['ok_limit']:.1f} / 불량 ±{j['ng_limit']:.1f} 초과)  {ko[j['status']]}")
        print(f"  종합: {ko[result['judgement']['result']]}")

    if args.ref:
        if all(r * 5 < dims[k] for r, k in zip(args.ref, DIM_KEYS)):
            print("\n[주의] --ref 값이 스캔값보다 5배 이상 작습니다. cm로 넣지 않았는지 확인하세요 (단위 mm).")
        rows, scale = compare_reference(dims, args.ref)
        result["caliper_comparison"] = rows
        print("\n=== 캘리퍼스 비교 ===")
        for k in DIM_KEYS:
            r = rows[k]
            print(f"  {DIM_KO[k]:10s}: 실측 {r['caliper']:7.2f}  스캔 {r['scanned']:7.2f}  "
                  f"오차 {r['error']:+6.2f} mm ({r['error_pct']:+.1f}%)")
        if result["judgement"].get("result") == "NG":
            # 불량 판정 샘플은 형상 자체가 달라 보정계수 계산에 쓰면 안 됨 (10-02, 불량 테스트 miss01)
            print("  (불량 판정 샘플이라 보정계수는 계산하지 않습니다 — 정상 샘플로만 보정)")
        else:
            print(f"  추천 보정계수: {scale * config.SCALE_CORRECTION:.4f} "
                  "(여러 샘플의 평균값을 config.SCALE_CORRECTION에 넣으세요)")

    out = os.path.join(session, "measurement.json")
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    print(f"\n'{out}' 저장 (LLM 리포트 입력용)")


if __name__ == "__main__":
    main()
