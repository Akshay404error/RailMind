export default function TopBar({ health }) {
  const dotClass = health.status === 'ok' ? 'ok' : health.status === 'warn' ? 'warn' : 'down'
  const label = health.live
    ? (health.status === 'ok' ? 'LINK NOMINAL' : 'LINK DEGRADED')
    : 'LINK OFFLINE — DEMO DATA'

  return (
    <header className="topbar">
      <div className="wordmark">
        <span className="wordmark-mark">RAILMIND</span>
        <span className="wordmark-sub">CORRIDOR CONSOLE</span>
      </div>
      <div className="health-pill">
        <span className={`health-dot ${dotClass}`} />
        {label}
      </div>
    </header>
  )
}
