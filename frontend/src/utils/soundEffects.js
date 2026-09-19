/**
 * Native Web Audio Chime Generator
 * Provides subtle audio feedback for long-running workflows with zero external audio assets.
 */

export function playChime(type = 'success') {
  try {
    const win = typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis.window : null)
    if (!win) return
    const AudioCtx = win.AudioContext || win.webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {})
    }
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    const now = ctx.currentTime
    if (type === 'success') {
      // Soft ascending chime: C5 (523.25Hz) -> G5 (783.99Hz)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(523.25, now)
      osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.12)
      gain.gain.setValueAtTime(0.06, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45)
      osc.start(now)
      osc.stop(now + 0.46)
    } else {
      // Subtle alert: F4 (349.23Hz) -> Db4 (277.18Hz)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(349.23, now)
      osc.frequency.exponentialRampToValueAtTime(277.18, now + 0.14)
      gain.gain.setValueAtTime(0.06, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4)
      osc.start(now)
      osc.stop(now + 0.41)
    }
  } catch {
    /* Silent fallback if Web Audio is blocked or not available */
  }
}
