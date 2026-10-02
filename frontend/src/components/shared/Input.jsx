import React from 'react'

export default function Input({ search = false, value, onChange, onClear, className = '', placeholder, ...rest }) {
  if (!search) {
    return <input className={className} value={value} onChange={onChange} placeholder={placeholder} {...rest} />
  }
  const hasValue = value !== undefined && value !== null && String(value) !== ''
  return (
    <div className="input-search">
      <span className="is-icon" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </span>
      <input
        className={className}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        {...rest}
      />
      {hasValue && onClear && (
        <button type="button" className="is-clear" aria-label="Clear search" onClick={onClear}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  )
}
