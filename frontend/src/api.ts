import { useSyncExternalStore } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

const TEXT: Record<string, string> = {
  "invalid credentials": "Correo o contraseña incorrectos.",
  "email already registered": "Ese correo ya está registrado.",
  "invalid or expired token": "El enlace venció o no es válido.",
  "missing token": "Inicie sesión de nuevo.",
  "invalid token": "La sesión venció. Inicie sesión de nuevo.",
  "payment required": "La suscripción no está al día.",
  "invalid license": "La licencia es inválida o fue revocada.",
  "daily drawdown cannot exceed total drawdown": "El drawdown diario no puede superar el total.",
  "account not found": "No encontramos esa cuenta.",
  "account cannot copy itself": "Una cuenta no puede copiarse a sí misma.",
  "follower already linked": "Esa cuenta ya sigue a otra.",
  "copy link not found": "No encontramos ese vínculo.",
  "invalid chat id": "El chat id de Telegram solo admite números.",
};

let token: string | null = localStorage.getItem("qg_token");
const listeners = new Set<() => void>();

export function getToken() {
  return token;
}

export function setToken(value: string | null) {
  token = value;
  if (value) localStorage.setItem("qg_token", value);
  else localStorage.removeItem("qg_token");
  listeners.forEach((fn) => fn());
}

export function useToken() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    getToken,
  );
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function messageOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return TEXT[detail] ?? detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object" && "msg" in detail[0]) {
      return String((detail[0] as { msg: string }).msg);
    }
  }
  if (status === 402) return TEXT["payment required"];
  if (status === 403) return TEXT["invalid license"];
  return "No se pudo completar la solicitud.";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  const body = await res.json().catch(() => null);
  if (res.status === 401 && token && !path.startsWith("/api/v1/auth/")) setToken(null);
  if (!res.ok) throw new ApiError(res.status, messageOf(body, res.status));
  return body as T;
}

export type License = {
  license_key: string;
  status: string;
  plan_id: string;
  subscription_status: string;
  last_heartbeat_at: string | null;
};

export type Me = { id: string; email: string; telegram_chat_id: string | null; licenses: License[] };

export type Account = {
  id: string;
  account_number: string;
  broker_server: string;
  initial_balance: number;
  balance: number | null;
  equity: number | null;
  last_update: string | null;
  floating_pnl: number | null;
  day_start_equity: number | null;
  open_trades: number | null;
  daily_dd_pct: number | null;
  total_dd_pct: number | null;
  action: "ALLOW" | "BLOCK_NEW" | "FORCE_FLAT" | null;
  level: "NORMAL" | "ALERT" | "KILL" | null;
  max_daily_dd_pct: number | null;
  max_total_dd_pct: number | null;
  max_open_trades: number | null;
};

export type Risk = {
  max_daily_dd_pct: number;
  max_total_dd_pct: number;
  max_open_trades: number;
  risk_per_trade_pct: number;
  news_filter: boolean;
};

export type Strategy = {
  id: string;
  strategy: string;
  symbol: string;
  params: Record<string, number>;
  enabled: boolean;
};

export type Trade = {
  ticket: string;
  symbol: string;
  side: string;
  volume: number;
  open_price: number;
  close_price: number | null;
  pnl: number | null;
  opened_at: string;
  closed_at: string | null;
};

export type CopyLink = {
  id: string;
  enabled: boolean;
  master_account_id: string;
  master_account_number: string;
  follower_account_id: string;
  follower_account_number: string;
};

export type Performance = {
  metrics: {
    trades: number;
    net_pnl: number;
    win_rate: number | null;
    profit_factor: number | null;
    expectancy: number | null;
    avg_win: number | null;
    avg_loss: number | null;
    max_drawdown_pct: number;
  };
  equity_curve: { ts: string; equity: number; balance: number }[];
  trades_total: number;
  trades: Trade[];
};

export const session = {
  me: () => api<Me>("/api/v1/me"),
  accounts: () => api<Account[]>("/api/v1/me/accounts"),
  register: (email: string, password: string) =>
    api<{ access_token: string }>("/api/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    api<{ access_token: string }>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  forgot: (email: string) =>
    api<{ status: string; reset_token?: string }>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  reset: (token: string, password: string) =>
    api<{ status: string }>("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),
  activate: (body: { license_key: string; account_number: string; broker_server: string; initial_balance: number }) =>
    api<{ account_id: string }>("/api/v1/license/activate", { method: "POST", body: JSON.stringify(body) }),
  risk: (id: string) => api<Risk>(`/api/v1/me/accounts/${id}/risk`),
  saveRisk: (id: string, body: Risk) =>
    api<Risk>(`/api/v1/me/accounts/${id}/risk`, { method: "PUT", body: JSON.stringify(body) }),
  strategies: (id: string) => api<Strategy[]>(`/api/v1/me/accounts/${id}/strategies`),
  createStrategy: (id: string, body: { strategy: string; symbol: string; params: Record<string, number> }) =>
    api<Strategy>(`/api/v1/me/accounts/${id}/strategies`, { method: "POST", body: JSON.stringify(body) }),
  patchStrategy: (accountId: string, strategyId: string, body: { enabled?: boolean; params?: Record<string, number> }) =>
    api<Strategy>(`/api/v1/me/accounts/${accountId}/strategies/${strategyId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  performance: (id: string, limit: number, offset: number) =>
    api<Performance>(`/api/v1/analytics/performance?account_id=${id}&limit=${limit}&offset=${offset}`),
  copies: () => api<CopyLink[]>("/api/v1/me/copies"),
  createCopy: (master_account_id: string, follower_account_id: string) =>
    api<CopyLink>("/api/v1/me/copies", { method: "POST", body: JSON.stringify({ master_account_id, follower_account_id }) }),
  deleteCopy: (id: string) => api<null>(`/api/v1/me/copies/${id}`, { method: "DELETE" }),
  saveTelegram: (chat_id: string) =>
    api<{ telegram_chat_id: string | null }>("/api/v1/me/telegram", {
      method: "PUT",
      body: JSON.stringify({ chat_id: chat_id.trim() || null }),
    }),
};

export function money(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}

export function pct(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(2)}%`;
}

export function when(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}
