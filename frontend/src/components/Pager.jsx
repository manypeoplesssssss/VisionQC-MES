/**
 * 페이지 이동 버튼 (components/Pager.jsx)   [기능 F12 · 담당 D]
 * page: 현재 페이지(1부터), total: 전체 건수, size: 한 페이지 건수, onChange(새페이지)
 */
export default function Pager({ page, total, size, onChange }) {
  const pages = Math.max(1, Math.ceil(total / size)); // 데이터가 없어도 1페이지로 표시
  return (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onChange(1)}>처음</button>
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>이전</button>
      <span className="num">{page} / {pages}</span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)}>다음</button>
      <button disabled={page >= pages} onClick={() => onChange(pages)}>끝</button>
    </div>
  );
}
