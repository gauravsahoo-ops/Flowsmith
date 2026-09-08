export default function PageHeader({ title, description, actions, breadcrumbs, children }) {
  return (
    <div className="page-header">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav className="page-breadcrumbs" aria-label="Breadcrumb">
          {breadcrumbs.map((bc, i) => (
            <span key={i} className="breadcrumb-item">
              {bc.href ? <a href={bc.href}>{bc.label}</a> : <span>{bc.label}</span>}
              {i < breadcrumbs.length - 1 && <span className="breadcrumb-sep">/</span>}
            </span>
          ))}
        </nav>
      )}
      <div className="page-header-row">
        <div className="page-header-text">
          <h1 className="page-title">{title}</h1>
          {description && <p className="page-description">{description}</p>}
        </div>
        {actions && <div className="page-header-actions">{actions}</div>}
      </div>
      {children}
    </div>
  )
}
