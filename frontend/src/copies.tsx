import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, CopyLink, session } from "./api";
import { useDesk } from "./desk";

export function Copies() {
  const { accounts } = useDesk();
  const [rows, setRows] = useState<CopyLink[]>([]);
  const [master, setMaster] = useState("");
  const [follower, setFollower] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setRows(await session.copies());
  }, []);

  useEffect(() => {
    load().catch((err) => setError(err instanceof ApiError ? err.message : "No se pudieron leer las copias."));
  }, [load]);

  useEffect(() => {
    if (!master && accounts[0]) setMaster(accounts[0].id);
    if (!follower && accounts[1]) setFollower(accounts[1].id);
  }, [accounts, master, follower]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await session.createCopy(master, follower);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear el vínculo.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError("");
    try {
      await session.deleteCopy(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo quitar el vínculo.");
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_0.8fr]">
      <section className="space-y-3">
        <h2 className="text-lg">Cuentas seguidoras</h2>
        <p className="text-sm text-mute">La seguidora recibe la misma orden. El lote baja o sube según su equidad frente a la maestra. El stop y el take profit no cambian.</p>
        {rows.length === 0 && <p className="text-sm text-mute">No hay vínculos.</p>}
        {rows.map((row) => (
          <article key={row.id} className="panel flex flex-wrap items-center justify-between gap-3">
            <p className="num text-sm">{row.master_account_number} → {row.follower_account_number}</p>
            <button className="btn btn-ghost" onClick={() => void remove(row.id)}>Quitar</button>
          </article>
        ))}
        {error && <p className="text-sm text-danger">{error}</p>}
      </section>
      <form className="panel h-fit space-y-4" onSubmit={create}>
        <h2 className="text-lg">Nuevo vínculo</h2>
        <label className="block"><span className="label">Maestra</span>
          <select className="field" required value={master} onChange={(e) => setMaster(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_number}</option>)}
          </select>
        </label>
        <label className="block"><span className="label">Seguidora</span>
          <select className="field" required value={follower} onChange={(e) => setFollower(e.target.value)}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_number}</option>)}
          </select>
        </label>
        <button className="btn btn-lime" disabled={busy || accounts.length < 2}>{busy ? "Guardando…" : "Vincular"}</button>
        {accounts.length < 2 && <p className="text-sm text-mute">Hacen falta al menos dos terminales vinculadas.</p>}
      </form>
    </div>
  );
}
