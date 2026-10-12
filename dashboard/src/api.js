// RailMind dashboard - API layer (v3: login-aware)
//
// Talks to the FastAPI backend through the /api proxy (see vite.config.js).
//   GET  /health                 (public)
//   GET  /schedule/corridor      (all sections + trains + priority + conflicts, one call)
//   POST /simulate/disruption    (what-if delay on one train)
//   GET  /report/pdf             (PDF report, see downloadReportPdf in auth.js)
//   POST /report/email           (email the live report)
//
// Every call except /health goes through authFetch, which adds the login token.
// If the backend is unreachable, getSections() falls back to demo data.

import { authFetch } from './auth.js'

const BASE = '/api'

export const PRIORITY_INFO = {
  1: { label: 'Premium', color: 'var(--lamp-blue)' },
  2: { label: 'Express', color: 'var(--signal-clear)' },
  3: { label: 'Passenger', color: 'var(--text-faint)' },
}

const DEMO_SECTIONS = [
  { name: 'ANVR -> ANVT', headwayMin: 3, occupants: [
    { train: '12004', entryMin: 1829, priority: 1 },
    { train: '12816', entryMin: 1840, priority: 2 },
    { train: '12876', entryMin: 1840, priority: 2 },
    { train: '12017', entryMin: 1868, priority: 1 },
  ]},
  { name: 'ANVT -> CNJ', headwayMin: 5, occupants: [
    { train: '14012', entryMin: 1800, priority: 2 },
    { train: '12004', entryMin: 1830, priority: 1 },
    { train: '12816', entryMin: 1841, priority: 2 },
    { train: '12506', entryMin: 1850, priority: 2 },
  ]},
  { name: 'CNJ -> SBB', headwayMin: 5, occupants: [
    { train: '14012', entryMin: 1804, priority: 2 },
    { train: '12004', entryMin: 1831, priority: 1 },
    { train: '12876', entryMin: 1842, priority: 2 },
  ]},
  { name: 'SBB -> GZB', headwayMin: 3, occupants: [
    { train: '54308', entryMin: 1570, priority: 3 },
    { train: '14012', entryMin: 1812, priority: 2 },
    { train: '12004', entryMin: 1835, priority: 1 },
    { train: '14556', entryMin: 1842, priority: 2 },
  ]},
  { name: 'GZB -> MIU', headwayMin: 5, occupants: [
    { train: '12004', entryMin: 1846, priority: 1 },
    { train: '12816', entryMin: 1851, priority: 2 },
    { train: '12506', entryMin: 1862, priority: 2 },
  ]},
  { name: 'MIU -> DER', headwayMin: 4, occupants: [
    { train: '12004', entryMin: 1852, priority: 1 },
    { train: '12816', entryMin: 1859, priority: 2 },
    { train: '14084', entryMin: 1896, priority: 2 },
  ]},
  { name: 'DER -> BRKY', headwayMin: 3, occupants: [
    { train: '12004', entryMin: 1856, priority: 1 },
    { train: '12816', entryMin: 1865, priority: 2 },
    { train: '12324', entryMin: 1909, priority: 2 },
  ]},
]

export function minutesToClock(min) {
  const h = Math.floor((min % 1440) / 60)
  const m = Math.round(min % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

// Demo-data only. Live data gets its conflict flags from the backend simulator
// (capacity + headway aware), so this naive gap check is NOT used for live data.
function withDemoConflicts(section, index) {
  const sorted = [...section.occupants].sort((a, b) => a.entryMin - b.entryMin)
  const flagged = sorted.map((o, i) => {
    const prev = sorted[i - 1]
    return { ...o, conflict: Boolean(prev && o.entryMin - prev.entryMin < section.headwayMin) }
  })
  return { ...section, sectionIndex: index, occupants: flagged }
}

// /health is public, so it uses plain fetch (no login needed for the status light).
export async function getHealth() {
  try {
    const res = await fetch(`${BASE}/health`)
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    return { status: data.status === 'ok' ? 'ok' : 'warn', live: true }
  } catch (err) {
    return { status: 'down', live: false, error: err.message }
  }
}

export async function getSections() {
  try {
    const res = await authFetch('/schedule/corridor')
    if (!res.ok) throw new Error(`/schedule/corridor status ${res.status}`)
    const data = await res.json()
    const sections = data.sections.map((s) => ({
      name: s.name,
      sectionIndex: s.section_index,
      headwayMin: s.headway_minutes,
      lineType: s.line_type,
      capacity: s.capacity,
      durationMin: s.duration_minutes,
      occupants: s.occupants.map((o) => ({
        train: o.train,
        entryMin: o.entry_min,
        delayMin: o.delay_min,
        priority: o.priority,
        conflict: o.conflict,
      })),
    }))
    return { sections, live: true, conflictCount: data.conflict_count }
  } catch (err) {
    return {
      sections: DEMO_SECTIONS.map(withDemoConflicts),
      live: false,
      error: err.message,
      conflictCount: null,
    }
  }
}

export async function simulateDisruption({ train, sectionIndex, sectionName, delayMin }) {
  try {
    const res = await authFetch('/simulate/disruption', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        train_number: train,
        section_index: sectionIndex,
        delay_min: delayMin,
        propagate: true,
      }),
    })
    if (!res.ok) {
      let detail = ''
      try { detail = (await res.json()).detail } catch { /* ignore */ }
      throw new Error(`status ${res.status}${detail ? ` - ${detail}` : ''}`)
    }
    const data = await res.json()
    return {
      live: true,
      conflicts: data.new_conflicts.length,
      conflictList: data.new_conflicts,
      note: data.conflict_free
        ? `+${delayMin} min on ${train} at ${sectionName}: the schedule absorbs this delay, no new conflicts.`
        : null,
    }
  } catch (err) {
    // Only guess locally when the backend can't be reached at all.
    if (err instanceof TypeError) {
      const conflicted = delayMin > 8
      return {
        live: false,
        conflicts: conflicted ? 1 : 0,
        note: `Backend unreachable - local estimate: a ${delayMin} min delay on ${train} ${conflicted ? 'likely breaches' : 'stays within'} headway on ${sectionName}.`,
      }
    }
    return { live: true, failed: true, error: err.message }
  }
}

// ---------- report + mail ----------

// Query params for the PDF report / email, built from the last simulation (or none).
export function reportParams(scenario) {
  if (!scenario) return {}
  return {
    train_number: scenario.train,
    section_index: scenario.sectionIndex,
    delay_min: scenario.delayMin,
  }
}

export async function emailReport({ to, subject, scenario }) {
  const body = { to, subject: subject || null }
  if (scenario) {
    body.train_number = scenario.train
    body.section_index = scenario.sectionIndex
    body.delay_min = scenario.delayMin
  }
  const res = await authFetch('/report/email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `status ${res.status}`
    try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}