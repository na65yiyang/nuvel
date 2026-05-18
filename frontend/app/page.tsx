'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'

const RECENT = ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'META']
const CURRENT_YEAR = 2025
const YEARS = Array.from({ length: 5 }, (_, i) => CURRENT_YEAR - i)

export default function Home() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)

  const [ticker, setTicker] = useState('')
  const [filingType, setFilingType] = useState<'10-K' | '10-Q'>('10-K')
  const [year, setYear] = useState(YEARS[0])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [focused, setFocused] = useState(false)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSubmit = async (sym = ticker) => {
    const t = sym.trim().toUpperCase()
    if (!t || !/^[A-Z]{1,5}$/.test(t)) {
      setError('Enter a valid ticker symbol (1–5 letters)')
      return
    }
    setError('')
    setLoading(true)
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      const res = await fetch(`${API}/api/analyze/${t}?year=${year}`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const { task_id } = await res.json()
      router.push(`/analyze/${t}/loading/${task_id}?year=${year}`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to start analysis'
      setError(msg)
      setLoading(false)
    }
  }

  return (
    <main
      className="min-h-screen flex flex-col items-center justify-center px-4 relative overflow-hidden"
      style={{
        background:
          'radial-gradient(ellipse 90% 55% at 50% -5%, rgba(59,130,246,0.09) 0%, transparent 65%), #0a0a0a',
      }}
    >
      {/* Subtle grid texture */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.025]"
        style={{
          backgroundImage:
            'linear-gradient(#ffffff 1px, transparent 1px), linear-gradient(90deg, #ffffff 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="mb-14 text-center"
      >
        <div className="flex items-center justify-center gap-2.5 mb-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shadow-lg"
            style={{ background: 'linear-gradient(135deg, #2563eb 0%, #6366f1 100%)' }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <polyline
                points="1,12 5,7 8,9.5 11,5 15,8"
                stroke="white"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
          </div>
          <span className="text-[22px] font-semibold tracking-tight" style={{ color: '#f5f5f5' }}>
            Nuvel
          </span>
        </div>
        <p className="text-sm" style={{ color: '#404040' }}>
          AI-powered earnings analysis for retail investors
        </p>
      </motion.div>

      {/* Search card */}
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-2xl"
      >
        {/* Input */}
        <div
          className="relative flex items-center rounded-xl transition-all duration-200"
          style={{
            background: '#111111',
            border: `1px solid ${focused ? '#3b82f6' : '#222222'}`,
            boxShadow: focused
              ? '0 0 0 3px rgba(59,130,246,0.12), 0 1px 3px rgba(0,0,0,0.5)'
              : '0 1px 3px rgba(0,0,0,0.4)',
          }}
        >
          {/* Search icon */}
          <div className="pl-4 pr-2 flex-shrink-0 transition-colors"
            style={{ color: focused ? '#3b82f6' : '#3a3a3a' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
          </div>

          <input
            ref={inputRef}
            type="text"
            value={ticker}
            onChange={e => { setTicker(e.target.value.toUpperCase()); setError('') }}
            onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="Enter ticker symbol — NVDA, AAPL, MSFT…"
            maxLength={5}
            spellCheck={false}
            autoComplete="off"
            className="flex-1 bg-transparent py-4 text-lg outline-none placeholder:select-none"
            style={{
              color: '#f5f5f5',
              fontFamily: 'var(--font-geist-mono)',
              letterSpacing: '0.06em',
            }}
          />

          {/* Analyze button */}
          <AnimatePresence>
            {ticker && (
              <motion.button
                key="analyze-btn"
                initial={{ opacity: 0, scale: 0.88, x: 6 }}
                animate={{ opacity: 1, scale: 1, x: 0 }}
                exit={{ opacity: 0, scale: 0.88, x: 6 }}
                transition={{ duration: 0.15, ease: 'easeOut' }}
                onClick={() => handleSubmit()}
                disabled={loading}
                className="mr-2.5 flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium"
                style={{
                  background: loading ? '#1e3a6e' : '#2563eb',
                  color: 'white',
                  flexShrink: 0,
                  cursor: loading ? 'not-allowed' : 'pointer',
                }}
                whileHover={loading ? {} : { background: '#1d4ed8' }}
                whileTap={loading ? {} : { scale: 0.97 }}
              >
                {loading ? (
                  <>
                    <span
                      className="w-3.5 h-3.5 rounded-full border-2 animate-spin"
                      style={{ borderColor: 'rgba(255,255,255,0.25)', borderTopColor: 'white' }}
                    />
                    Analyzing
                  </>
                ) : (
                  <>
                    Analyze
                    <kbd className="text-[10px] opacity-50 font-mono tracking-wide">↵</kbd>
                  </>
                )}
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        {/* Error message */}
        <AnimatePresence>
          {error && (
            <motion.p
              initial={{ opacity: 0, height: 0, marginTop: 0 }}
              animate={{ opacity: 1, height: 'auto', marginTop: 8 }}
              exit={{ opacity: 0, height: 0, marginTop: 0 }}
              className="text-xs px-1"
              style={{ color: '#f87171', overflow: 'hidden' }}
            >
              {error}
            </motion.p>
          )}
        </AnimatePresence>

        {/* Controls */}
        <div className="mt-4 flex items-center gap-2.5 flex-wrap">
          {/* Filing type toggle */}
          <div
            className="flex items-center rounded-lg p-[3px]"
            style={{ background: '#111111', border: '1px solid #222222' }}
          >
            {(['10-K', '10-Q'] as const).map(type => (
              <button
                key={type}
                onClick={() => setFilingType(type)}
                className="relative rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors"
                style={{ color: filingType === type ? '#f5f5f5' : '#525252' }}
              >
                {filingType === type && (
                  <motion.span
                    layoutId="filing-active"
                    className="absolute inset-0 rounded-md"
                    style={{ background: '#1e3a6e', border: '1px solid #2563eb33' }}
                    transition={{ type: 'spring', stiffness: 500, damping: 38 }}
                  />
                )}
                <span className="relative z-10">
                  {type === '10-K' ? '10-K Annual' : '10-Q Quarterly'}
                </span>
              </button>
            ))}
          </div>

          {/* Year dropdown */}
          <div className="relative">
            <select
              value={year}
              onChange={e => setYear(Number(e.target.value))}
              className="appearance-none rounded-lg px-3 py-1.5 pr-7 text-sm font-medium outline-none cursor-pointer"
              style={{
                background: '#111111',
                border: '1px solid #222222',
                color: '#a3a3a3',
              }}
            >
              {YEARS.map(y => (
                <option key={y} value={y} style={{ background: '#111111' }}>
                  FY {y}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2"
              style={{ color: '#525252' }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.5">
                <path d="m6 9 6 6 6-6"/>
              </svg>
            </div>
          </div>
        </div>

        {/* Recent analysis chips */}
        <div className="mt-8 flex items-center gap-2 flex-wrap">
          <span className="text-xs mr-0.5" style={{ color: '#333333' }}>Recent</span>
          {RECENT.map((sym, i) => (
            <motion.button
              key={sym}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.22 + i * 0.04, ease: 'easeOut' }}
              onClick={() => { setTicker(sym); handleSubmit(sym) }}
              className="rounded-md px-2.5 py-1 text-xs font-mono font-medium transition-all"
              style={{
                background: '#111111',
                border: '1px solid #1e1e1e',
                color: '#525252',
              }}
              whileHover={{
                borderColor: '#3b82f633',
                color: '#93c5fd',
                backgroundColor: '#0f1f3d',
              }}
              whileTap={{ scale: 0.95 }}
            >
              {sym}
            </motion.button>
          ))}
        </div>
      </motion.div>

      {/* Footer */}
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.7 }}
        className="absolute bottom-7 text-[11px]"
        style={{ color: '#262626' }}
      >
        SEC EDGAR · AlphaVantage · Claude AI · Nuvel v0.1
      </motion.p>
    </main>
  )
}
