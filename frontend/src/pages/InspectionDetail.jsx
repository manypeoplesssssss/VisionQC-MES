/**
 * 검사 상세 (pages/InspectionDetail.jsx) - 주소: /inspections/:id
 *
 * 검사 1회의 단계별 결과를 위에서 아래로 보여준다.
 *   요약        : 최종 결과, 제품, 제품번호, 사진 폴더
 *   3D 치수     : 실측 / 기준 / 차이 / 축별 합불 (허용오차 ±3mm)
 *   PatchCore   : 이상 점수 / 기준 / 합불
 *   YOLO        : 결함 사진 (누르면 크게) + 결함 목록 + 불량 코드(D01~D05) 지정
 *   원인 후보 · 권장 조치 : 지정한 불량 코드에서 자동으로 모임 (확정 원인이 아닌 후보)
 * 관리자는 불량 코드 지정과 검사 삭제를 할 수 있다.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtTime, isAdmin } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import ImageViewer from "../components/ImageViewer.jsx";
import { FinalBadge, StageBadge, YoloBadge } from "../components/ResultBadge.jsx";

const AXES = [
  ["width", "가로"],
  ["length", "길이"],
  ["height", "높이"],
];

export default function InspectionDetail() {
  const { id } = useParams(); // 주소의 :id 부분 (검사번호)
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = isAdmin(user);
  const [insp, setInsp] = useState(null);
  const [types, setTypes] = useState([]);
  const [viewing, setViewing] = useState(null); // 크게 보는 사진 (null 이면 닫힘)
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.inspection(id).then((d) => { setInsp(d); setError(""); }).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    api.defectTypes().then(setTypes).catch(() => {});
  }, []);

  /** 결함 1개에 불량 코드 지정/해제 */
  const setCode = async (index, code) => {
    try {
      setInsp(await api.setDefectCode(id, index, code || null));
    } catch (e) {
      alert(e.message);
    }
  };

  const remove = async () => {
    if (!confirm(`${id}\n이 검사 데이터와 사진을 모두 삭제할까요?`)) return;
    try {
      await api.deleteInspection(id);
      navigate("/inspections");
    } catch (e) {
      alert(e.message);
    }
  };

  if (error) return <><BackLink /><div className="error">{error}</div></>;
  if (!insp) return <div className="center muted">불러오는 중...</div>;
  const d = insp.dimension;
  const tol = insp.dimension_data?.tolerance_mm ?? 3;
  const activeTypes = types.filter((t) => t.is_active);

  return (
    <>
      <div className="page-head">
        <h2>
          검사 상세 · <span className="mono">{insp.inspection_id}</span> <FinalBadge value={insp.final_result} />
        </h2>
        <BackLink />
      </div>

      <section className="card">
        <dl className="kv wide">
          <dt>제품 모델</dt><dd>{insp.product_name}</dd>
          <dt>제품번호</dt><dd className="mono">{insp.product_serial || "-"}</dd>
          <dt>검사 시각</dt><dd>{fmtTime(insp.created_at)} <span className="muted small">(수정 {fmtTime(insp.updated_at)})</span></dd>
          <dt>사진 폴더</dt><dd className="mono small">{insp.capture_folder || "-"}</dd>
          <dt>단계</dt>
          <dd className="row-gap">
            3D 치수 <StageBadge value={insp.dimension_result} /> → PatchCore <StageBadge value={insp.patchcore_result} /> → YOLO <YoloBadge value={insp.yolo_status} />
          </dd>
        </dl>
      </section>

      <section className="grid-2">
        <div className="card">
          <h3>3D 치수 <StageBadge value={insp.dimension_result} /></h3>
          {d ? (
            <>
              <table className="mini">
                <thead>
                  <tr><th>축</th><th className="num">실측 (mm)</th><th className="num">기준 (mm)</th><th className="num">차이</th><th>합불</th></tr>
                </thead>
                <tbody>
                  {AXES.map(([k, label]) => {
                    const v = d[`${k}_mm`], s = d[`standard_${k}_mm`];
                    const diff = v != null && s != null ? v - s : null;
                    return (
                      <tr key={k}>
                        <th>{label}</th>
                        <td className="num">{v ?? "-"}</td>
                        <td className="num">{s ?? "-"}</td>
                        <td className={`num ${diff != null && Math.abs(diff) > tol ? "ng-text" : ""}`}>
                          {diff != null ? `${diff > 0 ? "+" : ""}${diff.toFixed(2)}` : "-"}
                        </td>
                        <td><StageBadge value={d[`${k}_result`]} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small">허용오차 ±{tol}mm (경계값 포함). 3D 스캔: <span className="mono">{d.scan_file_path || "-"}</span></p>
            </>
          ) : (
            <p className="muted small">아직 치수 측정값이 없습니다.</p>
          )}
        </div>

        <div className="card">
          <h3>PatchCore <StageBadge value={insp.patchcore_result} /></h3>
          {insp.patchcore_score != null ? (
            <table className="mini">
              <tbody>
                <tr><th>이상 점수</th><td className={`num ${insp.patchcore_result === "FAIL" ? "ng-text" : ""}`}>{insp.patchcore_score}</td></tr>
                <tr><th>판정 기준</th><td className="num">{insp.patchcore_threshold} <span className="muted small">(점수가 기준 이상이면 불합격)</span></td></tr>
                <tr><th>모델 버전</th><td>{insp.patchcore_model_version || "-"}</td></tr>
              </tbody>
            </table>
          ) : (
            <p className="muted small">아직 PatchCore 결과가 없습니다.</p>
          )}
        </div>
      </section>

      <section className="card">
        <h3>YOLO 불량 분류 <YoloBadge value={insp.yolo_status} /> {insp.yolo_model_version && <span className="muted small">모델 {insp.yolo_model_version}</span>}</h3>
        {insp.images.length === 0 ? (
          <p className="muted small">결함 사진이 없습니다.</p>
        ) : (
          <div className="thumbs">
            {insp.images.map((img) => (
              <button key={img.capture_number} className="thumb" onClick={() => setViewing(img)}>
                <img src={img.annotated_url || img.original_url} alt="" loading="lazy" />
                <div className="thumb-meta">
                  <b>사진 {img.capture_number}</b>
                  <span className="small">결함 {insp.defects.filter((x) => x.capture_number === img.capture_number).length}개</span>
                </div>
              </button>
            ))}
          </div>
        )}

        {insp.defects.length > 0 && (
          <table className="table" style={{ marginTop: 16 }}>
            <thead>
              <tr><th>사진</th><th>결함 종류</th><th className="num">신뢰도</th><th className="num">각도</th><th>위치 (box)</th><th>불량 코드</th></tr>
            </thead>
            <tbody>
              {insp.defects.map((x) => (
                <tr key={x.index}>
                  <td className="num">{x.capture_number}</td>
                  <td>{x.defect_class}</td>
                  <td className="num">{x.confidence.toFixed(3)}</td>
                  <td className="num">{x.angle_deg != null ? `${x.angle_deg}°` : "-"}</td>
                  <td className="mono small">{x.box ? `[${x.box.map((v) => Math.round(v)).join(", ")}]` : "-"}</td>
                  <td>
                    {admin ? (
                      <select value={x.defect_code || ""} onChange={(e) => setCode(x.index, e.target.value)}>
                        <option value="">미분류</option>
                        {/* 사용 중지된 코드라도 이미 지정된 값은 보이게 */}
                        {types.filter((t) => t.is_active || t.defect_code === x.defect_code).map((t) => (
                          <option key={t.defect_code} value={t.defect_code}>{t.defect_code} {t.defect_name}</option>
                        ))}
                      </select>
                    ) : (
                      x.defect_code ? `${x.defect_code} ${x.defect_name ?? ""}` : <span className="muted">미분류</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {admin && insp.defects.length > 0 && activeTypes.length > 0 && (
          <p className="muted small">YOLO 검출만으로는 D01~D05 공정 불량이 자동 분류되지 않습니다. 위치·공정을 확인해 불량 코드를 지정하세요.</p>
        )}
      </section>

      <section className="card">
        <h3>원인 후보 · 권장 조치</h3>
        {insp.recommended_action ? (
          <pre className="advice">{insp.recommended_action}</pre>
        ) : (
          <p className="muted small">불량 코드를 지정하면 그 코드의 원인 후보와 권장 조치가 여기에 모입니다. (원인은 확정이 아닌 후보)</p>
        )}
        <p className="muted small">리포트: {insp.report_path || "생성 전"}{insp.report_sent_at && ` · 발송 ${fmtTime(insp.report_sent_at)}`}</p>
      </section>

      {admin && <button className="danger" onClick={remove}>검사 데이터 삭제</button>}

      <ImageViewer
        image={viewing}
        defects={viewing ? insp.defects.filter((x) => x.capture_number === viewing.capture_number) : []}
        title={insp.inspection_id}
        onClose={() => setViewing(null)}
      />
    </>
  );
}

function BackLink() {
  return <Link to="/inspections">← 검사 조회</Link>;
}
