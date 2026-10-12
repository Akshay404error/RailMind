import { useState } from 'react'
import { minutesToClock, PRIORITY_INFO } from '../api.js'

const WINDOWS = [
  { label: 'All', hours: null },
  { label: '1 h', hours: 1 },
  { label: '2 h', hours: 2 },
  { label: '4 h', hours: 4 },
  { label: '8 h', hours: 8 },
]
const DENSE_LIMIT = 14

function markerClass(o) {
  if (o.conflict) return 'conflict'
  if (o.priority) return `pri-${o.priority}`
  return o.delayMin > 0 ? 'held' : 'ontime'
}

function PriorityBadge({ priority }) {
  const info = PRIORITY_INFO[priority]
  if (!info) return <span style={{ color: 'var(--text-faint)' }}>-</span>
  return (
    <span className="pri-badge">
      <span className="legend-dot" style={{ background: info.color }} /> {info.label}
    </span>
  )
}

// Track occupancy for one block section. Real corridors carry 60-135 trains
// per section, so the plot has a time-window filter + slider (the plot stays
// readable) and a priority filter; labels hide on dense plots and show on hover.
export default function TrackTimeline({ section }) {
  const occupants = section.occupants
  const [windowIdx, setWindowIdx] = useState(() => (occupants.length > 25 ? 2 : 0))
  const [prioFilter, setPrioFilter] = useState('all')
  const [start, setStart] = useState(null)

  if (occupants.length === 0) {
    return <div className="state-msg">No trains scheduled through this section in the current window.</div>
  }

  const dataMin = Math.floor(Math.min(...occupants.map((o) => o.entryMin)))
  const dataMax = Math.ceil(Math.max(...occupants.map((o) => o.entryMin)))
  const hours = WINDOWS[windowIdx].hours
  const winStart = Math.min(Math.max(start ?? dataMin, dataMin), dataMax)
  const winEnd = hours == null ? dataMax + 1 : winStart + hours * 60

  const hasPriority = occupants.some((o) => o.priority != null)
  const visible = occupants
    .filter((o) => hours == null || (o.entryMin >= winStart && o.entryMin < winEnd))
    .filter((o) => prioFilter === 'all' || String(o.priority) === prioFilter)
    .sort((a, b) => a.entryMin - b.entryMin)

  const axisMin = hours == null ? dataMin - section.headwayMin : winStart
  const axisMax = hours == null ? dataMax + section.headwayMin : winEnd
  const span = axisMax - axisMin || 1
  const pct = (t) => ((t - axisMin) / span) * 100

  const dense = visible.length > DENSE_LIMIT
  const conflictCount = occupants.filter((o) => o.conflict).length
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => axisMin + f * span)

  return (
    <div>
      <div className="timeline-controls">
        <div className="tc-group">
          <span className="tc-label">Window</span>
          {WINDOWS.map((w, i) => (
            <button
              key={w.label}
              type="button"
              className={`chip ${i === windowIdx ? 'active' : ''}`}
              onClick={() => setWindowIdx(i)}
            >
              {w.label}
            </button>
          ))}
        </div>
        {hasPriority && (
          <div className="tc-group">
            <span className="tc-label">Priority</span>
            {[['all', 'All'], ['1', 'Premium'], ['2', 'Express'], ['3', 'Passenger']].map(([v, label]) => (
              <button
                key={v}
                type="button"
                className={`chip ${prioFilter === v ? 'active' : ''}`}
                onClick={() => setPrioFilter(v)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {hours != null && dataMax > dataMin && (
        <div className="tc-slider">
          <span className="tc-label">Start {minutesToClock(winStart)}</span>
          <input
            type="range"
            min={dataMin}
            max={dataMax}
            step={5}
            value={winStart}
            onChange={(e) => setStart(Number(e.target.value))}
          />
        </div>
      )}

      <div className="timeline-wrap">
        <div className="timeline-track">
          {visible.map((o) => (
            <div
              key={`hw-${o.train}`}
              className="timeline-headway"
              style={{
                left: `${pct(o.entryMin - section.headwayMin / 2)}%`,
                width: `${pct(o.entryMin + section.headwayMin / 2) - pct(o.entryMin - section.headwayMin / 2)}%`,
              }}
            />
          ))}
          {visible.map((o) => (
            <div
              key={o.train}
              className={`train-marker ${markerClass(o)} ${dense ? 'dense' : ''}`}
              style={{ left: `${pct(o.entryMin)}%` }}
              title={`${o.train} - ${minutesToClock(o.entryMin)}${PRIORITY_INFO[o.priority] ? ` - ${PRIORITY_INFO[o.priority].label}` : ''}${o.delayMin > 0 ? ` - held ${o.delayMin}min` : ''}${o.conflict ? ' - CONFLICT' : ''}`}
            >
              <span className="train-label">{o.train} · {minutesToClock(o.entryMin)}</span>
            </div>
          ))}
        </div>
        <div className="timeline-axis">
          {ticks.map((t, i) => <span key={i}>{minutesToClock(t)}</span>)}
        </div>
      </div>

      <div className="legend">
        {hasPriority ? (
          Object.entries(PRIORITY_INFO).map(([k, info]) => (
            <span key={k} className="legend-item">
              <span className="legend-dot" style={{ background: info.color }} /> {info.label}
            </span>
          ))
        ) : (
          <>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-clear)' }} /> On time</span>
            <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-caution)' }} /> Held for conflict resolution</span>
          </>
        )}
        <span className="legend-item"><span className="legend-dot" style={{ background: 'var(--signal-danger)' }} /> Conflict</span>
        <span className="legend-item" style={{ marginLeft: 'auto', color: 'var(--text-faint)' }}>
          Showing {visible.length} of {occupants.length} trains{conflictCount > 0 ? ` · ${conflictCount} conflicting` : ''}
        </span>
      </div>

      {dense && <div className="tc-hint">Many trains in this window - hover a marker for its label, or narrow the window.</div>}

      <div className="table-scroll">
        <table className="occupancy-table">
          <thead>
            <tr>
              <th>Train</th>
              <th>Entry time</th>
              {hasPriority && <th>Priority</th>}
              <th>Delay</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((o) => (
              <tr key={o.train} className={o.conflict ? 'row-conflict' : ''}>
                <td className="mono">{o.train}</td>
                <td className="mono">{minutesToClock(o.entryMin)}</td>
                {hasPriority && <td><PriorityBadge priority={o.priority} /></td>}
                <td className="mono">{o.delayMin > 0 ? `+${o.delayMin}m` : '-'}</td>
                <td>{o.conflict ? 'CONFLICT' : o.delayMin > 0 ? 'HELD' : 'ON TIME'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}