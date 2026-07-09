// RailMind dashboard — API layer
//
// Calls the FastAPI backend via the /api proxy (see vite.config.js).
// Field names below (`health()`, `getSections()`, `simulateDisruption()`)
// assume endpoints matching what was scaffolded earlier
// (/health, /schedule/sections, /simulate/baseline) — ADJUST THE PATHS
// AND RESPONSE MAPPING BELOW if your actual FastAPI routes differ.
//
// If a call fails (backend not running, wrong shape, CORS, etc.) each
// function falls back to real demo data from the actual ANVR->BRKY
// corridor so the dashboard is still usable standalone.

const BASE = '/api'

// Real corridor + a sample of real train numbers/priorities from the
// validated optimizer run, used only as a fallback when the live API
// isn't reachable.
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

function minutesToClock(min) {
  const h = Math.floor((min % 1440) / 60)
  const m = Math.round(min % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function withHeadwayConflicts(section) {
  const sorted = [...section.occupants].sort((a, b) => a.entryMin - b.entryMin)
  const flagged = sorted.map((o, i) => {
    const prev = sorted[i - 1]
    const conflict = prev && (o.entryMin - prev.entryMin) < section.headwayMin
    return { ...o, conflict: Boolean(conflict) }
  })
  return { ...section, occupants: flagged }
}

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
    // CONFIRMED shapes from your real /openapi.json:
    //   GET /schedule/sections -> SectionInfo[]
    //     { section_index, from_station, to_station, line_type, capacity,
    //       headway_minutes, duration_minutes }
    //   GET /schedule/trains -> string[]  (just train numbers)
    //   GET /schedule/trains/{train_number} -> TrainScheduleResponse
    //     { train_number, stops: [{ section, section_index,
    //       scheduled_entry_min, recommended_entry_min, delay_min }] }
    //
    // There's no single endpoint returning sections+trains together, and
    // no priority/train-name field anywhere - so this reassembles
    // occupancy client-side from the per-train endpoint, and colors
    // trains by delay_min (real optimizer output) instead of priority
    // (which the API doesn't expose).
    const [sectionsRes, trainsRes] = await Promise.all([
      fetch(`${BASE}/schedule/sections`),
      fetch(`${BASE}/schedule/trains`),
    ])
    if (!sectionsRes.ok) throw new Error(`/schedule/sections status ${sectionsRes.status}`)
    if (!trainsRes.ok) throw new Error(`/schedule/trains status ${trainsRes.status}`)

    const sectionMetas = await sectionsRes.json()
    const trainNumbers = await trainsRes.json()

    const sectionsByIndex = new Map(
      sectionMetas.map((s) => [s.section_index, {
        name: `${s.from_station} -> ${s.to_station}`,
        sectionIndex: s.section_index,
        headwayMin: s.headway_minutes ?? 5,
        lineType: s.line_type,
        capacity: s.capacity,
        durationMin: s.duration_minutes,
        occupants: [],
      }])
    )

    // Fetch every train's schedule. allSettled so one bad train doesn't
    // blank the whole corridor.
    const trainResults = await Promise.allSettled(
      trainNumbers.map((num) =>
        fetch(`${BASE}/schedule/trains/${num}`).then((r) => {
          if (!r.ok) throw new Error(`status ${r.status}`)
          return r.json()
        })
      )
    )

    for (const result of trainResults) {
      if (result.status !== 'fulfilled') continue
      const { train_number, stops } = result.value
      for (const stop of stops) {
        const section = sectionsByIndex.get(stop.section_index)
        if (!section) continue
        section.occupants.push({
          train: train_number,
          entryMin: stop.recommended_entry_min,
          delayMin: stop.delay_min,
          priority: null,  // not exposed by the API
        })
      }
    }

    const sections = [...sectionsByIndex.values()]
      .sort((a, b) => a.sectionIndex - b.sectionIndex)
      .map(withHeadwayConflicts)

    return { sections, live: true }
  } catch (err) {
    return { sections: DEMO_SECTIONS.map(withHeadwayConflicts), live: false, error: err.message }
  }
}

export async function simulateDisruption({ train, sectionName, delayMin }) {
  try {
    const res = await fetch(`${BASE}/simulate/baseline`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ train_number: train, section: sectionName, delay_min: delayMin }),
    })
    if (res.status === 404) {
      throw new Error('404 - /simulate/baseline not found (router likely not registered in main.py yet)')
    }
    if (!res.ok) throw new Error(`status ${res.status}`)
    const data = await res.json()
    return { ...data, live: true }
  } catch (err) {
    // Fallback: a plausible local estimate so the panel is still demoable
    // even though /simulate isn't live yet.
    const conflicted = delayMin > 8
    return {
      live: false,
      error: err.message,
      resolved: true,
      conflicts: conflicted ? 1 : 0,
      note: conflicted
        ? `Simulated locally (${err.message}): a ${delayMin}min delay on ${train} likely breaches headway on ${sectionName}.`
        : `Simulated locally (${err.message}): a ${delayMin}min delay on ${train} stays within headway on ${sectionName}.`,
    }
  }
}

export { minutesToClock }