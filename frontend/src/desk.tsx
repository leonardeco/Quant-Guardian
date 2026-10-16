import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Account, ApiError, Me, Performance, Risk, Strategy,
  money, pct, session, setToken, when,
} from "./api";

type Ctx = {
  me: Me | null;
  accounts: Account[];
  account: Account | null;
  reload: () => Promise<void>;
};

export function useDesk() {
  return useOutletContext<Ctx>();
}

const NAV = [
  { to: "/", label: "Resumen", end: true },
  { to: "/cuentas", label: "Cuentas" },
  { to: "/riesgo", label: "Riesgo" },
  { to: "/estrategias", label: "Estrategias" },
  { to: "/operaciones", label: "Operaciones" },
  { to: "/copias", label: "Copias" },
];

const LEVEL = {
  NORMAL: { label: "Normal", hint: "La cuenta opera dentro de los límites.", dot: "bg-lime" },
  ALERT: { label: "Alerta", hint: "El drawdown llegó al 80% de un límite.", dot: "bg-warn" },
  KILL: { label: "Kill-switch", hint: "La terminal debe cerrar las posiciones de este asesor.", dot: "bg-danger lamp-kill" },
} as const;

const ACTION: Record<string, string> = {
  ALLOW: "Puede abrir operaciones.",
  BLOCK_NEW: "No puede abrir operaciones nuevas.",
  FORCE_FLAT: "Cierre forzado activo.",
};

export function Desk() {
  const [me, setMe] = useState<Me | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [id, setId] = useState(() => localStorage.getItem("qg_account") ?? "");
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      const [who, rows] = await Promise.all([session.me(), session.accounts()]);
      setMe(who);
      setAccounts(rows);
      setId((cur) => (rows.some((a) => a.id === cur) ? cur : rows[0]?.id ?? ""));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No hay conexión con el servidor.");
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { if (id) localStorage.setItem("qg_account", id); }, [id]);

  const account = accounts.find((a) => a.id === id) ?? null;

  return (
    <div className="min-h-full md:grid md:grid-cols-[232px_1fr]">
      <aside className="flex flex-col border-b border-line bg-[#171c15] md:min-h-full md:border-b-0 md:border-r">
        <div className="flex items-center gap-3 px-5 py-5">
          <span className="grid h-8 w-8 place-items-center rounded-sm bg-lime text-xs font-semibold text-ink">QG</span>
          <div>
            <p className="leading-none">Quant Guardian</p>
            <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-mute">Portal</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:px-3">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-ink text-lime" : "text-mute hover:text-paper"}`}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden px-5 py-5 md:block">
          <p className="truncate text-sm">{me?.email}</p>
          <button className="mt-2 text-sm text-mute underline decoration-line underline-offset-4" onClick={() => setToken(null)}>
            Cerrar sesión
          </button>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between gap-4 border-b border-line px-5 py-4 md:px-8">
          <label className="min-w-0 flex-1">
            <span className="label">Cuenta</span>
            <select className="field max-w-md" value={id} onChange={(e) => setId(e.target.value)}>
              {accounts.length === 0 && <option value="">Sin cuentas vinculadas</option>}
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.account_number} · {a.broker_server}</option>
              ))}
            </select>
          </label>
          <button className="btn btn-ghost md:hidden" onClick={() => setToken(null)}>Salir</button>
        </header>
        {error && <p className="mx-5 mt-4 text-sm text-danger md:mx-8">{error}</p>}
        <div className="px-5 py-6 md:px-8">
          <Outlet context={{ me, accounts, account, reload } satisfies Ctx} />
        </div>
      </div>
    </div>
  );
}

function NeedAccount({ children }: { children: (account: Account) => ReactNode }) {
  const { account } = useDesk();
  if (!account) {
    return <p className="text-mute">Vincule una terminal en Cuentas para ver esta sección.</p>;
  }
  return children(account);
}

