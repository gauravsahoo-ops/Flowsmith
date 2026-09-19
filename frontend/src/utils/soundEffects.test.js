import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { playChime } from './soundEffects'

if (!globalThis.window) {
  globalThis.window = {}
}

describe('soundEffects Suite', () => {
  let originalAudioContext

  beforeEach(() => {
    originalAudioContext = globalThis.window.AudioContext
  })

  afterEach(() => {
    globalThis.window.AudioContext = originalAudioContext
  })

  it('runs safely without error when AudioContext is missing', () => {
    delete globalThis.window.AudioContext
    delete globalThis.window.webkitAudioContext
    expect(() => playChime('success')).not.toThrow()
    expect(() => playChime('error')).not.toThrow()
  })

  it('plays ascending tones for success', () => {
    const mockSetValueAtTime = vi.fn()
    const mockRampToValue = vi.fn()
    const mockStart = vi.fn()
    const mockStop = vi.fn()
    const mockConnect = vi.fn()

    globalThis.window.AudioContext = vi.fn().mockImplementation(function() {
      return {
        currentTime: 0,
        state: 'running',
        destination: {},
        createOscillator: () => ({
          type: 'sine',
          frequency: {
            setValueAtTime: mockSetValueAtTime,
            exponentialRampToValueAtTime: mockRampToValue,
          },
          connect: mockConnect,
          start: mockStart,
          stop: mockStop,
        }),
        createGain: () => ({
          gain: {
            setValueAtTime: mockSetValueAtTime,
            exponentialRampToValueAtTime: mockRampToValue,
          },
          connect: mockConnect,
        }),
      }
    })

    playChime('success')

    expect(mockSetValueAtTime).toHaveBeenCalledWith(523.25, 0)
    expect(mockRampToValue).toHaveBeenCalledWith(783.99, 0.12)
    expect(mockStart).toHaveBeenCalled()
    expect(mockStop).toHaveBeenCalled()
  })

  it('plays descending tones for error', () => {
    const mockSetValueAtTime = vi.fn()
    const mockRampToValue = vi.fn()
    const mockStart = vi.fn()
    const mockStop = vi.fn()
    const mockConnect = vi.fn()

    globalThis.window.AudioContext = vi.fn().mockImplementation(function() {
      return {
        currentTime: 0,
        state: 'running',
        destination: {},
        createOscillator: () => ({
          type: 'sine',
          frequency: {
            setValueAtTime: mockSetValueAtTime,
            exponentialRampToValueAtTime: mockRampToValue,
          },
          connect: mockConnect,
          start: mockStart,
          stop: mockStop,
        }),
        createGain: () => ({
          gain: {
            setValueAtTime: mockSetValueAtTime,
            exponentialRampToValueAtTime: mockRampToValue,
          },
          connect: mockConnect,
        }),
      }
    })

    playChime('error')

    expect(mockSetValueAtTime).toHaveBeenCalledWith(349.23, 0)
    expect(mockRampToValue).toHaveBeenCalledWith(277.18, 0.14)
    expect(mockStart).toHaveBeenCalled()
    expect(mockStop).toHaveBeenCalled()
  })
})
