import { useCallback, useEffect, useState } from "react";
import { downloadFile, fetchMe, getJson, postJson } from "../auth";

// Admin-only panel: who signed in / what they did, with IP + location.
// Renders nothing for normal users.
export default function ActivityPanel() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [hours, setHours] = useState(24);
  const [events, setEvents] = useState([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchMe().then((m) => setIsAdmin(!!m.is_admin)).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await getJson(`/admin/activity?hours=${hours}&limit=100`);
      setEvents(r.events);
    } catch (e) {
      setMsg(e.message);
    }
  }, [hours]);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  if (!isAdmin) return null;

  async function run(fn, okText) {
    setBusy(true);
    setMsg("");
    try {
      const r = await fn();
      setMsg(okText(r));
      load();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  const fmt = (ts) => new Date(ts * 1000).toLocaleString();

  return (
    <div className="panel activity-panel">
      <div className="panel-title">Activity &amp; sign-ins</div>
      <div className="tc-group" style={{ marginBottom: 10 }}>
        <span className="tc-label">Period</span>
        {[[1, "1h"], [24, "24h"], [168, "7d"]].map(([h, label]) => (
          <button key={h} className={"chip" + (hours === h ? " active" : "")} onClick={() => setHours(h)}>
            {label}
          </button>
        ))}
        <button className="chip" onClick={load}>Refresh</button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run(() => downloadFile(`/admin/activity.pdf?hours=${hours}`, "railmind_activity.pdf"), () => "PDF downloaded.")}
        >
          DOWNLOAD PDF
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run(() => postJson(`/admin/activity/email?hours=${hours}`), (r) => `Sent to ${r.to} (${r.events} events).`)}
        >
          EMAIL PDF TO ADMIN
        </button>
      </div>
      {msg && <p className="tc-hint">{msg}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>TIME</th><th>USER</th><th>ACTIVITY</th><th>DETAILS</th><th>IP</th><th>LOCATION</th></tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>{fmt(e.ts)}</td>
                <td>{e.email || "-"}</td>
                <td>{e.action}</td>
                <td>{e.detail}</td>
                <td>{e.ip}</td>
                <td>{e.location}</td>
              </tr>
            ))}
            {events.length === 0 && <tr><td colSpan={6}>No activity in this period.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}