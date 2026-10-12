import { useState } from 'react'
import { simulateDisruption } from '../api.js'

export default function DisruptionPanel({ section, onScenario }) {
  const [train, setTrain] = useState(section.occupants[0]?.train ?? '')
  const [delayMin, setDelayMin] = useState(10)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleRun() {
    setLoading(true)
    setResult(null)
    const delay = Number(delayMin)
    const res = await simulateDisruption({
      train,
      sectionIndex: section.sectionIndex,
      sectionName: section.name,
      delayMin: delay,
    })
    setResult(res)
    if (res.live && !res.failed && onScenario) {
      onScenario({ train, sectionIndex: section.sectionIndex, delayMin: delay })
    }
    setLoading(false)
  }

  const resultClass = result?.failed ? 'conflict' : result?.conflicts > 0 ? 'conflict' : result ? 'clear' : ''

  return (
    <div className="panel">
      <div className="panel-title">Disruption simulator</div>
      <div className="form-row">
        <div className="field">
          <label htmlFor="train-select">Train</label>
          <select id="train-select" value={train} onChange={(e) => setTrain(e.target.value)}>
            {section.occupants.map((o) => (
              <option key={o.train} value={o.train}>{o.train}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="delay-input">Injected delay (min)</label>
          <input
            id="delay-input"
            type="number"
            min="1"
            max="120"
            value={delayMin}
            onChange={(e) => setDelayMin(e.target.value)}
          />
        </div>
        <button className="btn" onClick={handleRun} disabled={loading || !train || !(Number(delayMin) > 0)}>
          {loading ? 'RUNNING...' : 'RUN SIMULATION'}
        </button>
      </div>

      {result && (
        <div className={`result-line ${resultClass}`}>
          {result.failed && `Simulation failed: ${result.error}`}
          {!result.failed && result.note}
          {!result.failed && !result.note && (
            <>
              {result.conflicts} new conflict(s) after delaying {train} by {delayMin} min at {section.name}:
              <ul className="conflict-list">
                {result.conflictList.map((c, i) => (
                  <li key={i}>[{c.section_name}] {c.train_a} vs {c.train_b}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}