import React, { useState, useRef, useLayoutEffect, useEffect } from 'react'
import { createPortal } from 'react-dom'

export default function Tooltip({ label, children, placement = 'bottom' }) {
  const [show, setShow] = useState(false)
  const [ready, setReady] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const [arrowPos, setArrowPos] = useState(null)
  const [actualPlacement, setActualPlacement] = useState(placement)
  const targetRef = useRef(null)
  const tipRef = useRef(null)
  const timer = useRef(null)

  const open = () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setShow(true)
    }, 120)
  }

  const close = () => {
    clearTimeout(timer.current)
    setShow(false)
    setReady(false)
  }

  useLayoutEffect(() => {
    if (!show || !targetRef.current || !tipRef.current) return

    const targetEl = targetRef.current
    const tipEl = tipRef.current
    const r = targetEl.getBoundingClientRect()
    const tip = tipEl.getBoundingClientRect()

    let effectivePlacement = placement
    // Dynamic flip if offscreen vertically
    if (placement === 'top' && r.top - tip.height - 8 < 0) {
      effectivePlacement = 'bottom'
    } else if (placement === 'bottom' && r.bottom + 8 + tip.height > window.innerHeight - 8) {
      effectivePlacement = 'top'
    }

    // Horizontal centering & viewport edge clamping
    const halfTip = tip.width / 2
    const targetCenter = r.left + r.width / 2
    let centerLeft = targetCenter

    const minLeft = halfTip + 8
    const maxLeft = window.innerWidth - halfTip - 8
    if (minLeft <= maxLeft) {
      centerLeft = Math.max(minLeft, Math.min(centerLeft, maxLeft))
    }

    // Offset of the arrow relative to the tooltip box
    const arrowOffset = targetCenter - (centerLeft - halfTip)
    const clampedArrow = Math.max(10, Math.min(tip.width - 10, arrowOffset))

    const top = effectivePlacement === 'bottom' ? r.bottom + 8 : r.top - tip.height - 8

    setActualPlacement(effectivePlacement)
    setPos({ top, left: centerLeft })
    setArrowPos(clampedArrow)
    setReady(true)
  }, [show, placement, label])

  useEffect(() => {
    if (!show) return
    const handleScrollOrResize = () => {
      close()
    }
    window.addEventListener('scroll', handleScrollOrResize, true)
    window.addEventListener('resize', handleScrollOrResize)
    return () => {
      window.removeEventListener('scroll', handleScrollOrResize, true)
      window.removeEventListener('resize', handleScrollOrResize)
    }
  }, [show])

  useEffect(() => {
    return () => clearTimeout(timer.current)
  }, [])

  if (!label) return children

  const child = React.isValidElement(children)
    ? React.cloneElement(children, {
        'aria-label': children.props['aria-label'] || children.props.title || (typeof label === 'string' ? label : undefined),
        title: undefined,
      })
    : children

  const tooltipPortal =
    show && typeof document !== 'undefined' && document.body
      ? createPortal(
          <div
            ref={tipRef}
            className={`tooltip-box placement-${actualPlacement} ${ready ? 'show' : ''}`}
            style={{
              top: `${pos.top}px`,
              left: `${pos.left}px`,
              transform: 'translateX(-50%)',
              opacity: ready ? 1 : 0,
              '--arrow-left': arrowPos !== null ? `${arrowPos}px` : '50%',
            }}
            role="tooltip"
          >
            {label}
          </div>,
          document.body
        )
      : null

  return (
    <span
      className="tooltip"
      ref={targetRef}
      onMouseEnter={open}
      onMouseLeave={close}
      onFocus={open}
      onBlur={close}
    >
      {child}
      {tooltipPortal}
    </span>
  )
}
