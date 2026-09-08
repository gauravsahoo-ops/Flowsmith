import React from 'react'

const VARIANT = {
  primary: 'primary',
  ghost: 'ghost',
  danger: 'danger',
  link: 'linklike',
  quick: 'quick-action',
}

export default function Button({ variant = 'ghost', size, className = '', type = 'button', ...rest }) {
  const cls = [VARIANT[variant] || 'ghost', size === 'sm' ? 'small' : '', className]
    .filter(Boolean)
    .join(' ')
  return <button type={type} className={cls} {...rest} />
}
