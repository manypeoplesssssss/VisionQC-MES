/**
 * 차트 컴포넌트 (components/Charts.jsx)   [기능 F11 · 담당 C]
 * 차트 라이브러리(Recharts 등)를 쓰지 않고 SVG 로 직접 그린다 → 설치할 패키지가 없고 가볍다.
 *   StackedBars : 누적 막대 (시간대별/일별 OK·NG)
 *   HBars       : 가로 막대 (불량 유형 순위)
 * 색은 styles.css 의 --series-ok(파랑) / --series-ng(빨강) 변수를 쓴다.
 */
import { useState } from "react";

/**
 * 누적 막대 차트 (라이브러리 없이 SVG)
 * data:   [{ label: "09", values: [ok, ng] }, ...]
 * series: [{ name: "양품", cls: "s-ok" }, { name: "불량", cls: "s-ng" }]   (아래부터 쌓임)
 * 막대 위에 마우스를 올리면 툴팁, 범례는 항상 표시 (색만으로 구분하지 않게)
 */
export function StackedBars({ data, series, tickEvery = 1, height = 180, unit = "건" }) {
  const [hover, setHover] = useState(null); // 마우스가 올라간 막대 번호 (없으면 null)
  // SVG 내부 좌표계: 가로 600, 세로 height. 화면 크기에 맞춰 자동으로 늘어난다 (viewBox)
  const W = 600, H = height, padL = 32, padB = 22, padT = 8; // padL: y축 숫자 자리, padB: x축 글자 자리
  const plotH = H - padB - padT;                              // 막대가 그려지는 높이
  const totals = data.map((d) => d.values.reduce((a, b) => a + b, 0));
  const max = niceMax(Math.max(1, ...totals));                // y축 최대값을 50, 100 같은 깔끔한 수로
  const bw = (W - padL) / Math.max(1, data.length);           // 막대 1칸 너비
  const y = (v) => padT + plotH - (v / max) * plotH;          // 값 → SVG y 좌표 (위가 0 이라 뒤집음)
  const ticks = [0, max / 2, max];                            // 가로 눈금선 3개

  return (
    <div className="chart">
      <div className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i className={`swatch ${s.cls}`} />
            {s.name}
          </span>
        ))}
      </div>
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={series.map((s) => s.name).join(", ")}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={padL} x2={W} y1={y(t)} y2={y(t)} />
              <text className="axis" x={padL - 6} y={y(t) + 4} textAnchor="end">{t}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = padL + i * bw;                            // 이 칸의 왼쪽 x
            const w = Math.max(2, bw - Math.min(8, bw * 0.3));  // 실제 막대 너비 (칸보다 조금 좁게 → 막대 사이 여백)
            // 값들을 아래부터 차곡차곡 쌓으면서 각 조각의 위치/높이 계산 (0인 조각은 그리지 않음)
            let acc = 0;
            const segs = d.values.map((v, si) => {
              const y0 = y(acc), y1 = y(acc + v);
              acc += v;
              return { v, si, y: y1, h: y0 - y1 };
            }).filter((s) => s.v > 0);
            return (
              <g key={d.label}>
                {segs.map((s, k) => {
                  const top = k === segs.length - 1; // 맨 위 조각만 모서리를 둥글게
                  const gap = k > 0 ? 2 : 0; // 쌓인 막대 사이 2px 간격
                  return (
                    <path
                      key={s.si}
                      className={`bar ${series[s.si].cls}`}
                      d={barPath(x + (bw - w) / 2, s.y, w, Math.max(0, s.h - gap), top ? Math.min(4, w / 2) : 0)}
                    />
                  );
                })}
                {i % tickEvery === 0 && (
                  <text className="axis" x={x + bw / 2} y={H - 6} textAnchor="middle">{d.label}</text>
                )}
                {/* 막대보다 넓은 투명 사각형 → 가는 막대도 마우스로 쉽게 가리킬 수 있게 */}
                <rect
                  className="hit"
                  x={x}
                  y={padT}
                  width={bw}
                  height={plotH}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
        {/* 툴팁: 가리킨 칸의 가운데에 위치 (SVG 좌표를 % 로 바꿔서 HTML 위에 띄움) */}
        {hover !== null && (
          <div className="tooltip" style={{ left: `${((padL + (hover + 0.5) * bw) / W) * 100}%` }}>
            <b>{data[hover].label}</b>
            {series.map((s, si) => (
              <div key={s.name}>
                <i className={`swatch ${s.cls}`} /> {s.name} <span className="num">{data[hover].values[si]}{unit}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** 가로 막대 (불량 유형 순위 등 단일 시리즈) */
export function HBars({ data, empty = "데이터 없음" }) {
  if (!data.length) return <p className="muted small">{empty}</p>;
  const max = Math.max(...data.map((d) => d.value)); // 가장 큰 값 = 막대 100%
  return (
    <div className="hbars">
      {data.map((d) => (
        <div key={d.label} className="hbar-row" title={`${d.label}: ${d.value}`}>
          <span className="hbar-label">{d.label}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${(d.value / max) * 100}%` }} />
          </span>
          <span className="num">{d.value}</span>
        </div>
      ))}
    </div>
  );
}

// 위쪽 모서리만 둥근 막대 (SVG path 명령: M 이동, V 세로선, Q 곡선, H 가로선, Z 닫기)
function barPath(x, y, w, h, r) {
  if (h <= 0) return "";
  r = Math.min(r, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

// y축 최대값을 보기 좋은 수로 올림: 37 → 50, 120 → 200, 7 → 10
function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return Math.max(2, m * p);
  return v;
}
