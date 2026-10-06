/**
 * 검사 사진 크게 보기 모달 (components/ImageViewer.jsx)
 *
 *   image   : 보여줄 사진 1장 { capture_number, original_url, annotated_url, ... } (null 이면 닫힌 상태)
 *   defects : 그 사진에서 나온 결함들 (box: [x1,y1,x2,y2] 원본 사진 픽셀 기준)
 *   title   : 위쪽에 보일 제목 (검사번호 등)
 *   onClose : 닫기
 *
 * "원본" 으로 보면 결함 박스(box)를 원본 사진 위에 SVG 로 겹쳐 그린다.
 * SVG 좌표계(viewBox)를 원본 가로x세로로 맞추면, 화면에서 사진이 줄어들어도 박스가 정확히 따라간다.
 * "표시 사진" 은 검사 PC 가 이미 상자를 그려서 보낸 사진이라 그대로 보여준다.
 */
import { useEffect, useState } from "react";

export default function ImageViewer({ image, defects = [], title, onClose }) {
  const [mode, setMode] = useState("annotated"); // annotated: 표시 사진 / original: 원본 + 박스
  const [size, setSize] = useState(null);        // 원본 사진 크기 (박스 좌표 기준)
  const [imgError, setImgError] = useState(false);

  // 다른 사진을 열면 상태 초기화 (표시 사진이 없으면 원본으로)
  useEffect(() => {
    setMode(image?.annotated_url ? "annotated" : "original");
    setSize(null);
    setImgError(false);
  }, [image]);

  // ESC 키로 닫기
  useEffect(() => {
    if (!image) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [image, onClose]);

  if (!image) return null;
  const src = mode === "annotated" && image.annotated_url ? image.annotated_url : image.original_url;
  const boxes = mode === "original" ? defects.filter((d) => Array.isArray(d.box)) : [];

  return (
    // 바깥 어두운 배경을 클릭하면 닫힘. 안쪽 클릭은 stopPropagation 으로 배경까지 전달되지 않게
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div>
            <div className="mono">{title} · 사진 {image.capture_number}</div>
            <div className="muted small mono">{image.original_path}</div>
          </div>
          <div className="row-gap">
            {image.annotated_url && (
              <div className="seg">
                <button className={mode === "annotated" ? "active" : ""} onClick={() => setMode("annotated")}>표시 사진</button>
                <button className={mode === "original" ? "active" : ""} onClick={() => setMode("original")}>원본 + 박스</button>
              </div>
            )}
            <a className="ghost btn" href={src} target="_blank" rel="noreferrer">새 창</a>
            <button className="ghost" onClick={onClose}>닫기</button>
          </div>
        </div>
        <div className="modal-body single">
          <div className="img-wrap">
            {imgError ? (
              <div className="img-missing">사진을 불러올 수 없습니다</div>
            ) : (
              <img
                src={src}
                alt={image.original_path}
                // 사진이 다 불러와지면 원본 크기를 기억 → 박스 좌표계로 사용
                onLoad={(e) => setSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
                onError={() => setImgError(true)}
              />
            )}
            {size && boxes.length > 0 && (
              <svg className="overlay" viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none">
                {boxes.map((d) => {
                  const [x1, y1, x2, y2] = d.box;
                  const fs = Math.max(12, size.w / 40); // 글자 크기를 사진 크기에 비례하게
                  return (
                    <g key={d.index}>
                      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} strokeWidth={Math.max(2, size.w / 300)} />
                      {/* 라벨은 박스 위에, 위쪽 공간이 없으면 박스 아래에 */}
                      <text x={x1} y={y1 > fs + 4 ? y1 - 4 : y2 + fs} fontSize={fs}>
                        {d.defect_class} {(d.confidence * 100).toFixed(0)}%
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
