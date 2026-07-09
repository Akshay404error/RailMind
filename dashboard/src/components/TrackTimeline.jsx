import { minutesToClock } from '../api.js'

function markerClass(o) {
  if (o.conflict) return 'conflict'
  if (o.priority) return `pri-${o.priority}`
  return o.delayMin > 0 ? 'held' : 'ontime'
}

function statusLabel(o) {
  if (o.conflict) return 'CONFLICT'
  if (o.priority) return null
  return o.delayMin > 0 ? `HELD +${o.delayMin}m` : 'ON TIME'
}

// Plots trains along a real time axis for the selected section, plus a
// scannable table below - the dot-plot alone stops being readable past
// ~15-20 trains (labels overlap), and this corridor's busiest sections
// carry 60-135 trains across a full day, so the table is the part that
// actually stays usable at real scale. The plot is still useful for
// spotting clusters/gaps at a glance; the table is for reading specifics.
export default function TrackTimeline({ section }) {
  const occupants = section.occupants
  if (occupants.length === 0) {
    return <div className="state-msg">No trains scheduled through this section in the current window.</div>
  }

  const sorted = [...occupants].sort((a, b) => a.entryMin - b.entryMin)
  const times = occupants.map((o) => o.entryMin)
  const min = Math.min(...times) - section.headwayMin
  const max = Math.max(...times) + section.headwayMin
  const span = max - min || 1

  const pct = (t) => ((t - min) / span) * 100
  const hasPriority = occupants.some((o) => o.priority != null)
  const conflictCount = occupants.filter((o) => o.conflict).length

  return (
    <div>
      <div className="timeline-wrap">
        <div className="timeline-track">
          {occupants.map((o) => (
            <div
              key={`hw-${o.train}`}
              className="timeline-headway"
              style={{
                left: `${pct(o.entryMin - section.headwayMin / 2)}%`,
                width: `${pct(o.entryMin + section.headwayMin / 2) - pct(o.entryMin - section.headwayMin / 2)}%`,
              }}
            />
          ))}
          {occupants.map((o) => (
            <div
              key={o.train}
              className={`train-marker ${markerClass(o)}`}
              style={{ left: `${pct(o.entryMin)}%` }}
              title={`${o.train} — ${minutesToClock(o.entryMin)}${o.delayMin > 0 ? ` — held ${o.delayMin}min` : ''}${o.conflict ? ' — HEADWAY CONFLICT' : ''}`}
            >
              <span className="train-label">{o.train} · {minutesToClock(o.entryMin)}</span>
            </div>
          ))}
        </div>
        <div className="timeline-axis">
          <span>{minutesToClock(min)}</span>
          <span>{minutesToClock((min + max) / 2)}</span>
          <span>{minutesToClock(max)}</span>
        </div>
      </div>

      <div className="legend">
        {hasPriority ? (
          <>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--lamp-blue)' }} /> Premium</span>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-clear)' }} /> Express</span>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--text-faint)' }} /> Passenger</span>
          </>
        ) : (
          <>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-clear)' }} /> On time</span>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-caution)' }} /> Held for conflict resolution</span>
          </>
        )}
        <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-danger)' }} /> Headway conflict</span>
        <span className="legend-item" style={{ marginLeft: 'auto', color: 'var(--text-faint)' }}>
          {occupants.length} trains{conflictCount > 0 ? ` · ${conflictCount} conflicting` : ''}
        </span>
      </div>

      <table className="occupancy-table">
        <thead>
          <tr>
            <th>Train</th>
            <th>Entry time</th>
            {!hasPriority && <th>Delay</th>}
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => (
            <tr key={o.train} className={o.conflict ? 'row-conflict' : ''}>
              <td className="mono">{o.train}</td>
              <td className="mono">{minutesToClock(o.entryMin)}</td>
              {!hasPriority && <td className="mono">{o.delayMin > 0 ? `+${o.delayMin}m` : '—'}</td>}
              <td>{statusLabel(o)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}