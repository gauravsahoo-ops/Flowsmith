import React from 'react'

export default function Input({ search = false, value, onChange, onClear, className = '', placeholder, ...rest }) {
  if (!search) {
    return <input className={className} value={value} onChange={onChange} placeholder={placeholder} {...rest} />
  }
  const hasValue = value !== undefined && value !== null && String(value) !== ''
  return (
    <div className="input-search">
      <span className="is-icon" aria-hidden="true">🔍</span>
      <input
        className={className}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        {...rest}
      />
      {hasValue && onClear && (
        <button type="button" className="is-clear" aria-label="Clear search" onClick={onClear}>
          ✕
        </button>
      )}
    </div>
  )
}
