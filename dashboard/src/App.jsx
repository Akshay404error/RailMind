import { useEffect, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import Sidebar from './components/Sidebar.jsx'
import TrackTimeline from './components/TrackTimeline.jsx'
import DisruptionPanel from './components/DisruptionPanel.jsx'
import { getHealth, getSections } from './api.js'

export default function App() {
  const [health, setHealth] = useState({ status: 'down', live: false })
  const [sections, setSections] = useState([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [dataError, setDataError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const [h, s] = await Promise.all([getHealth(), getSections()])
      if (cancelled) return
      setHealth(h)
      setSections(s.sections)
      setDataError(s.live ? null : s.error)
      setLoading(false)
    }

    load()
    const interval = setInterval(async () => {
      const h = await getHealth()
      if (!cancelled) setHealth(h)
    }, 15000)

    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const activeSection = sections[activeIndex]

  return (
    <div className="console">
      <TopBar health={health} />
      <div className="console-body">
        {loading ? (
          <div className="state-msg" style={{ gridColumn: '1 / -1' }}>Loading corridor state…</div>
        ) : (
          <>
            <Sidebar sections={sections} activeIndex={activeIndex} onSelect={setActiveIndex} />
            <main className="main">
              {dataError && (
                <div className="state-msg error">
                  Backend unreachable — showing demo data from the validated ANVR→BRKY corridor run.
                </div>
              )}
              {activeSection && (
                <>
                  <div className="main-header">
                    <h1 className="main-title">{activeSection.name}</h1>
                  </div>
                  <p className="main-subtitle">
                    {activeSection.occupants.length} trains scheduled · {activeSection.headwayMin} min minimum headway
                  </p>

                  <div className="panel">
                    <div className="panel-title">Track occupancy</div>
                    <TrackTimeline section={activeSection} />
                  </div>

                  <DisruptionPanel section={activeSection} />
                </>
              )}
            </main>
          </>
        )}
      </div>
    </div>
  )
}
