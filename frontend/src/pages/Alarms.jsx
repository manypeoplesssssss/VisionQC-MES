/**
 * 안전 알람 (pages/Alarms.jsx) - 센터링 · 인터락 알람 발생 / 해제 이력
 *
 * 검사 허용 조건은 센터링 OFF(정위치) AND 인터락 0(정상). 이상이면 검사 프로그램이 장비를 멈추고
 * 검사를 보류하며 알람을 남긴다. 관리자는 현장 확인 후 [해제]를 누른다 (해제만으로 검사가 다시 시작되지는 않음).
 * 필터는 주소창 쿼리스트링에 둔다 (예: /alarms?status=ACTIVE).
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ALARM_TYPE_LABEL, api, fmtTime, isAdmin, STAGE_NAME } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import Pager from "../components/Pager.jsx";
import { AlarmBadge, SafetyBadge } from "../components/ResultBadge.jsx";

const SIZE = 30;
const TABS = [
  { code: "ACTIVE", label: "발생 중" },
  { code: "", label: "전체" },
  { code: "CLEARED", label: "해제됨" },
];

export default function Alarms() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "ACTIVE";
  const alarmType = params.get("alarm_type") || "";
  const dateFrom = params.get("date_from") || "";
  const dateTo = params.get("date_to") || "";
  const page = Number(params.get("page") || 1);
  const [data, setData] = useState({ total: 0, items: [] });
  const [error, setError] = useState("");

  const update = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v !== undefined && v !== null ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page");
    setParams(next);
  };

  const load = useCallback(() => {
    api
      .alarms({ status, alarm_type: alarmType, date_from: dateFrom, date_to: dateTo, page, size: SIZE })
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message));
  }, [status, alarmType, dateFrom, dateTo, page]);
  useEffect(load, [load]);

  const clear = async (a) => {
    if (!confirm(`알람 #${a.id} 을(를) 해제할까요?\n현장에서 원인을 확인했는지 확인하세요. 해제해도 검사는 자동으로 다시 시작되지 않습니다.`)) return;
    try {
      await api.clearAlarm(a.id);
      load();
    } catch (e) {
      alert(e.message);
    }
  };

  return (
    <>
      <div className="page-head"><h2>안전 알람</h2></div>
      <p className="muted small">
        검사는 <b>센터링 OFF(정위치)</b> 이고 <b>인터락 0(정상)</b> 일 때만 진행됩니다. 위치 이상, 인터락 비정상, 미확인(센서 응답 끊김 포함)이면
        검사 프로그램이 장비를 멈추고 검사를 보류하며 여기에 기록합니다. 해제는 기록용이고 검사를 다시 시작하지는 않습니다.
      </p>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.code || "all"} className={t.code === status ? "active" : ""} onClick={() => update({ status: t.code })}>{t.label}</button>
        ))}
      </div>
      <div className="filters">
        <input type="date" value={dateFrom} onChange={(e) => update({ date_from: e.target.value || null })} />
        <span className="muted">~</span>
        <input type="date" value={dateTo} onChange={(e) => update({ date_to: e.target.value || null })} />
        <select value={alarmType} onChange={(e) => update({ alarm_type: e.target.value || null })}>
          <option value="">전체 종류</option>
          <option value="CENTERING">센터링</option>
          <option value="INTERLOCK">인터락</option>
        </select>
        <span className="muted small">총 {data.total.toLocaleString()}건</span>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr><th>발생 시각</th><th>종류</th><th>상태</th><th>센터링</th><th>인터락</th><th>검사 단계</th><th>검사번호</th><th>내용</th><th>해제 시각</th>{admin && <th />}</tr>
          </thead>
          <tbody>
            {data.items.map((a) => (
              <tr key={a.id}>
                <td className="mono small">{fmtTime(a.occurred_at)}</td>
                <td><b>{ALARM_TYPE_LABEL[a.alarm_type] ?? a.alarm_type}</b></td>
                <td><AlarmBadge value={a.alarm_status} /></td>
                <td><SafetyBadge kind="centering" value={a.centering_state} /></td>
                <td><SafetyBadge kind="interlock" value={a.interlock_state} /></td>
                <td>{STAGE_NAME[a.inspection_stage] ?? a.inspection_stage}</td>
                <td className="mono small">
                  {a.inspection_id ? <Link to={`/inspections/${encodeURIComponent(a.inspection_id)}`}>{a.inspection_id}</Link> : <span className="muted">시작 전</span>}
                </td>
                <td className="small">{a.alarm_message || "-"}</td>
                <td className="mono small muted">{fmtTime(a.cleared_at) || "-"}</td>
                {admin && <td>{a.alarm_status === "ACTIVE" && <button className="ghost" onClick={() => clear(a)}>해제</button>}</td>}
              </tr>
            ))}
            {data.items.length === 0 && <tr><td colSpan={10} className="center muted">알람이 없습니다.</td></tr>}
          </tbody>
        </table>
        <Pager page={page} total={data.total} size={SIZE} onChange={(p) => update({ page: String(p) })} />
      </div>
    </>
  );
}