export function Overview() {
  const { account, reload } = useDesk();
  const [perf, setPerf] = useState<Performance | null>(null);

  useEffect(() => {
    const tick = setInterval(() => { void reload(); }, 5000);
    return () => clearInterval(tick);
  }, [reload]);

  useEffect(() => {
    if (!account) { setPerf(null); return; }
    let live = true;
    session.performance(account.id, 1, 0).then((p) => { if (live) setPerf(p); }).catch(() => { if (live) setPerf(null); });
    return () => { live = false; };
  }, [account]);

  if (!account) return <p className="text-mute">Cuando el asesor active la licencia, el resumen aparece aquí.</p>;

  const level = account.level ? LEVEL[account.level] : null;
  const curve = perf?.equity_curve.map((p) => ({ ...p, label: when(p.ts) })) ?? [];

  return (
    <div className="space-y-5">
      <section className="panel flex flex-col gap-5 sm:flex-row sm:items-center">
        <span className={`h-14 w-14 shrink-0 rounded-full ${level?.dot ?? "bg-line"}`} />
        <div>
          <p className="text-3xl font-medium tracking-tight">{level?.label ?? "Sin telemetría"}</p>
          <p className="mt-1 text-mute">{level?.hint ?? "La terminal todavía no envió un heartbeat."}</p>
          {account.action && <p className="mt-2 text-sm">{ACTION[account.action]}</p>}
        </div>
        <p className="sm:ml-auto text-xs uppercase tracking-[0.16em] text-mute">
          Actualizado {when(account.last_update)}
        </p>
      </section>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Balance" value={money(account.balance)} />
        <Kpi label="Equidad" value={money(account.equity)} />
        <Kpi label="PnL flotante" value={money(account.floating_pnl)} tone={toneOf(account.floating_pnl)} />
        <Kpi label="Drawdown diario" value={`${pct(account.daily_dd_pct)} / ${pct(account.max_daily_dd_pct)}`} tone={ddTone(account.daily_dd_pct)} />
        <Kpi label="Drawdown total" value={`${pct(account.total_dd_pct)} / ${pct(account.max_total_dd_pct)}`} tone={ddTone(account.total_dd_pct)} />
        <Kpi label="Operaciones abiertas" value={`${account.open_trades ?? "—"} / ${account.max_open_trades ?? "—"}`} />
        <Kpi label="Beneficio neto" value={money(perf?.metrics.net_pnl)} tone={toneOf(perf?.metrics.net_pnl)} />
        <Kpi label="Win rate" value={pct(perf?.metrics.win_rate)} />
      </section>
      <section className="panel">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg">Curva de equidad</h2>
          <p className="text-xs text-mute"><span className="text-lime">Equidad</span> · Balance</p>
        </div>
        {curve.length === 0 ? (
          <p className="text-sm text-mute">Aún no hay snapshots. El gráfico se llena con los heartbeats.</p>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curve}>
                <CartesianGrid stroke="#343b2e" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "#909888", fontSize: 11 }} minTickGap={28} />
                <YAxis tick={{ fill: "#909888", fontSize: 11 }} width={72} />
                <Tooltip contentStyle={{ background: "#1c2219", border: "1px solid #343b2e", borderRadius: 8 }} />
                <Line type="monotone" dataKey="equity" name="Equidad" stroke="#d2f25a" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="balance" name="Balance" stroke="#909888" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  const color = tone === "up" ? "text-lime" : tone === "down" ? "text-danger" : "text-paper";
  return (
    <article className="panel">
      <p className="label">{label}</p>
      <p className={`num mt-2 text-2xl ${color}`}>{value}</p>
    </article>
  );
}

function toneOf(n: number | null | undefined): "up" | "down" | undefined {
  if (n == null || n === 0) return undefined;
  return n > 0 ? "up" : "down";
}

function ddTone(n: number | null | undefined): "up" | "down" | undefined {
  if (n == null || n === 0) return undefined;
  return n > 0 ? "down" : "up";
}

const PLAN: Record<string, string> = {
  starter: "Starter", quant_pro: "Quant Pro", institutional: "Institutional",
};
const SUB: Record<string, string> = {
  active: "Activa", trialing: "Prueba", past_due: "Impaga", canceled: "Cancelada",
};

