import { useState } from 'react'
import { simulateDisruption } from '../api.js'

export default function DisruptionPanel({ section }) {
  const [train, setTrain] = useState(section.occupants[0]?.train ?? '')
  const [delayMin, setDelayMin] = useState(10)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleRun() {
    setLoading(true)
    setResult(null)
    const res = await simulateDisruption({ train, sectionName: section.name, delayMin: Number(delayMin) })
    setResult(res)
    setLoading(false)
  }

  const resultClass = result?.conflicts > 0 ? 'conflict' : result ? 'clear' : ''

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
            max="60"
            value={delayMin}
            onChange={(e) => setDelayMin(e.target.value)}
          />
        </div>
        <button className="btn" onClick={handleRun} disabled={loading || !train}>
          {loading ? 'RUNNING…' : 'RUN SIMULATION'}
        </button>
      </div>

      {result && (
        <div className={`result-line ${resultClass}`}>
          {result.note || (result.conflicts > 0
            ? `${result.conflicts} conflict(s) triggered on ${section.name}.`
            : `No conflicts triggered on ${section.name}.`)}
          {!result.live && ' (backend unreachable — showing local estimate)'}
        </div>
      )}
    </div>
  )
}
