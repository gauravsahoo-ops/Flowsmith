import React, { useState, useRef, useCallback } from 'react'

export default function Tooltip({ label, children, placement = 'top' }) {
  const [show, setShow] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const ref = useRef(null)
  const timer = useRef(null)

  const place = useCallback(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const boxW = 220
    let left = r.left + r.width / 2 - boxW / 2
    left = Math.max(8, Math.min(left, window.innerWidth - boxW - 8))
    const top = placement === 'top' ? r.top - 32 : r.bottom + 8
    setPos({ top, left })
  }, [placement])

  const open = () => {
    timer.current = setTimeout(() => {
      place()
      setShow(true)
    }, 180)
  }
  const close = () => {
    clearTimeout(timer.current)
    setShow(false)
  }

  const child = React.cloneElement(children, {
    onMouseEnter: open,
    onMouseLeave: close,
    onFocus: open,
    onBlur: close,
    'aria-label': children.props['aria-label'] || label,
    title: children.props.title || label,
  })

  return (
    <span className="tooltip" ref={ref}>
      {child}
      {show && (
        <span className="tooltip-box show" style={{ top: pos.top, left: pos.left }} role="tooltip">
          {label}
        </span>
      )}
    </span>
  )
}
