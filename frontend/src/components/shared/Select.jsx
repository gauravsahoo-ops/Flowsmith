import React from 'react'
import SearchableSelect from '../SearchableSelect'

export default function Select({
  searchable = true,
  options = [],
  value,
  onChange,
  placeholder,
  disabled,
  clearable = true,
  loading,
  className,
  ...rest
}) {
  if (!searchable) {
    return (
      <select
        className={className}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        {...rest}
      >
        {placeholder && <option value="" disabled>{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }
  return (
    <SearchableSelect
      value={value}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      disabled={disabled}
      clearable={clearable}
      loading={loading}
    />
  )
}
