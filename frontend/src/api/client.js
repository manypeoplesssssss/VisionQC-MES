/**
 * API 호출 모음 (api/client.js)   [기능 F00 · 담당 A, 기능별 구역은 각 담당]
 *
 * 화면(pages)에서는 fetch 를 직접 쓰지 않고 항상 여기 있는 api.xxx() 를 부른다.
 * - 로그인 토큰을 자동으로 헤더에 붙임
 * - 401(로그인 만료) 이면 토큰을 지우고 로그인 화면으로 보냄
 * - 서버 에러 메시지(detail)를 읽기 좋은 문장으로 바꿔서 throw
 *
 * 개발 중에는 vite.config.js 의 proxy 가 /api 요청을 FastAPI(8000)로 넘겨준다.
 */

// 브라우저 localStorage 에 토큰을 저장하는 키 이름
const TOKEN_KEY = "vqc_token";

/** 로그인 토큰 저장소 (새로고침해도 로그인 유지) */
export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** 경로 + 쿼리 파라미터 → URL. 값이 비어 있는 파라미터는 빼고 붙인다 */
function buildUrl(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  return url;
}

/** FastAPI 에러(detail)는 문자열일 수도, 검증 오류 배열일 수도 있어서 사람이 읽을 문장으로 맞춘다 */
function errorMessage(detail, status) {
  if (!detail) return `요청 실패 (${status})`;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
  return JSON.stringify(detail);
}

/**
 * 공통 요청 함수
 * @param path   "/api/..." 경로
 * @param method GET / POST / PUT / PATCH / DELETE
 * @param body   JSON 으로 보낼 객체
 * @param params 쿼리스트링 객체
 * @param raw    true 면 Response 를 그대로 돌려줌 (파일 다운로드용)
 */
async function request(path, { method = "GET", body, params, raw = false } = {}) {
  const headers = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";

  const res = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  // 로그인 만료/무효 → 로그인 화면으로 (로그인 요청 자체의 401 은 '비밀번호 틀림' 이라 제외)
  if (res.status === 401 && !path.includes("/auth/login")) {
    tokenStore.clear();
    window.location.href = "/login";
    throw new Error("로그인이 필요합니다");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(errorMessage(err.detail, res.status));
  }
  if (raw) return res;
  return res.status === 204 ? null : res.json(); // 204(내용 없음)는 null
}

/** 인증 헤더가 필요한 파일 다운로드 (CSV) - <a href> 로는 헤더를 못 보내서 fetch 후 저장 */
async function download(path, params, fallbackName) {
  const res = await request(path, { params, raw: true });
  // 서버가 정해준 파일명 (Content-Disposition: attachment; filename="...")
  const cd = res.headers.get("Content-Disposition") || "";
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] || fallbackName;
  const blob = await res.blob();
  // 임시 링크를 만들어 클릭 → 브라우저 다운로드
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** 공정 코드와 화면 표시 이름 (백엔드 Process enum 과 같은 순서) */
export const PROCESSES = [
  { code: "DIM3D", label: "3D 치수검사", short: "3D" },
  { code: "PATCHCORE", label: "1차 PatchCore", short: "PC" },
  { code: "YOLO", label: "2차 YOLO", short: "YOLO" },
];
export const processLabel = (code) => PROCESSES.find((p) => p.code === code)?.label ?? code;

/** 제품 상태 표시 이름 */
export const STATUS_LABEL = { OK: "양품", NG: "불량", IN_PROGRESS: "진행중" };

export const todayStr = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD (로컬)
export const fmtTime = (iso) => iso?.replace("T", " ").slice(0, 19) ?? ""; // "2026-10-05T14:03:11" → "2026-10-05 14:03:11"

/** 백엔드 API 목록. 주소와 파라미터는 backend/app/routers/*.py 와 1:1 로 대응 */
export const api = {
  // 인증 (F03·F04, A)
  login: (username, password) => request("/api/auth/login", { method: "POST", body: { username, password } }),
  me: () => request("/api/auth/me"),
  changePassword: (current_password, new_password) =>
    request("/api/auth/password", { method: "PUT", body: { current_password, new_password } }),

  // 대시보드 (F10·F11, C)
  summary: (date) => request("/api/dashboard/summary", { params: { date } }),
  hourly: (date) => request("/api/dashboard/hourly", { params: { date } }),
  daily: (date_from, date_to) => request("/api/dashboard/daily", { params: { date_from, date_to } }),

  // 검사 조회·CSV (F12·F13·F14, D)
  inspections: (params) => request("/api/inspections", { params }),
  inspection: (id) => request(`/api/inspections/${id}`),
  deleteInspection: (id) => request(`/api/inspections/${id}`, { method: "DELETE" }),
  exportCsv: (params) => download("/api/inspections/export", params, "inspections.csv"),
  items: () => request("/api/items"),

  // 제품 (F09 API=C, F15 화면=D)
  products: (params) => request("/api/products", { params }),
  history: (serial) => request(`/api/products/${encodeURIComponent(serial)}/history`),

  // 규격 (F07, B)
  specs: () => request("/api/specs"),
  saveSpec: (item, spec) => request(`/api/specs/${encodeURIComponent(item)}`, { method: "PUT", body: spec }),
  deleteSpec: (item) => request(`/api/specs/${encodeURIComponent(item)}`, { method: "DELETE" }),

  // 사용자 (F04, A)
  users: () => request("/api/users"),
  createUser: (body) => request("/api/users", { method: "POST", body }),
  updateUser: (id, body) => request(`/api/users/${id}`, { method: "PATCH", body }),
};
