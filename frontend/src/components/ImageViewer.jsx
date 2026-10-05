/**
 * 검사 이미지 상세 모달 (components/ImageViewer.jsx)   [기능 F13 · 담당 D]
 *
 * 대시보드·공정별 조회·제품 이력에서 공통으로 쓴다.
 *   inspection : 보여줄 검사 1건 (null 이면 닫힌 상태 → 아무것도 안 그림)
 *   onClose    : 닫기
 *   onDeleted  : 관리자가 삭제했을 때 목록을 새로고침하라고 부모에게 알림
 *
 * 결함 박스(box: [x1,y1,x2,y2])는 '원본 이미지 픽셀' 기준이라,
 * 이미지 위에 같은 크기 좌표계(viewBox=원본 가로x세로)의 SVG 를 겹쳐서 그린다.
 * 그러면 화면에서 이미지가 줄어들어도 박스가 정확히 따라간다.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtTime, processLabel } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import ResultBadge from "./ResultBadge.jsx";

/** 검사 이미지 + 결함 박스 오버레이 + 상세 데이터 모달 */
export default function ImageViewer({ inspection, onClose, onDeleted }) {
  const { user } = useAuth();
  const [size, setSize] = useState(null); // 원본 이미지 크기 (박스 좌표 기준)
  const [showBoxes, setShowBoxes] = useState(true);  // 결함 박스 표시 on/off
  const [imgError, setImgError] = useState(false);   // 이미지 파일이 없거나 주소 만료

  // 다른 검사를 열면 이전 이미지 크기/에러 상태를 초기화
  useEffect(() => {
    setSize(null);
    setImgError(false);
  }, [inspection?.id]);

  // ESC 키로 닫기
  useEffect(() => {
    if (!inspection) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inspection, onClose]);

  if (!inspection) return null;
  const { dimension, defects = [] } = inspection;
  const found = defects.filter((d) => d.defect_detected);    // 실제 결함만
  const boxes = found.filter((d) => Array.isArray(d.box));   // 그 중 위치(box)가 있는 것 (PatchCore 는 없을 수도)

  /** 관리자 삭제 (DB 행 + 이미지 파일) */
  const remove = async () => {
    if (!confirm(`${inspection.image_filename}\n이 검사 데이터와 이미지를 삭제할까요?`)) return;
    try {
      await api.deleteInspection(inspection.id);
      onDeleted?.(inspection.id);
      onClose();
    } catch (e) {
      alert(e.message);
    }
  };

  return (
    // 바깥 어두운 배경을 클릭하면 닫힘. 안쪽 클릭은 stopPropagation 으로 배경까지 전달되지 않게
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div>
            <div className="mono">{inspection.image_filename}</div>
            <div className="muted small">
              {processLabel(inspection.process)} · {fmtTime(inspection.inspected_at)}
              {inspection.model_version && ` · 모델 ${inspection.model_version}`}
            </div>
          </div>
          <div className="row-gap">
            {boxes.length > 0 && (
              <label className="small check">
                <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} /> 결함 박스
              </label>
            )}
            <a className="ghost btn" href={inspection.image_url} target="_blank" rel="noreferrer">원본</a>
            <button className="ghost" onClick={onClose}>닫기</button>
          </div>
        </div>

        <div className="modal-body">
          <div className="img-wrap">
            {imgError ? (
              <div className="img-missing">이미지를 불러올 수 없습니다</div>
            ) : (
              <img
                src={inspection.image_url}
                alt={inspection.image_filename}
                // 이미지가 다 불러와지면 원본 크기를 기억 → 박스 좌표계로 사용
                onLoad={(e) => setSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
                onError={() => setImgError(true)}
              />
            )}
            {size && showBoxes && boxes.length > 0 && (
              <svg className="overlay" viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none">
                {boxes.map((d) => {
                  const [x1, y1, x2, y2] = d.box;
                  const fs = Math.max(12, size.w / 40); // 글자 크기를 이미지 크기에 비례하게
                  return (
                    <g key={d.id}>
                      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} strokeWidth={Math.max(2, size.w / 300)} />
                      {/* 라벨은 박스 위에, 위쪽 공간이 없으면 박스 아래에 */}
                      <text x={x1} y={y1 > fs + 4 ? y1 - 4 : y2 + fs} fontSize={fs}>
                        {d.type} {d.confidence != null && `${(d.confidence * 100).toFixed(0)}%`}
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}
          </div>

          <div className="detail">
            <dl>
              <dt>판정</dt>
              <dd><ResultBadge value={inspection.result} /></dd>
              <dt>시리얼</dt>
              <dd>
                <Link to={`/products/${encodeURIComponent(inspection.serial_no)}`} onClick={onClose}>
                  {inspection.serial_no}
                </Link>
              </dd>
              <dt>품목</dt>
              <dd>{inspection.item}</dd>
              <dt>공정</dt>
              <dd>{processLabel(inspection.process)}</dd>
            </dl>

            {dimension && (
              <>
                <h4>치수 데이터</h4>
                <table className="mini">
                  <tbody>
                    <tr><th>width_mm</th><td className="num">{dimension.width_mm}</td></tr>
                    <tr><th>length_mm</th><td className="num">{dimension.length_mm}</td></tr>
                    <tr><th>height_mm</th><td className="num">{dimension.height_mm}</td></tr>
                    <tr><th>status</th><td><ResultBadge value={dimension.status} /></td></tr>
                    {/* 검사 PC 판정과 서버(규격) 판정이 다를 때만 표시 */}
                    {dimension.reported_status && dimension.reported_status !== dimension.status && (
                      <tr><th>검사PC 판정</th><td><ResultBadge value={dimension.reported_status} /> <span className="muted small">(규격 기준 재판정됨)</span></td></tr>
                    )}
                  </tbody>
                </table>
              </>
            )}

            {inspection.process !== "DIM3D" && (
              <>
                <h4>결함 데이터</h4>
                {found.length === 0 ? (
                  <p className="muted small">검출된 결함 없음</p>
                ) : (
                  <table className="mini">
                    <thead>
                      <tr><th>type</th><th>confidence</th><th>box</th></tr>
                    </thead>
                    <tbody>
                      {found.map((d) => (
                        <tr key={d.id}>
                          <td>{d.type || "-"}</td>
                          <td className="num">{d.confidence?.toFixed(3) ?? "-"}</td>
                          <td className="mono small">{d.box ? `[${d.box.map((v) => Math.round(v)).join(", ")}]` : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}

            {/* 삭제 버튼은 관리자에게만 (백엔드도 관리자만 허용) */}
            {user?.role === "ADMIN" && (
              <button className="danger small-btn" onClick={remove}>검사 데이터 삭제</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
