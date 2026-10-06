/**
 * 판정 배지 (components/ResultBadge.jsx)
 * 색이 안 보이는 사람도 알 수 있게 항상 글자를 같이 쓴다.
 *   <FinalBadge value="PROCESS_DEFECT" />  → 공정 불량 (빨강)
 *   <StageBadge value="PASS" />             → 합격 (초록) / 불합격 (빨강) / 대기 (노랑)
 *   <YoloBadge value="IN_PROGRESS" />       → 진행 중
 */
import { CENTERING_LABEL, FINAL_RESULTS, INTERLOCK_LABEL, STAGE_LABEL, YOLO_LABEL } from "../api/client.js";

/** 최종 결과 6가지 */
export function FinalBadge({ value }) {
  const f = FINAL_RESULTS.find((x) => x.code === value);
  if (!f) return <span className="badge none">-</span>;
  return <span className={`badge ${f.tone}`}>{f.label}</span>;
}

/** 치수 · PatchCore 단계 판정 */
const STAGE_TONE = { PASS: "ok", RECHECK: "wip", FAIL: "ng", PENDING: "wip" };
export function StageBadge({ value }) {
  if (!value) return <span className="badge none">-</span>;
  return <span className={`badge ${STAGE_TONE[value] || ""}`}>{STAGE_LABEL[value] ?? value}</span>;
}

/** YOLO 진행 상태 */
const YOLO_TONE = { NOT_STARTED: "none", IN_PROGRESS: "wip", COMPLETED: "ok" };
export function YoloBadge({ value }) {
  return <span className={`badge ${YOLO_TONE[value] || ""}`}>{YOLO_LABEL[value] ?? value ?? "-"}</span>;
}

/** 장비 안전 상태: 센터링 OFF / 인터락 0 이면 초록, 이상이면 빨강, 미확인이면 노랑 */
export function SafetyBadge({ kind, value }) {
  const labels = kind === "centering" ? CENTERING_LABEL : INTERLOCK_LABEL;
  const ok = kind === "centering" ? value === "OFF" : value === "0";
  const tone = ok ? "ok" : value === "UNKNOWN" || value == null ? "wip" : "ng";
  return <span className={`badge ${tone}`}>{labels[value] ?? "미확인"}</span>;
}

/** 알람 상태 */
export function AlarmBadge({ value }) {
  return <span className={`badge ${value === "ACTIVE" ? "ng" : "none"}`}>{value === "ACTIVE" ? "발생 중" : "해제됨"}</span>;
}
