import { useEffect, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import Sidebar from './components/Sidebar.jsx'
import TrackTimeline from './components/TrackTimeline.jsx'
import DisruptionPanel from './components/DisruptionPanel.jsx'
import ReportPanel from './components/ReportPanel.jsx'
import Login from './components/Login.jsx'
import AccountBar from './components/AccountBar.jsx'
import ActivityPanel from './components/ActivityPanel.jsx'
import { getHealth, getSections } from './api.js'
import { getToken } from './auth.js'

const REFRESH_MS = 30000

export default function App() {
  const [authed, setAuthed] = useState(() => Boolean(getToken()))
  const [health, setHealth] = useState({ status: 'down', live: false })
  const [sections, setSections] = useState([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [dataError, setDataError] = useState(null)
  const [conflictCount, setConflictCount] = useState(null)
  const [scenario, setScenario] = useState(null)

  // Send the user back to the login screen when the session expires or they sign out.
  useEffect(() => {
    const onExpired = () => setAuthed(false)
    window.addEventListener('auth-expired', onExpired)
    return () => window.removeEventListener('auth-expired', onExpired)
  }, [])

  // Load live data only while signed in.
  useEffect(() => {
    if (!authed) return undefined
    let cancelled = false

    async function load() {
      const [h, s] = await Promise.all([getHealth(), getSections()])
      if (cancelled) return
      setHealth(h)
      setSections(s.sections)
      setDataError(s.live ? null : s.error)
      setConflictCount(s.conflictCount)
      setLoading(false)
    }

    setLoading(true)
    load()
    // Re-read live data every 30 s so the console follows the data files.
    const interval = setInterval(load, REFRESH_MS)
    return () => { cancelled = true; clearInterval(interval) }
  }, [authed])

  // All hooks are above this line. Not signed in -> login screen.
  if (!authed) {
    return <Login onLogin={() => { setScenario(null); setAuthed(true) }} />
  }

  const activeSection = sections[activeIndex]

  return (
    <div className="console">
      <TopBar health={health} />
      <div className="account-float"><AccountBar /></div>
      <div className="console-body">
        {loading ? (
          <div className="state-msg" style={{ gridColumn: '1 / -1' }}>Loading corridor state...</div>
        ) : (
          <>
            <Sidebar sections={sections} activeIndex={activeIndex} onSelect={setActiveIndex} />
            <main className="main">
              {dataError && (
                <div className="state-msg error">
                  Backend unreachable - showing demo data ({dataError}).
                </div>
              )}
              {activeSection && (
                <>
                  <div className="main-header">
                    <h1 className="main-title">{activeSection.name}</h1>
                  </div>
                  <p className="main-subtitle">
                    {activeSection.occupants.length} trains scheduled · {activeSection.headwayMin} min minimum headway
                    {conflictCount != null && ` · corridor conflicts: ${conflictCount}`}
                  </p>

                  <div className="panel">
                    <div className="panel-title">Track occupancy</div>
                    <TrackTimeline key={activeSection.name} section={activeSection} />
                  </div>

                  <DisruptionPanel key={`d-${activeSection.name}`} section={activeSection} onScenario={setScenario} />
                  <ReportPanel scenario={scenario} />
                  <ActivityPanel />
                </>
              )}
            </main>
          </>
        )}
      </div>
    </div>
  )
}