/**
 * 검사 상세 (pages/InspectionDetail.jsx) - 주소: /inspections/:id
 *
 * 검사 1회의 단계별 결과를 위에서 아래로 보여준다.
 *   요약        : 최종 결과, 제품, 제품번호, 사진 폴더
 *   3D 치수     : 실측 / 기준 / 차이 / 축별 합불 (허용오차 ±3mm)
 *   YOLO        : 결함 사진 (누르면 크게) + 결함 목록 + 불량 코드(D01~D05) 지정
 *   원인 후보 · 권장 조치 : 지정한 불량 코드에서 자동으로 모임 (확정 원인이 아닌 후보)
 * 관리자는 불량 코드 지정과 검사 삭제를 할 수 있다.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ALARM_TYPE_LABEL, api, fmtTime, isAdmin, STAGE_NAME } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import ImageViewer from "../components/ImageViewer.jsx";
import { AlarmBadge, FinalBadge, SafetyBadge, StageBadge, YoloBadge } from "../components/ResultBadge.jsx";

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
  // 축별 한계 (검사 당시 값, dimension_data 에 저장됨)
  const tol = insp.dimension_data?.tolerance_mm;
  const recheck = insp.dimension_data?.recheck_mm;
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
            3D 치수 <StageBadge value={insp.dimension_result} /> → YOLO <YoloBadge value={insp.yolo_status} />
          </dd>
          <dt>장비 상태</dt>
          <dd className="row-gap">
            센터링 <SafetyBadge kind="centering" value={insp.centering_state} /> 인터락 <SafetyBadge kind="interlock" value={insp.interlock_state} />
            <span className="muted small">(마지막 확인 값. 센터링 OFF + 인터락 0 일 때만 검사 허용)</span>
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
                  <tr><th>축</th><th className="num">실측 (mm)</th><th className="num">기준 (mm)</th><th className="num">편차</th><th className="num">정상 / 불량 한계</th><th>판정</th></tr>
                </thead>
                <tbody>
                  {AXES.map(([k, label]) => {
                    const v = d[`${k}_mm`], s = d[`standard_${k}_mm`];
                    const diff = v != null && s != null ? v - s : null;
                    const result = d[`${k}_result`];
                    return (
                      <tr key={k}>
                        <th>{label}</th>
                        <td className="num">{v ?? "-"}</td>
                        <td className="num">{s ?? "-"}</td>
                        <td className={`num ${result === "FAIL" ? "ng-text" : ""}`}>
                          {diff != null ? `${diff > 0 ? "+" : ""}${diff.toFixed(2)}` : "-"}
                        </td>
                        <td className="num muted">±{limit(recheck, k)} / ±{limit(tol, k)}</td>
                        <td><StageBadge value={result} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small">
                편차가 정상 한계 이내면 합격, 정상~불량 한계 사이면 재검(다시 스캔), 불량 한계를 넘으면 불합격 (경계값은 좋은 쪽).
                3D 스캔: <span className="mono">{d.scan_file_path || "-"}</span>
              </p>
            </>
          ) : (
            <p className="muted small">아직 치수 측정값이 없습니다.</p>
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

      {insp.alarms.length > 0 && (
        <section className="card">
          <h3>안전 알람 <span className="muted small">{insp.active_alarms}건 발생 중</span></h3>
          <table className="table">
            <thead>
              <tr><th>발생 시각</th><th>종류</th><th>상태</th><th>센터링</th><th>인터락</th><th>검사 단계</th><th>내용</th><th>해제 시각</th></tr>
            </thead>
            <tbody>
              {insp.alarms.map((a) => (
                <tr key={a.id}>
                  <td className="mono small">{fmtTime(a.occurred_at)}</td>
                  <td>{ALARM_TYPE_LABEL[a.alarm_type] ?? a.alarm_type}</td>
                  <td><AlarmBadge value={a.alarm_status} /></td>
                  <td><SafetyBadge kind="centering" value={a.centering_state} /></td>
                  <td><SafetyBadge kind="interlock" value={a.interlock_state} /></td>
                  <td>{STAGE_NAME[a.inspection_stage] ?? a.inspection_stage}</td>
                  <td className="small">{a.alarm_message || "-"}</td>
                  <td className="mono small muted">{fmtTime(a.cleared_at) || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">해제는 [안전 알람] 화면에서 합니다. 해제해도 검사는 자동으로 다시 시작되지 않습니다.</p>
        </section>
      )}

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

/** 한계값: 축별 dict 면 그 축 값, 숫자면 그대로 (예전 데이터), 없으면 - */
function limit(v, axis) {
  if (v == null) return "-";
  return typeof v === "object" ? v[axis] ?? "-" : v;
}

function BackLink() {
  return <Link to="/inspections">← 검사 조회</Link>;
}
