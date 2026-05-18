'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'

interface ProgressEvent {
  task_id: string
  step: number
  step_name: string
  status: 'running' | 'completed' | 'failed'
  detail: string
  elapsed_seconds: number
  timestamp: string
}

type StepStatus = 'pending' | 'running' | 'completed' | 'failed'

interface StepState {
  status: StepStatus
  detail: string
  elapsed: number
}

const STEP_NAMES = [
  'Fetch 10-K from SEC EDGAR',
  'Parse financial statements',
  'Calculate financial ratios',
  'Build RAG vector index',
  'Scan footnotes for risk signals',
  'MD&A sentiment analysis',
  'Generate Excel workbook',
]

const STEP_ICONS = ['', '', '', '', '', '', '']

function SpinnerIcon() {
  return (
    <motion.div
      animate={{ rotate: 360 }}
      transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
      className="w-5 h-5 rounded-full"
      style={{
        border: '2px solid rgba(59,130,246,0.2)',
        borderTopColor: '#3b82f6',
      }}
    />
  )
}

function CheckIcon() {
  return (
    <motion.svg
      width="20" height="20" viewBox="0 0 20 20" fill="none"
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 500, damping: 28 }}
    >
      <circle cx="10" cy="10" r="10" fill="#16a34a" fillOpacity="0.15"/>
      <motion.path
        d="M5.5 10.5l3 3 6-6"
        stroke="#22c55e"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
      />
    </motion.svg>
  )
}

