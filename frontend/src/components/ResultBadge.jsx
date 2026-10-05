/**
 * 판정 배지 (components/ResultBadge.jsx)   [기능 F12 · 담당 D]
 * OK(초록) / NG(빨강) / 진행중(노랑). 색이 안 보이는 사람도 알 수 있게 항상 글자를 같이 쓴다.
 *   <ResultBadge value="NG" />              → NG
 *   <ResultBadge value="OK" long />         → 양품
 *   <ResultBadge value={undefined} />       → - (아직 검사 안 함)
 */
import { STATUS_LABEL } from "../api/client.js";

// 값 → CSS 클래스 (styles.css 의 .badge.ok / .ng / .wip)
const CLS = { OK: "ok", NG: "ng", IN_PROGRESS: "wip" };

/** OK / NG / IN_PROGRESS 표시. 색만이 아니라 글자로도 구분되게 */
export default function ResultBadge({ value, long = false }) {
  if (!value) return <span className="badge none">-</span>;
  return <span className={`badge ${CLS[value] || ""}`}>{long ? STATUS_LABEL[value] : value === "IN_PROGRESS" ? "진행중" : value}</span>;
}