function TelegramForm() {
  const { me, reload } = useDesk();
  const [chat, setChat] = useState(me?.telegram_chat_id ?? "");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setChat(me?.telegram_chat_id ?? ""); }, [me?.telegram_chat_id]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setOk("");
    try {
      await session.saveTelegram(chat);
      setOk("Listo. Las alertas salen al pasar a alerta, al kill-switch y en cada apertura o cierre.");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={onSubmit}>
      <label className="block flex-1">
        <span className="label">Telegram chat id</span>
        <input className="field" inputMode="numeric" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="99887766" />
      </label>
      <button className="btn btn-lime" disabled={busy}>{busy ? "Guardando…" : "Guardar"}</button>
      {error && <p className="text-sm text-danger sm:w-full">{error}</p>}
      {ok && <p className="text-sm text-lime sm:w-full">{ok}</p>}
    </form>
  );
}

export function Accounts() {
  const { me, accounts, reload } = useDesk();
  const [license, setLicense] = useState("");
  const [number, setNumber] = useState("");
  const [server, setServer] = useState("");
  const [balance, setBalance] = useState("100000");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const licenses = me?.licenses ?? [];

  useEffect(() => {
    if (!license && licenses[0]) setLicense(licenses[0].license_key);
  }, [license, licenses]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setOk("");
    try {
      await session.activate({
        license_key: license,
        account_number: number.trim(),
        broker_server: server.trim(),
        initial_balance: Number(balance),
      });
      setNumber("");
      setOk("Terminal vinculada. El asesor puede conectarse con esa misma licencia.");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo vincular la cuenta.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
    <TelegramForm />
    <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <section className="space-y-3">
        <h2 className="text-lg">Licencias</h2>
        {licenses.length === 0 && <p className="text-sm text-mute">Todavía no hay una suscripción asociada a este usuario.</p>}
        {licenses.map((lic) => (
          <article key={lic.license_key} className="panel">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-lg">{PLAN[lic.plan_id] ?? lic.plan_id}</p>
              <p className="text-sm text-mute">{SUB[lic.subscription_status] ?? lic.subscription_status} · {lic.status}</p>
            </div>
            <p className="num mt-3 break-all text-sm text-lime">{lic.license_key}</p>
            <button className="btn btn-ghost mt-3" onClick={() => navigator.clipboard.writeText(lic.license_key)}>Copiar clave</button>
            <p className="mt-3 text-xs text-mute">Último heartbeat {when(lic.last_heartbeat_at)}</p>
          </article>
        ))}
        <h2 className="pt-2 text-lg">Terminales</h2>
        {accounts.length === 0 && <p className="text-sm text-mute">Ninguna cuenta MT5 vinculada.</p>}
        {accounts.map((a) => (
          <article key={a.id} className="panel flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="num text-lg">{a.account_number}</p>
              <p className="text-sm text-mute">{a.broker_server}</p>
            </div>
            <p className="num text-sm">Balance inicial {money(a.initial_balance)}</p>
          </article>
        ))}
      </section>
      <form className="panel h-fit space-y-4" onSubmit={onSubmit}>
        <h2 className="text-lg">Vincular terminal</h2>
        <p className="text-sm text-mute">Use el número de cuenta y el servidor tal como aparecen en MetaTrader. El asesor confirma la misma licencia al iniciar.</p>
        <label className="block"><span className="label">Licencia</span>
          <select className="field" required value={license} onChange={(e) => setLicense(e.target.value)}>
            {licenses.map((l) => <option key={l.license_key} value={l.license_key}>{PLAN[l.plan_id] ?? l.plan_id}</option>)}
          </select>
        </label>
        <label className="block"><span className="label">Número de cuenta</span>
          <input className="field" required value={number} onChange={(e) => setNumber(e.target.value)} /></label>
        <label className="block"><span className="label">Servidor</span>
          <input className="field" required value={server} onChange={(e) => setServer(e.target.value)} placeholder="Broker-Demo" /></label>
        <label className="block"><span className="label">Balance inicial</span>
          <input className="field" required type="number" min="0" step="0.01" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
        <button className="btn btn-lime" disabled={busy || licenses.length === 0}>{busy ? "Vinculando…" : "Vincular"}</button>
        {error && <p className="text-sm text-danger">{error}</p>}
        {ok && <p className="text-sm text-lime">{ok}</p>}
      </form>
    </div>
    </div>
  );
}

export function RiskPage() {
  return (
    <NeedAccount>
      {(account) => <RiskForm accountId={account.id} />}
    </NeedAccount>
  );
}

function RiskForm({ accountId }: { accountId: string }) {
  const { reload } = useDesk();
  const [form, setForm] = useState<Risk | null>(null);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    session.risk(accountId).then((r) => { if (live) setForm(r); }).catch((err) => {
      if (live) setError(err instanceof ApiError ? err.message : "No se pudo leer el perfil.");
    });
    return () => { live = false; };
  }, [accountId]);

  if (!form) return <p className="text-mute">{error || "Cargando perfil…"}</p>;

  function set<K extends keyof Risk>(key: K, value: Risk[K]) {
    setForm((cur) => (cur ? { ...cur, [key]: value } : cur));
    setOk("");
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (form && form.max_daily_dd_pct > form.max_total_dd_pct) {
      setError("El drawdown diario no puede superar el total.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setForm(await session.saveRisk(accountId, form!));
      setOk("Perfil guardado. El próximo heartbeat ya usa estos límites.");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel max-w-xl space-y-6" onSubmit={onSubmit}>
      <div>
        <h2 className="text-lg">Límites de la cuenta</h2>
        <p className="mt-1 text-sm text-mute">Al llegar al límite, el servidor ordena el cierre. Al 80% el portal marca alerta.</p>
      </div>
      <Slider label="Drawdown diario máximo %" min={0.5} max={30} step={0.1} value={form.max_daily_dd_pct}
        onChange={(v) => set("max_daily_dd_pct", v)} />
      <Slider label="Drawdown total máximo %" min={1} max={50} step={0.1} value={form.max_total_dd_pct}
        onChange={(v) => set("max_total_dd_pct", v)} />
      <Slider label="Operaciones simultáneas" min={1} max={30} step={1} value={form.max_open_trades}
        onChange={(v) => set("max_open_trades", v)} />
      <Slider label="Riesgo por trade %" min={0.1} max={5} step={0.1} value={form.risk_per_trade_pct}
        onChange={(v) => set("risk_per_trade_pct", v)} />
      <button type="button" role="switch" aria-checked={form.news_filter}
        className="flex w-full items-center justify-between rounded-md border border-line px-3 py-3 text-left"
        onClick={() => set("news_filter", !form.news_filter)}>
        <span>
          <span className="block text-sm">Filtro de noticias</span>
          <span className="text-xs text-mute">Pausa las estrategias alrededor de eventos de alto impacto.</span>
        </span>
        <span className={`num text-sm ${form.news_filter ? "text-lime" : "text-mute"}`}>{form.news_filter ? "Activo" : "Apagado"}</span>
      </button>
      <button className="btn btn-lime" disabled={busy}>{busy ? "Guardando…" : "Guardar límites"}</button>
      {error && <p className="text-sm text-danger">{error}</p>}
      {ok && <p className="text-sm text-lime">{ok}</p>}
    </form>
  );
}

function Slider({ label, min, max, step, value, onChange }: {
  label: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between">
        <span className="label mb-0">{label}</span>
        <span className="num text-sm">{Number.isInteger(step) ? value : value.toFixed(1)}</span>
      </span>
      <input className="mt-2 w-full accent-lime" type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

const FIELDS: Record<string, { key: string; label: string; step: number; def: number }[]> = {
  session_breakout: [
    { key: "range_start", label: "Inicio del rango UTC", step: 1, def: 0 },
    { key: "range_end", label: "Fin del rango UTC", step: 1, def: 7 },
    { key: "trade_end", label: "Cierre de la ventana UTC", step: 1, def: 12 },
    { key: "sl_atr", label: "Stop en ATR", step: 0.1, def: 1.5 },
    { key: "rr", label: "Relación beneficio/riesgo", step: 0.1, def: 2 },
  ],
  zscore_reversion: [
    { key: "window", label: "Ventana", step: 1, def: 50 },
    { key: "entry_z", label: "Umbral Z", step: 0.1, def: 2 },
    { key: "sl_atr", label: "Stop en ATR", step: 0.1, def: 2 },
  ],
};

const NAMES: Record<string, string> = {
  session_breakout: "Session Breakout",
  zscore_reversion: "Z-Score",
};

export function Strategies() {
  return <NeedAccount>{(account) => <StrategyDesk accountId={account.id} />}</NeedAccount>;
}

function StrategyDesk({ accountId }: { accountId: string }) {
  const [rows, setRows] = useState<Strategy[]>([]);
  const [error, setError] = useState("");
  const [kind, setKind] = useState("session_breakout");
  const [symbol, setSymbol] = useState("EURUSD");
  const [params, setParams] = useState<Record<string, number>>(defaults("session_breakout"));
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setRows(await session.strategies(accountId));
  }, [accountId]);

  useEffect(() => { load().catch((err) => setError(err instanceof ApiError ? err.message : "No se pudieron leer las estrategias.")); }, [load]);

  function pickKind(next: string) {
    setKind(next);
    setParams(defaults(next));
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await session.createStrategy(accountId, { strategy: kind, symbol: symbol.trim().toUpperCase(), params });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la estrategia.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
      <section className="space-y-3">
        {rows.length === 0 && <p className="text-sm text-mute">Esta cuenta no tiene estrategias. Cree una a la derecha.</p>}
        {rows.map((row) => (
          <StrategyCard key={row.id} accountId={accountId} row={row} onChange={load} />
        ))}
      </section>
      <form className="panel h-fit space-y-4" onSubmit={create}>
        <h2 className="text-lg">Nueva estrategia</h2>
        <label className="block"><span className="label">Tipo</span>
          <select className="field" value={kind} onChange={(e) => pickKind(e.target.value)}>
            <option value="session_breakout">Session Breakout</option>
            <option value="zscore_reversion">Z-Score</option>
          </select>
        </label>
        <label className="block"><span className="label">Símbolo</span>
          <input className="field" list="symbols" required value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <datalist id="symbols">
            {["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"].map((s) => <option key={s} value={s} />)}
          </datalist>
        </label>
        {FIELDS[kind].map((f) => (
          <label key={f.key} className="block"><span className="label">{f.label}</span>
            <input className="field" type="number" step={f.step} value={params[f.key]}
              onChange={(e) => setParams({ ...params, [f.key]: Number(e.target.value) })} /></label>
        ))}
        <button className="btn btn-lime" disabled={busy}>{busy ? "Creando…" : "Activar estrategia"}</button>
        {error && <p className="text-sm text-danger">{error}</p>}
      </form>
    </div>
  );
}

function defaults(kind: string) {
  return Object.fromEntries(FIELDS[kind].map((f) => [f.key, f.def]));
}

function StrategyCard({ accountId, row, onChange }: { accountId: string; row: Strategy; onChange: () => Promise<void> }) {
  const fields = FIELDS[row.strategy] ?? [];
  const [params, setParams] = useState<Record<string, number>>({ ...defaults(row.strategy), ...row.params });
  const [error, setError] = useState("");

  async function toggle() {
    setError("");
    try {
      await session.patchStrategy(accountId, row.id, { enabled: !row.enabled });
      await onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo actualizar.");
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await session.patchStrategy(accountId, row.id, { params });
      await onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Parámetros inválidos.");
    }
  }

  return (
    <form className="panel space-y-3" onSubmit={save}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-lg">{NAMES[row.strategy] ?? row.strategy}</p>
          <p className="num text-sm text-mute">{row.symbol}</p>
        </div>
        <button type="button" className={`btn ${row.enabled ? "btn-lime" : "btn-ghost"}`} onClick={() => void toggle()}>
          {row.enabled ? "Activa" : "En pausa"}
        </button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => (
          <label key={f.key} className="block"><span className="label">{f.label}</span>
            <input className="field" type="number" step={f.step} value={params[f.key] ?? f.def}
              onChange={(e) => setParams({ ...params, [f.key]: Number(e.target.value) })} /></label>
        ))}
      </div>
      <button className="btn btn-ghost">Guardar parámetros</button>
      {error && <p className="text-sm text-danger">{error}</p>}
    </form>
  );
}