function FailIcon() {
  return (
    <motion.svg
      width="20" height="20" viewBox="0 0 20 20" fill="none"
      initial={{ scale: 0 }}
      animate={{ scale: 1 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
    >
      <circle cx="10" cy="10" r="10" fill="#dc2626" fillOpacity="0.15"/>
      <path d="M7 7l6 6M13 7l-6 6" stroke="#ef4444" strokeWidth="2" strokeLinecap="round"/>
    </motion.svg>
  )
}

function PendingDot({ number }: { number: number }) {
  return (
    <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono"
      style={{ background: '#1a1a1a', border: '1px solid #2a2a2a', color: '#444' }}>
      {number}
    </div>
  )
}

function StepIcon({ status, index }: { status: StepStatus; index: number }) {
  return (
    <AnimatePresence mode="wait">
      {status === 'pending' && (
        <motion.div key="pending" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}>
          <PendingDot number={index + 1} />
        </motion.div>
      )}
      {status === 'running' && (
        <motion.div key="running" initial={{ opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.7 }} transition={{ duration: 0.2 }}>
          <SpinnerIcon />
        </motion.div>
      )}
      {status === 'completed' && (
        <motion.div key="completed" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
          <CheckIcon />
        </motion.div>
      )}
      {status === 'failed' && (
        <motion.div key="failed" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
          <FailIcon />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default function LoadingPage() {
  const params = useParams()
  const router = useRouter()
  const ticker = (params.ticker as string).toUpperCase()
  const taskId = params.taskId as string
  const searchParams = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search)
    : new URLSearchParams()
  const year = searchParams.get('year') ?? '2025'

  const [steps, setSteps] = useState<StepState[]>(
    STEP_NAMES.map(() => ({ status: 'pending' as StepStatus, detail: '', elapsed: 0 }))
  )
  const [activeDetail, setActiveDetail] = useState('')
  const [activeStep, setActiveStep] = useState(0)
  const [error, setError] = useState('')
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const wsRef = useRef<WebSocket | null>(null)

  const completedCount = steps.filter(s => s.status === 'completed').length
  const progress = completedCount / STEP_NAMES.length
  const doneRef = useRef(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const startPolling = (t: string, y: string) => {
    if (pollRef.current) return
    const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000'
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/report/${t}/10K/${y}`)
        if (res.ok) {
          const data = await res.json()
          if (data.status === 'complete') {
            clearInterval(pollRef.current!)
            doneRef.current = true
            router.push(`/analyze/${t}/report?year=${y}`)
          }
        }
      } catch { /* backend not yet ready */ }
    }, 5000)
  }

  useEffect(() => {
    const WS = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://127.0.0.1:8000'
    const ws = new WebSocket(`${WS}/ws/${taskId}`)
    wsRef.current = ws

    ws.onopen = () => setWsStatus('connected')

    ws.onclose = () => {
      setWsStatus('disconnected')
      if (doneRef.current) return
      setSteps(prev => {
        const anyProgress = prev.some(s => s.status !== 'pending')
        if (!anyProgress) {
          setError('Could not connect to the analysis server. Is the backend running?')
        } else {
          // WS dropped mid-analysis — poll the report endpoint until it's ready
          startPolling(ticker, year)
        }
        return prev
      })
    }
    ws.onerror = () => { /* close handler covers this */ }

    ws.onmessage = (e) => {
      let event: ProgressEvent
      try { event = JSON.parse(e.data) } catch { return }

      const idx = event.step - 1
      setActiveStep(idx)
      setActiveDetail(event.detail)

      setSteps(prev => {
        const next = [...prev]
        next[idx] = {
          status: event.status as StepStatus,
          detail: event.detail,
          elapsed: event.elapsed_seconds,
        }
        return next
      })

      if (event.status === 'failed') {
        setError(event.detail)
      }

      if (event.status === 'completed' && event.step === 7) {
        doneRef.current = true
        setTimeout(() => router.push(`/analyze/${ticker}/report?year=${year}`), 900)
      }
    }

    return () => {
      ws.close()
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [taskId, ticker, router])

  const handleRetry = () => router.push('/')

  return (
    <main
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: '#0a0a0a' }}
    >
      <div className="w-full max-w-xl">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-8 text-center"
        >
          <div className="flex items-center justify-center gap-2 mb-1">
            <span className="text-2xl font-mono font-semibold" style={{ color: '#f5f5f5' }}>
              {ticker}
            </span>
            <span className="text-sm rounded px-2 py-0.5"
              style={{ background: '#1a1a1a', color: '#525252', border: '1px solid #222' }}>
              10-K Analysis
            </span>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: wsStatus === 'connected' ? '#22c55e' : wsStatus === 'connecting' ? '#f59e0b' : '#ef4444' }}
            />
          </div>
          <p className="text-xs" style={{ color: '#3a3a3a' }}>
            task {taskId.slice(0, 8)}…
          </p>
        </motion.div>

        {/* Progress bar */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="mb-8"
        >
          <div className="flex justify-between text-xs mb-2" style={{ color: '#3a3a3a' }}>
            <span>{completedCount} of {STEP_NAMES.length} steps complete</span>
            <span>{Math.round(progress * 100)}%</span>
          </div>
          <div className="h-1 rounded-full overflow-hidden" style={{ background: '#1a1a1a' }}>
            <motion.div
              className="h-full rounded-full"
              style={{ background: 'linear-gradient(90deg, #2563eb, #6366f1)' }}
              initial={{ width: 0 }}
              animate={{ width: `${progress * 100}%` }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            />
          </div>
        </motion.div>

        {/* Steps list */}
        <div className="space-y-1">
          {STEP_NAMES.map((name, i) => {
            const step = steps[i]
            const isActive = step.status === 'running'
            const isDone = step.status === 'completed'
            const isFailed = step.status === 'failed'

            return (
              <motion.div
                key={name}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04, ease: 'easeOut' }}
              >
                <div
                  className="flex items-center gap-3 rounded-lg px-4 py-3 transition-all duration-200"
                  style={{
                    background: isActive ? '#0f1f3d' : isFailed ? '#1c0a0a' : 'transparent',
                    border: `1px solid ${
                      isActive ? '#2563eb33' : isFailed ? '#ef444433' : 'transparent'
                    }`,
                  }}
                >
                  {/* Icon */}
                  <div className="w-5 flex-shrink-0">
                    <StepIcon status={step.status} index={i} />
                  </div>

                  {/* Name */}
                  <span
                    className="flex-1 text-sm font-medium"
                    style={{
                      color: isFailed ? '#f87171'
                        : isActive ? '#f5f5f5'
                        : isDone ? '#a3a3a3'
                        : '#333333',
                    }}
                  >
                    {name}
                  </span>

                  {/* Elapsed time */}
                  {isDone && (
                    <motion.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="text-xs flex-shrink-0"
                      style={{ color: '#2d5a27', fontVariantNumeric: 'tabular-nums' }}
                    >
                      {step.elapsed.toFixed(1)}s
                    </motion.span>
                  )}
                </div>

                {/* Active detail row */}
                <AnimatePresence>
                  {isActive && activeDetail && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className="overflow-hidden"
                    >
                      <p
                        className="text-xs px-14 pb-2 truncate"
                        style={{ color: '#3b82f6', fontFamily: 'var(--font-geist-mono)' }}
                      >
                        {activeDetail}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )
          })}
        </div>

        {/* Error state */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-6 rounded-xl p-5"
              style={{ background: '#1c0a0a', border: '1px solid #7f1d1d44' }}
            >
              <div className="flex items-start gap-3">
                <span className="text-lg flex-shrink-0">⚠️</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium mb-1" style={{ color: '#fca5a5' }}>
                    Analysis failed
                  </p>
                  <p className="text-xs break-words" style={{ color: '#7f1d1d', fontFamily: 'var(--font-geist-mono)' }}>
                    {error}
                  </p>
                </div>
              </div>
              <button
                onClick={handleRetry}
                className="mt-4 w-full rounded-lg py-2 text-sm font-medium transition-colors"
                style={{ background: '#7f1d1d', color: '#fca5a5' }}
              >
                ← Try another ticker
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Completion flash */}
        <AnimatePresence>
          {completedCount === 7 && !error && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="mt-6 rounded-xl p-4 text-center"
              style={{ background: '#052e16', border: '1px solid #16a34a33' }}
            >
              <p className="text-sm font-medium" style={{ color: '#4ade80' }}>
                ✓ Analysis complete — loading report…
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </main>
  )
}
