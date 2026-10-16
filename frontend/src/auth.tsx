import { FormEvent, ReactNode, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, getToken, session, setToken } from "./api";

function Frame({ title, lede, children }: { title: string; lede: string; children: ReactNode }) {
  return (
    <div className="grid min-h-full md:grid-cols-[1.1fr_1fr]">
      <aside className="hidden flex-col justify-between border-r border-line bg-[#171c15] p-12 md:flex">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-sm bg-lime text-sm font-semibold text-ink">QG</span>
          <span className="text-lg tracking-tight">Quant Guardian</span>
        </div>
        <div>
          <p className="max-w-sm text-4xl font-medium leading-tight tracking-tight">{title}</p>
          <p className="mt-4 max-w-sm text-mute">{lede}</p>
        </div>
        <p className="text-xs uppercase tracking-[0.18em] text-mute">Riesgo centralizado · ejecución en MT5</p>
      </aside>
      <main className="flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}

function ErrorNote({ error }: { error: string }) {
  if (!error) return null;
  return <p className="mt-3 text-sm text-danger">{error}</p>;
}

export function Login() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (getToken()) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await session.login(email, password);
      setToken(r.access_token);
      nav("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="El riesgo se decide antes de la orden." lede="Supervise el drawdown, pause estrategias y audite cada cierre que reporta la terminal.">
      <h1 className="text-2xl font-medium">Inicie sesión</h1>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        <label className="block"><span className="label">Correo</span>
          <input className="field" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="block"><span className="label">Contraseña</span>
          <input className="field" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button className="btn btn-lime w-full" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
        <ErrorNote error={error} />
      </form>
      <p className="mt-6 text-sm text-mute">
        <Link className="text-paper underline decoration-line underline-offset-4" to="/recuperar">Olvidé mi contraseña</Link>
        <span className="mx-2">·</span>
        <Link className="text-paper underline decoration-line underline-offset-4" to="/registro">Crear cuenta</Link>
      </p>
    </Frame>
  );
}

export function Register() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (getToken()) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== again) { setError("Las contraseñas no coinciden."); return; }
    setBusy(true);
    setError("");
    try {
      const r = await session.register(email, password);
      setToken(r.access_token);
      nav("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la cuenta.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="Una cuenta. Varias terminales." lede="El registro abre el portal. La licencia se activa cuando la pasarela confirma el plan.">
      <h1 className="text-2xl font-medium">Crear cuenta</h1>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        <label className="block"><span className="label">Correo</span>
          <input className="field" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="block"><span className="label">Contraseña</span>
          <input className="field" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <label className="block"><span className="label">Confirmar</span>
          <input className="field" type="password" required minLength={8} value={again} onChange={(e) => setAgain(e.target.value)} /></label>
        <button className="btn btn-lime w-full" disabled={busy}>{busy ? "Creando…" : "Crear cuenta"}</button>
        <ErrorNote error={error} />
      </form>
      <p className="mt-6 text-sm text-mute">
        <Link className="text-paper underline decoration-line underline-offset-4" to="/login">Ya tengo cuenta</Link>
      </p>
    </Frame>
  );
}

export function Forgot() {
  const [email, setEmail] = useState("");
  const [token, setTok] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await session.forgot(email);
      setTok(r.reset_token ?? "");
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo enviar la solicitud.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="Restablezca el acceso sin perder las terminales." lede="El enlace vence a los 30 minutos y solo puede usarse una vez.">
      <h1 className="text-2xl font-medium">Recuperar contraseña</h1>
      {done ? (
        <div className="mt-8 text-sm leading-6 text-mute">
          <p>Si el correo está registrado, ya puede definir una contraseña nueva.</p>
          {token ? (
            <p className="mt-4">
              <Link className="text-lime underline underline-offset-4" to={`/restablecer?token=${encodeURIComponent(token)}`}>
                Continuar con el restablecimiento
              </Link>
            </p>
          ) : (
            <p className="mt-4">Revise su correo y abra el enlace que le enviamos.</p>
          )}
        </div>
      ) : (
        <form className="mt-8 space-y-4" onSubmit={onSubmit}>
          <label className="block"><span className="label">Correo</span>
            <input className="field" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <button className="btn btn-lime w-full" disabled={busy}>{busy ? "Enviando…" : "Enviar enlace"}</button>
          <ErrorNote error={error} />
        </form>
      )}
      <p className="mt-6 text-sm text-mute">
        <Link className="text-paper underline decoration-line underline-offset-4" to="/login">Volver</Link>
      </p>
    </Frame>
  );
}

export function Reset() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [token, setTok] = useState(params.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await session.reset(token.trim(), password);
      nav("/login");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo restablecer la contraseña.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="Una clave nueva. La misma licencia." lede="Después de guardarla, entre de nuevo al portal.">
      <h1 className="text-2xl font-medium">Nueva contraseña</h1>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        <label className="block"><span className="label">Token</span>
          <input className="field" required minLength={20} value={token} onChange={(e) => setTok(e.target.value)} /></label>
        <label className="block"><span className="label">Contraseña nueva</span>
          <input className="field" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button className="btn btn-lime w-full" disabled={busy}>{busy ? "Guardando…" : "Guardar"}</button>
        <ErrorNote error={error} />
      </form>
    </Frame>
  );
}