const PAGE = 20;

export function Trades() {
  return <NeedAccount>{(account) => <TradeTable accountId={account.id} />}</NeedAccount>;
}

function TradeTable({ accountId }: { accountId: string }) {
  const [perf, setPerf] = useState<Performance | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => { setOffset(0); }, [accountId]);

  useEffect(() => {
    let live = true;
    session.performance(accountId, PAGE, offset).then((p) => { if (live) setPerf(p); }).catch((err) => {
      if (live) setError(err instanceof ApiError ? err.message : "No se pudo leer el historial.");
    });
    return () => { live = false; };
  }, [accountId, offset]);

  if (!perf) return <p className="text-mute">{error || "Cargando operaciones…"}</p>;
  const m = perf.metrics;
  const from = perf.trades_total === 0 ? 0 : offset + 1;
  const to = offset + perf.trades.length;

  return (
    <div className="space-y-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Win rate" value={pct(m.win_rate)} />
        <Kpi label="Profit factor" value={m.profit_factor == null ? "—" : m.profit_factor.toFixed(2)} />
        <Kpi label="Expectancy" value={money(m.expectancy)} tone={toneOf(m.expectancy)} />
        <Kpi label="Drawdown máximo" value={pct(m.max_drawdown_pct)} tone={m.max_drawdown_pct > 0 ? "down" : undefined} />
        <Kpi label="Ganancia media" value={money(m.avg_win)} tone={m.avg_win ? "up" : undefined} />
        <Kpi label="Pérdida media" value={money(m.avg_loss)} tone={m.avg_loss ? "down" : undefined} />
        <Kpi label="Beneficio neto" value={money(m.net_pnl)} tone={toneOf(m.net_pnl)} />
        <Kpi label="Operaciones" value={String(m.trades)} />
      </section>
      <section className="panel overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-[0.14em] text-mute">
            <tr>
              {["Ticket", "Símbolo", "Lado", "Volumen", "Apertura", "Cierre", "PnL", "Hora"].map((h) => (
                <th key={h} className="pb-3 pr-4 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {perf.trades.length === 0 && (
              <tr><td colSpan={8} className="py-6 text-mute">No hay cierres en esta página.</td></tr>
            )}
            {perf.trades.map((t) => (
              <tr key={t.ticket} className="border-t border-line">
                <td className="num py-3 pr-4">{t.ticket}</td>
                <td className="py-3 pr-4">{t.symbol}</td>
                <td className={`py-3 pr-4 ${t.side === "BUY" ? "text-lime" : "text-danger"}`}>{t.side}</td>
                <td className="num py-3 pr-4">{t.volume}</td>
                <td className="num py-3 pr-4">{t.open_price}</td>
                <td className="num py-3 pr-4">{t.close_price ?? "—"}</td>
                <td className={`num py-3 pr-4 ${(t.pnl ?? 0) >= 0 ? "text-lime" : "text-danger"}`}>{money(t.pnl)}</td>
                <td className="py-3 pr-4 text-mute">{when(t.closed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-4 flex items-center justify-between text-sm text-mute">
          <span>{from}–{to} de {perf.trades_total}</span>
          <span className="flex gap-2">
            <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Anterior</button>
            <button className="btn btn-ghost" disabled={offset + PAGE >= perf.trades_total} onClick={() => setOffset(offset + PAGE)}>Siguiente</button>
          </span>
        </div>
      </section>
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}
