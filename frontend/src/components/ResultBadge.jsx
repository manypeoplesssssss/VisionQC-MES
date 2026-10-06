/**
 * 판정 배지 (components/ResultBadge.jsx)
 * 색이 안 보이는 사람도 알 수 있게 항상 글자를 같이 쓴다.
 *   <FinalBadge value="PROCESS_DEFECT" />  → 공정 불량 (빨강)
 *   <StageBadge value="PASS" />             → 합격 (초록) / 불합격 (빨강) / 대기 (노랑)
 *   <YoloBadge value="IN_PROGRESS" />       → 진행 중
 */
import { FINAL_RESULTS, STAGE_LABEL, YOLO_LABEL } from "../api/client.js";

/** 최종 결과 6가지 */
export function FinalBadge({ value }) {
  const f = FINAL_RESULTS.find((x) => x.code === value);
  if (!f) return <span className="badge none">-</span>;
  return <span className={`badge ${f.tone}`}>{f.label}</span>;
}

/** 치수 · PatchCore 단계 판정 */
const STAGE_TONE = { PASS: "ok", FAIL: "ng", PENDING: "wip" };
export function StageBadge({ value }) {
  if (!value) return <span className="badge none">-</span>;
  return <span className={`badge ${STAGE_TONE[value] || ""}`}>{STAGE_LABEL[value] ?? value}</span>;
}

/** YOLO 진행 상태 */
const YOLO_TONE = { NOT_STARTED: "none", IN_PROGRESS: "wip", COMPLETED: "ok" };
export function YoloBadge({ value }) {
  return <span className={`badge ${YOLO_TONE[value] || ""}`}>{YOLO_LABEL[value] ?? value ?? "-"}</span>;
}
