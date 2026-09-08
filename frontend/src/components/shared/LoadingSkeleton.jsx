export function SkeletonLine({ width = "100%", height = 12 }) {
  return <div className="skeleton" style={{ width, height, borderRadius: 6 }} />
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <SkeletonLine width="40%" height={14} />
      <div style={{ height: 10 }} />
      <SkeletonLine width="80%" />
      <SkeletonLine width="60%" />
    </div>
  )
}

export function SkeletonTable({ rows = 5 }) {
  return (
    <div className="skeleton-table">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-row">
          <SkeletonLine width="18%" />
          <SkeletonLine width="30%" />
          <SkeletonLine width="12%" />
          <SkeletonLine width="15%" />
          <SkeletonLine width="10%" />
        </div>
      ))}
    </div>
  )
}

export default function LoadingSkeleton({ type = "table", rows = 5 }) {
  if (type === "cards") {
    return (
      <div className="skeleton-grid">
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    )
  }
  return <SkeletonTable rows={rows} />
}
