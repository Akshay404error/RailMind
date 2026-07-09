function sectionAspect(section) {
  const hasConflict = section.occupants.some((o) => o.conflict)
  if (hasConflict) return 'danger'
  if (section.occupants.length >= 4) return 'caution'
  return 'clear'
}

export default function Sidebar({ sections, activeIndex, onSelect }) {
  return (
    <nav className="sidebar" aria-label="Block sections">
      <div className="sidebar-label">Block sections — ANVR to BRKY</div>
      {sections.map((section, i) => {
        const aspect = sectionAspect(section)
        return (
          <button
            key={section.name}
            className={`section-btn ${i === activeIndex ? 'active' : ''}`}
            onClick={() => onSelect(i)}
          >
            <span className={`aspect-dot ${aspect}`} />
            <span style={{ flex: 1 }}>
              <div className="section-btn-name">{section.name}</div>
              <div className="section-btn-meta">
                {section.occupants.length} trains · {section.headwayMin}min headway
              </div>
            </span>
          </button>
        )
      })}
    </nav>
  )
}
