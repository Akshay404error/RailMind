import { useState } from 'react'
import { emailReport, reportParams } from '../api.js'
import { downloadReportPdf } from '../auth.js'

export default function ReportPanel({ scenario }) {
  const [emails, setEmails] = useState('')
  const [includeScenario, setIncludeScenario] = useState(true)
  const [status, setStatus] = useState(null)
  const [sending, setSending] = useState(false)
  const [generating, setGenerating] = useState(false)

  const active = includeScenario && scenario ? scenario : null

  async function handleSend() {
    const to = emails.split(/[,;\s]+/).map((e) => e.trim()).filter(Boolean)
    if (to.length === 0) {
      setStatus({ ok: false, text: 'Enter at least one email address.' })
      return
    }
    setSending(true)
    setStatus(null)
    try {
      await emailReport({ to, scenario: active })
      setStatus({ ok: true, text: `Report sent to ${to.join(', ')}.` })
    } catch (err) {
      setStatus({ ok: false, text: `Could not send: ${err.message}` })
    }
    setSending(false)
  }

  async function handleGenerate() {
    setGenerating(true)
    setStatus(null)
    try {
      await downloadReportPdf(reportParams(active))
      setStatus({ ok: true, text: 'PDF report downloaded.' })
    } catch (err) {
      setStatus({ ok: false, text: `Could not generate report: ${err.message}` })
    }
    setGenerating(false)
  }

  return (
    <div className="panel">
      <div className="panel-title">Report &amp; mail</div>
      <div className="form-row">
        <div className="field" style={{ flex: 1 }}>
          <label htmlFor="mail-to">Send to (comma separated)</label>
          <input
            id="mail-to"
            type="text"
            placeholder="dispatcher@example.com, hod@example.com"
            value={emails}
            onChange={(e) => setEmails(e.target.value)}
          />
        </div>
        <button className="btn" onClick={handleSend} disabled={sending}>
          {sending ? 'SENDING...' : 'SEND MAIL'}
        </button>
        <button className="btn" onClick={handleGenerate} disabled={generating}>
          {generating ? 'BUILDING PDF...' : 'GENERATE REPORT'}
        </button>
      </div>
      {scenario && (
        <label className="report-check">
          <input
            type="checkbox"
            checked={includeScenario}
            onChange={(e) => setIncludeScenario(e.target.checked)}
          />
          Include last simulation (train {scenario.train}, +{scenario.delayMin} min)
        </label>
      )}
      {status && <div className={`result-line ${status.ok ? 'clear' : 'conflict'}`}>{status.text}</div>}
    </div>
  )
}