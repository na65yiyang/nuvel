'use client'

import { useState, useRef, useEffect } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from 'recharts'

// ── Types ──────────────────────────────────────────────────────────────────

interface Signal {
  title: string
  level: 'critical' | 'monitor' | 'normal'
  category_label: string
  category_id: string
  explanation: string
  note_reference: string
  excerpt: string
}

interface SentimentPoint { year: string; score: number; label: string }
interface BeatMissRow {
  metric: string; consensus: string; actual: string
  result: 'beat' | 'miss' | 'inline'; surprise: string
}

interface ReportData {
  ticker: string
  company_name: string
  filing_type: string
  year: string
  filing_date: string
  price: number
  market_cap: string
  ratios: Record<string, number | null>
  ratios_history: Record<string, number[]>
  signals: Signal[]
  sentiment: SentimentPoint[]
  beat_miss: BeatMissRow[]
  status: string
}

// ── Constants ──────────────────────────────────────────────────────────────

const TABS = ['Financial Ratios', 'Risk Signals', 'MD&A Sentiment', 'Ask', 'Beat / Miss']

const RATIO_GROUPS = [
  {
    label: 'Profitability',
    rows: [
      { key: 'gross_margin',     label: 'Gross Margin',     fmt: 'pct', industry: 0.55 },
      { key: 'operating_margin', label: 'Operating Margin', fmt: 'pct', industry: 0.20 },
      { key: 'net_margin',       label: 'Net Margin',       fmt: 'pct', industry: 0.15 },
      { key: 'roa',              label: 'Return on Assets', fmt: 'pct', industry: 0.08 },
      { key: 'roe',              label: 'Return on Equity', fmt: 'pct', industry: 0.18 },
    ],
  },
  {
    label: 'Liquidity',
    rows: [
      { key: 'current_ratio', label: 'Current Ratio', fmt: 'x',   industry: 1.80 },
      { key: 'cash_ratio',    label: 'Cash Ratio',    fmt: 'x',   industry: 0.50 },
    ],
  },
  {
    label: 'Leverage & Efficiency',
    rows: [
      { key: 'debt_to_equity',         label: 'Debt / Equity',         fmt: 'x',   industry: 0.60 },
      { key: 'asset_turnover',          label: 'Asset Turnover',         fmt: 'x',   industry: 0.65 },
      { key: 'receivables_to_revenue',  label: 'Receivables / Revenue',  fmt: 'pct', industry: 0.12 },
    ],
  },
  {
    label: 'R&D & Cash Flow',
    rows: [
      { key: 'rd_to_revenue',      label: 'R&D Intensity',   fmt: 'pct', industry: 0.15 },
      { key: 'sga_to_revenue',     label: 'SG&A / Revenue',  fmt: 'pct', industry: 0.10 },
      { key: 'fcf',                label: 'Free Cash Flow',  fmt: '$b',  industry: null },
      { key: 'capex_to_revenue',   label: 'CapEx / Revenue', fmt: 'pct', industry: 0.06 },
      { key: 'goodwill_to_assets', label: 'Goodwill / Assets', fmt: 'pct', industry: 0.15 },
    ],
  },
]

const HERO_METRICS = [
  { key: 'gross_margin',    label: 'Gross Margin', fmt: 'pct', industry: 0.55, histKey: 'gross_margin' },
  { key: 'net_margin',      label: 'Net Margin',   fmt: 'pct', industry: 0.15, histKey: 'net_margin' },
  { key: 'roe',             label: 'ROE',          fmt: 'pct', industry: 0.18, histKey: 'roe' },
  { key: 'current_ratio',   label: 'Current Ratio',fmt: 'x',   industry: 1.80, histKey: 'current_ratio' },
]

const HIST_YEARS = ['FY21', 'FY22', 'FY23', 'FY24', 'FY25']

// ── Formatters ─────────────────────────────────────────────────────────────

function fmt(value: number | null | undefined, type: string): string {
  if (value == null || isNaN(value)) return '—'
  switch (type) {
    case 'pct': return `${(value * 100).toFixed(1)}%`
    case 'x':   return `${value.toFixed(2)}x`
    case '$b':  return `$${(value / 1e9).toFixed(1)}B`
    default:    return String(value)
  }
}

// ── Skeleton ───────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-lg ${className}`}
      style={{ background: '#1a1a1a' }} />
  )
}

function ReportSkeleton() {
  return (
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <Skeleton className="h-20 w-full" />
      <div className="flex gap-2"><Skeleton className="h-9 w-36" /><Skeleton className="h-9 w-32" /></div>
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-32" />)}
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  )
}

// ── Report Header ──────────────────────────────────────────────────────────

function ReportHeader({ data }: { data: ReportData }) {
  const [copied, setCopied] = useState(false)
  const critical = data.signals.filter(s => s.level === 'critical').length
  const monitor  = data.signals.filter(s => s.level === 'monitor').length

  const copy = () => {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="border-b px-6 py-5" style={{ borderColor: '#1f1f1f', background: '#0d0d0d' }}>
      <div className="max-w-6xl mx-auto">
        {/* Title row */}
        <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-mono font-bold" style={{ color: '#f5f5f5' }}>
                {data.ticker}
              </h1>
              <span className="text-lg" style={{ color: '#525252' }}>|</span>
              <span className="text-lg font-medium" style={{ color: '#a3a3a3' }}>
                {data.company_name}
              </span>
              <span className="text-xs rounded-md px-2 py-1"
                style={{ background: '#1a1a1a', color: '#525252', border: '1px solid #222' }}>
                {data.year} {data.filing_type}
              </span>
            </div>

            {/* Key metrics row */}
            <div className="flex items-center gap-5 mt-2 flex-wrap">
              <span className="text-sm font-mono" style={{ color: '#22c55e' }}>
                ${data.price?.toLocaleString()}
              </span>
              <span className="text-sm" style={{ color: '#525252' }}>
                Mkt Cap: <span style={{ color: '#a3a3a3' }}>{data.market_cap}</span>
              </span>
              <span className="text-sm" style={{ color: '#525252' }}>
                Filed: <span style={{ color: '#a3a3a3' }}>{data.filing_date}</span>
              </span>
            </div>

            {/* Signal summary */}
            {data.signals.length > 0 && (
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className="text-xs" style={{ color: '#525252' }}>
                  {data.signals.length} signals —
                </span>
                {critical > 0 && (
                  <span className="text-xs rounded px-1.5 py-0.5"
                    style={{ background: '#3d0a0a', color: '#f87171', border: '1px solid #7f1d1d44' }}>
                    ⚠ {critical} critical
                  </span>
                )}
                {monitor > 0 && (
                  <span className="text-xs rounded px-1.5 py-0.5"
                    style={{ background: '#292100', color: '#fbbf24', border: '1px solid #78350f44' }}>
                    △ {monitor} monitoring
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <a href={`/api/excel/${data.ticker}/${data.filing_type}/${data.year}`}
              className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
              style={{ background: '#111', border: '1px solid #222', color: '#a3a3a3' }}>
              <span>⬇</span> Excel
            </a>
            <button className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium"
              style={{ background: '#111', border: '1px solid #222', color: '#a3a3a3' }}>
              <span>📄</span> PDF
            </button>
            <button onClick={copy}
              className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-all"
              style={{ background: '#111', border: '1px solid #222', color: copied ? '#22c55e' : '#a3a3a3' }}>
              {copied ? '✓ Copied' : '🔗 Share'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Tab 1: Financial Ratios ────────────────────────────────────────────────

function MiniSparkline({ values }: { values: number[] }) {
  const data = values.map((v, i) => ({ y: v, x: HIST_YEARS[i] ?? `Y${i + 1}` }))
  return (
    <ResponsiveContainer width="100%" height={56}>
      <LineChart data={data}>
        <Line type="monotone" dataKey="y" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
        <XAxis dataKey="x" hide />
        <YAxis hide domain={['auto', 'auto']} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function HeroCard({
  label, value, fmt: fmtType, industry, history,
}: {
  label: string; value: number | null; fmt: string
  industry: number | null; history: number[]
}) {
  const v = value ?? 0
  const yoy = history.length >= 2
    ? (history[history.length - 1] - history[history.length - 2]) / Math.abs(history[history.length - 2])
    : null
  const isGood = yoy != null && yoy > 0
  const industryPct = industry && fmtType !== '$b'
    ? Math.min(100, (v / (industry * 2)) * 100)
    : null
  const myPct = industry && fmtType !== '$b'
    ? Math.min(100, (v / (industry * 2)) * 100)
    : null

  return (
    <div className="rounded-xl p-4 flex flex-col gap-3"
      style={{ background: '#111', border: '1px solid #1f1f1f' }}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color: '#525252' }}>{label}</span>
        {yoy != null && (
          <span className="text-xs font-mono"
            style={{ color: isGood ? '#22c55e' : '#f87171' }}>
            {isGood ? '↑' : '↓'} {Math.abs(yoy * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="text-2xl font-bold font-mono" style={{ color: '#f5f5f5' }}>
        {fmt(value, fmtType)}
      </div>
      {industry && fmtType !== '$b' && (
        <div>
          <div className="flex justify-between text-[10px] mb-1" style={{ color: '#333' }}>
            <span>Industry avg: {fmt(industry, fmtType)}</span>
          </div>
          <div className="relative h-1 rounded-full" style={{ background: '#1a1a1a' }}>
            {/* Industry marker */}
            <div className="absolute top-0 w-0.5 h-full rounded-full"
              style={{ left: '50%', background: '#333' }} />
            {/* Company value */}
            <div className="absolute top-0 h-full rounded-full transition-all"
              style={{
                width: `${myPct}%`,
                background: 'linear-gradient(90deg, #1d4ed8, #3b82f6)',
              }} />
          </div>
        </div>
      )}
      {history.length > 1 && (
        <div style={{ marginTop: -4 }}>
          <MiniSparkline values={history} />
        </div>
      )}
    </div>
  )
}

function RatioRow({
  label, value, fmtType, industry, history,
}: {
  label: string; value: number | null; fmtType: string
  industry: number | null; history: number[]
}) {
  const [open, setOpen] = useState(false)
  const v = value ?? 0
  const yoy = history.length >= 2
    ? (history[history.length - 1] - history[history.length - 2]) / Math.abs(history[history.length - 2])
    : null
  const vsIndustry = industry && fmtType !== '$b' ? v / industry : null

  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-4 py-2.5 px-3 rounded-lg text-left transition-colors hover:bg-white/[0.02]"
      >
        <span className="flex-1 text-sm" style={{ color: '#a3a3a3' }}>{label}</span>
        <span className="text-sm font-mono w-20 text-right" style={{ color: '#f5f5f5' }}>
          {fmt(value, fmtType)}
        </span>
        {yoy != null && (
          <span className="text-xs font-mono w-16 text-right"
            style={{ color: yoy >= 0 ? '#22c55e' : '#f87171' }}>
            {yoy >= 0 ? '+' : ''}{(yoy * 100).toFixed(1)}%
          </span>
        )}
        {vsIndustry != null && (
          <span className="text-[10px] rounded px-1.5 py-0.5 w-20 text-center"
            style={{
              background: vsIndustry >= 1 ? '#052e16' : '#1c0a0a',
              color: vsIndustry >= 1 ? '#22c55e' : '#f87171',
            }}>
            {vsIndustry >= 1 ? '▲' : '▼'} vs ind.
          </span>
        )}
        <span className="text-xs" style={{ color: '#333' }}>{open ? '▲' : '▼'}</span>
      </button>
      <AnimatePresence>
        {open && history.length > 1 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            style={{ overflow: 'hidden' }}
          >
            <div className="px-3 pb-3">
              <div className="rounded-lg p-3" style={{ background: '#0d0d0d', border: '1px solid #1a1a1a' }}>
                <p className="text-[10px] mb-2" style={{ color: '#333' }}>5-Year Trend</p>
                <ResponsiveContainer width="100%" height={80}>
                  <LineChart data={history.map((v, i) => ({ x: HIST_YEARS[i] ?? `Y${i+1}`, v }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
                    <XAxis dataKey="x" tick={{ fontSize: 10, fill: '#525252' }} />
                    <YAxis tick={{ fontSize: 10, fill: '#525252' }} width={40}
                      tickFormatter={v => fmt(v, fmtType)} />
                    <Tooltip
                      contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8 }}
                      labelStyle={{ color: '#a3a3a3', fontSize: 11 }}
                      formatter={(v) => [fmt(typeof v === 'number' ? v : null, fmtType), label]}
                    />
                    {industry && fmtType !== '$b' && (
                      <ReferenceLine y={industry} stroke="#333" strokeDasharray="4 4"
                        label={{ value: 'Industry', position: 'right', fontSize: 9, fill: '#444' }} />
                    )}
                    <Line type="monotone" dataKey="v" stroke="#3b82f6" strokeWidth={2}
                      dot={{ fill: '#3b82f6', r: 3 }} activeDot={{ r: 5 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function RatiosTab({ data }: { data: ReportData }) {
  const hist = data.ratios_history ?? {}
  return (
    <div className="space-y-8">
      {/* Hero cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {HERO_METRICS.map(m => (
          <HeroCard key={m.key} label={m.label} value={data.ratios[m.key] ?? null}
            fmt={m.fmt} industry={m.industry} history={hist[m.histKey] ?? []} />
        ))}
      </div>

      {/* Full ratio table */}
      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #1f1f1f' }}>
        {RATIO_GROUPS.map((group, gi) => (
          <div key={group.label}>
            <div className="px-4 py-2.5 flex items-center gap-2"
              style={{ background: '#0d0d0d', borderBottom: '1px solid #1a1a1a' }}>
              <span className="text-xs font-semibold tracking-wide uppercase"
                style={{ color: '#404040' }}>{group.label}</span>
            </div>
            <div style={{ background: '#111' }}>
              {group.rows.map(row => (
                <RatioRow key={row.key} label={row.label}
                  value={data.ratios[row.key] ?? null} fmtType={row.fmt}
                  industry={row.industry} history={hist[row.key] ?? []} />
              ))}
            </div>
            {gi < RATIO_GROUPS.length - 1 && (
              <div style={{ height: 1, background: '#1a1a1a' }} />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Tab 2: Risk Signals ────────────────────────────────────────────────────

const LEVEL_CONFIG = {
  critical: { icon: '⚠', bg: '#1c0505', border: '#7f1d1d44', badge: '#3d0a0a', badgeText: '#f87171', label: 'Critical' },
  monitor:  { icon: '△', bg: '#141000', border: '#78350f44', badge: '#292100', badgeText: '#fbbf24', label: 'Monitor' },
  normal:   { icon: '✓', bg: '#040f06', border: '#14532d44', badge: '#052e16', badgeText: '#4ade80', label: 'Normal' },
}

function SignalCard({ signal }: { signal: Signal }) {
  const [open, setOpen] = useState(false)
  const cfg = LEVEL_CONFIG[signal.level] ?? LEVEL_CONFIG.normal

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl overflow-hidden"
      style={{ background: cfg.bg, border: `1px solid ${cfg.border}` }}
    >
      <div className="p-4">
        <div className="flex items-start gap-3">
          <span className="text-xs rounded px-2 py-1 flex-shrink-0 font-medium mt-0.5"
            style={{ background: cfg.badge, color: cfg.badgeText }}>
            {cfg.icon} {cfg.label}
          </span>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-sm mb-1" style={{ color: '#f5f5f5' }}>{signal.title}</p>
            <p className="text-xs mb-2" style={{ color: '#525252' }}>{signal.note_reference}</p>
            <p className="text-sm leading-relaxed" style={{ color: '#a3a3a3' }}>{signal.explanation}</p>
          </div>
        </div>
        <button
          onClick={() => setOpen(o => !o)}
          className="mt-3 text-xs flex items-center gap-1 transition-colors"
          style={{ color: '#404040' }}
        >
          {open ? '▲ Hide' : '▼ Source excerpt'}
        </button>
      </div>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            style={{ overflow: 'hidden' }}
          >
            <div className="px-4 pb-4">
              <div className="rounded-lg px-4 py-3" style={{ background: '#0a0a0a', border: '1px solid #1a1a1a' }}>
                <p className="text-[10px] mb-1 font-mono" style={{ color: '#333' }}>
                  {signal.note_reference}
                </p>
                <p className="text-xs leading-relaxed italic" style={{ color: '#525252' }}>
                  "{signal.excerpt}"
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function SignalsTab({ data }: { data: ReportData }) {
  const order: Signal['level'][] = ['critical', 'monitor', 'normal']
  const grouped = order.map(lvl => ({
    level: lvl,
    signals: data.signals.filter(s => s.level === lvl),
  })).filter(g => g.signals.length > 0)

  return (
    <div className="space-y-6">
      {grouped.map(({ level, signals }) => (
        <div key={level}>
          <p className="text-xs font-semibold uppercase tracking-wide mb-3"
            style={{ color: '#333' }}>
            {LEVEL_CONFIG[level]?.label} ({signals.length})
          </p>
          <div className="space-y-3">
            {signals.map((s, i) => <SignalCard key={i} signal={s} />)}
          </div>
        </div>
      ))}
      {data.signals.length === 0 && (
        <p className="text-sm text-center py-12" style={{ color: '#333' }}>
          No signals found for this filing.
        </p>
      )}
    </div>
  )
}

// ── Tab 3: MD&A Sentiment ─────────────────────────────────────────────────

const CustomDot = (props: any) => {
  const { cx, cy, payload } = props
  return (
    <g>
      <circle cx={cx} cy={cy} r={6} fill="#3b82f6" stroke="#0a0a0a" strokeWidth={2} />
      <text x={cx} y={cy - 14} textAnchor="middle" fontSize={10} fill="#a3a3a3">
        {payload.label}
      </text>
    </g>
  )
}

function SentimentTab({ data }: { data: ReportData }) {
  // Backend returns a single sentiment object {tone, score (-1..1), themes, summary, year}.
  // Mock data returns an array. Normalise both into a chart-friendly array with score 0..1.
  const sentimentObj: Record<string, unknown> | null =
    data.sentiment && !Array.isArray(data.sentiment) ? data.sentiment as Record<string, unknown> : null
  const sentimentArr: Array<Record<string, unknown>> =
    Array.isArray(data.sentiment) ? (data.sentiment as unknown as Array<Record<string, unknown>>) : []

  // Normalise -1..1 → 0..1 for display
  const norm = (s: number) => Math.max(0, Math.min(1, (s + 1) / 2))

  type ChartPoint = { year: string; score: number; label: string }
  const chartData: ChartPoint[] = sentimentObj
    ? [{ year: String(sentimentObj.year ?? data.year), score: norm(Number(sentimentObj.score ?? 0)), label: String(sentimentObj.tone ?? '') }]
    : sentimentArr.map(d => ({ year: String(d.year ?? ''), score: norm(Number(d.score ?? 0)), label: String(d.label ?? '') }))

  const themes = sentimentObj ? (sentimentObj.themes as Array<{theme: string; sentiment: string; excerpt: string}> ?? []) : []
  const summary = sentimentObj ? String(sentimentObj.summary ?? '') : ''
  const tone = sentimentObj ? String(sentimentObj.tone ?? '') : ''
  const scoreDisplay = chartData[0] ? chartData[0].score : 0

  return (
    <div className="space-y-6">
      {/* Score card — shown for real single-result data */}
      {sentimentObj && (
        <div className="rounded-xl p-6" style={{ background: '#111', border: '1px solid #1f1f1f' }}>
          <div className="flex items-start justify-between gap-6">
            <div className="flex-1">
              <h3 className="text-sm font-semibold mb-1" style={{ color: '#f5f5f5' }}>MD&A Management Tone</h3>
              <p className="text-xs mb-4" style={{ color: '#525252' }}>Powered by Claude AI · {data.year} 10-K</p>
              {summary && <p className="text-sm leading-relaxed" style={{ color: '#a3a3a3' }}>{summary}</p>}
            </div>
            <div className="text-center flex-shrink-0">
              <div className="text-3xl font-mono font-bold mb-1"
                style={{ color: (scoreDisplay as number) > 0.65 ? '#22c55e' : (scoreDisplay as number) > 0.45 ? '#f5f5f5' : '#f87171' }}>
                {(scoreDisplay as number).toFixed(2)}
              </div>
              <div className="text-xs capitalize px-3 py-1 rounded-full"
                style={{ background: '#1a1a1a', color: '#a3a3a3' }}>{tone}</div>
            </div>
          </div>
          {themes.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-semibold mb-2" style={{ color: '#525252' }}>Key themes</p>
              {themes.map((t, i) => (
                <div key={i} className="rounded-lg px-3 py-2" style={{ background: '#0a0a0a', border: '1px solid #1a1a1a' }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium" style={{ color: '#f5f5f5' }}>{t.theme}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: t.sentiment === 'positive' ? '#14532d' : t.sentiment === 'negative' ? '#450a0a' : '#1a1a1a',
                               color: t.sentiment === 'positive' ? '#4ade80' : t.sentiment === 'negative' ? '#f87171' : '#737373' }}>
                      {t.sentiment}
                    </span>
                  </div>
                  {t.excerpt && <p className="text-[11px] italic" style={{ color: '#525252' }}>&ldquo;{t.excerpt}&rdquo;</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Trend chart — shown for mock array data */}
      {!sentimentObj && (
        <>
          <div className="rounded-xl p-6" style={{ background: '#111', border: '1px solid #1f1f1f' }}>
            <h3 className="text-sm font-semibold mb-1" style={{ color: '#f5f5f5' }}>MD&A Management Tone — 5-Year Trend</h3>
            <p className="text-xs mt-1 mb-6" style={{ color: '#525252' }}>
              Sentiment score 0.0 (bearish) → 1.0 (very bullish) · Powered by Claude AI
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ top: 24, right: 20, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="4 4" stroke="#1a1a1a" />
                <XAxis dataKey="year" tick={{ fontSize: 12, fill: '#525252' }} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: '#525252' }} width={32}
                  tickFormatter={v => v.toFixed(1)} />
                <Tooltip
                  contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8 }}
                  labelStyle={{ color: '#a3a3a3', fontSize: 11 }}
                  formatter={(v) => [(typeof v === 'number' ? v : 0).toFixed(2), 'Sentiment']}
                />
                <ReferenceLine y={0.5} stroke="#2a2a2a" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="score" stroke="#3b82f6" strokeWidth={2}
                  dot={<CustomDot />} activeDot={{ r: 7, fill: '#60a5fa' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-5 gap-3">
            {chartData.map((d, i) => (
              <div key={i} className="rounded-lg p-3 text-center"
                style={{ background: '#111', border: '1px solid #1a1a1a' }}>
                <div className="text-lg font-mono font-bold mb-0.5"
                  style={{ color: (d.score as number) > 0.7 ? '#22c55e' : (d.score as number) > 0.5 ? '#f5f5f5' : '#f87171' }}>
                  {(d.score as number).toFixed(2)}
                </div>
                <div className="text-[10px]" style={{ color: '#525252' }}>{String(d.year)}</div>
                <div className="text-[10px] mt-0.5" style={{ color: '#404040' }}>{String(d.label ?? '')}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── Tab 4: Ask ─────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  citations?: { section: string; page: number; excerpt: string }[]
}

type Citation = NonNullable<ChatMessage['citations']>[number]
function CitationBadge({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  return (
    <span>
      <button
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-mono mx-0.5 transition-colors"
        style={{ background: '#1a2a4a', color: '#93c5fd', border: '1px solid #1d4ed844' }}>
        {citation.section}, p.{citation.page}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-1 mx-1 rounded-lg px-3 py-2 text-xs"
              style={{ background: '#0a1628', border: '1px solid #1d4ed833', color: '#93c5fd' }}>
              <span className="font-semibold">{citation.section}</span>
              <p className="mt-1 italic text-[11px]" style={{ color: '#4a7ab8' }}>
                "{citation.excerpt}"
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  )
}

function AskTab({ ticker, year }: { ticker: string; year: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text: q }])
    setLoading(true)
    try {
      const res = await fetch(`/api/ask/${ticker}/${year}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      const data = await res.json()
      setMessages(m => [...m, {
        role: 'assistant',
        text: data.answer ?? 'No answer returned.',
        citations: data.citations ?? [],
      }])
    } catch {
      setMessages(m => [...m, { role: 'assistant', text: 'Error connecting to analysis server.' }])
    } finally {
      setLoading(false)
    }
  }

  const EXAMPLES = [
    'What are the main export control risks?',
    'How does goodwill impairment testing work here?',
    'Summarize the litigation contingencies.',
  ]

  return (
    <div className="flex flex-col" style={{ height: 520 }}>
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4">
        {messages.length === 0 ? (
          <div className="pt-8 text-center space-y-4">
            <p className="text-sm" style={{ color: '#333' }}>
              Ask anything about the {ticker} {year} 10-K filing
            </p>
            <div className="flex flex-col gap-2 items-center">
              {EXAMPLES.map(ex => (
                <button key={ex} onClick={() => { setInput(ex); }}
                  className="text-xs px-3 py-2 rounded-lg transition-colors"
                  style={{ background: '#111', border: '1px solid #1f1f1f', color: '#525252' }}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm"
                style={msg.role === 'user'
                  ? { background: '#1d4ed8', color: 'white' }
                  : { background: '#111', border: '1px solid #1f1f1f', color: '#d4d4d4' }}>
                <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-2 pt-2" style={{ borderTop: '1px solid #1a1a1a' }}>
                    <p className="text-[10px] mb-1" style={{ color: '#404040' }}>Sources:</p>
                    <div className="flex flex-wrap gap-1">
                      {msg.citations.map((c, j) => (
                        <CitationBadge key={j} citation={c} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-xl px-4 py-3" style={{ background: '#111', border: '1px solid #1f1f1f' }}>
              <div className="flex gap-1 items-center">
                {[0, 1, 2].map(i => (
                  <motion.div key={i} className="w-1.5 h-1.5 rounded-full"
                    style={{ background: '#3b82f6' }}
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about risk factors, accounting policies, guidance…"
          className="flex-1 rounded-xl px-4 py-3 text-sm outline-none"
          style={{ background: '#111', border: '1px solid #222', color: '#f5f5f5' }}
        />
        <button onClick={send} disabled={!input.trim() || loading}
          className="rounded-xl px-5 py-3 text-sm font-medium transition-all"
          style={{
            background: input.trim() && !loading ? '#2563eb' : '#1a1a1a',
            color: input.trim() && !loading ? 'white' : '#333',
          }}>
          Send
        </button>
      </div>
    </div>
  )
}

// ── Tab 5: Beat / Miss ─────────────────────────────────────────────────────

function BeatMissTab({ data }: { data: ReportData }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold" style={{ color: '#f5f5f5' }}>
          Analyst Consensus vs. Actual ({data.year})
        </h3>
        <span className="text-xs rounded px-2 py-1" style={{ background: '#1a1a1a', color: '#525252' }}>
          Source: Yahoo Finance · Prompt 11
        </span>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #1f1f1f' }}>
        {/* Header */}
        <div className="grid grid-cols-5 gap-4 px-4 py-2.5"
          style={{ background: '#0d0d0d', borderBottom: '1px solid #1a1a1a' }}>
          {['Metric', 'Consensus', 'Actual', 'Beat / Miss', 'Surprise'].map(h => (
            <span key={h} className="text-xs font-semibold" style={{ color: '#404040' }}>{h}</span>
          ))}
        </div>

        {data.beat_miss.map((row, i) => (
          <div key={i} className="grid grid-cols-5 gap-4 px-4 py-3 items-center"
            style={{
              background: i % 2 === 0 ? '#111' : '#0d0d0d',
              borderBottom: i < data.beat_miss.length - 1 ? '1px solid #1a1a1a' : 'none',
            }}>
            <span className="text-sm" style={{ color: '#a3a3a3' }}>{row.metric}</span>
            <span className="text-sm font-mono" style={{ color: '#525252' }}>{row.consensus}</span>
            <span className="text-sm font-mono font-semibold" style={{ color: '#f5f5f5' }}>{row.actual}</span>
            <span className="text-xs rounded-md px-2 py-1 w-fit"
              style={{
                background: row.result === 'beat' ? '#052e16' : row.result === 'miss' ? '#1c0a0a' : '#1a1a1a',
                color: row.result === 'beat' ? '#22c55e' : row.result === 'miss' ? '#f87171' : '#a3a3a3',
              }}>
              {row.result === 'beat' ? '✓ Beat' : row.result === 'miss' ? '✗ Miss' : '= Inline'}
            </span>
            <span className="text-sm font-mono"
              style={{ color: row.result === 'beat' ? '#22c55e' : row.result === 'miss' ? '#f87171' : '#a3a3a3' }}>
              {row.surprise}
            </span>
          </div>
        ))}
      </div>

      {/* Beat/Miss summary */}
      {data.beat_miss.length > 0 && (() => {
        const beats = data.beat_miss.filter(r => r.result === 'beat').length
        const misses = data.beat_miss.filter(r => r.result === 'miss').length
        return (
          <div className="flex gap-3 mt-2">
            <div className="rounded-lg px-4 py-2.5 flex-1 text-center"
              style={{ background: '#052e16', border: '1px solid #14532d44' }}>
              <div className="text-xl font-bold font-mono" style={{ color: '#22c55e' }}>{beats}</div>
              <div className="text-xs" style={{ color: '#166534' }}>Beats</div>
            </div>
            <div className="rounded-lg px-4 py-2.5 flex-1 text-center"
              style={{ background: '#1c0a0a', border: '1px solid #7f1d1d44' }}>
              <div className="text-xl font-bold font-mono" style={{ color: '#f87171' }}>{misses}</div>
              <div className="text-xs" style={{ color: '#7f1d1d' }}>Misses</div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────

function ReportContent({ ticker, filingType, year }: {
  ticker: string; filingType: string; year: string
}) {
  const [activeTab, setActiveTab] = useState(0)

  const { data, isLoading, error } = useQuery<ReportData>({
    queryKey: ['report', ticker, filingType, year],
    queryFn: async () => {
      const res = await fetch(
        `/api/report/${ticker}/${filingType}/${year}`
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    },
  })

  if (isLoading) return <ReportSkeleton />

  if (error || !data) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <p className="text-lg font-mono mb-2" style={{ color: '#f87171' }}>Failed to load report</p>
        <p className="text-sm" style={{ color: '#525252' }}>
          {error instanceof Error ? error.message : 'Unknown error'}
        </p>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen" style={{ background: '#0a0a0a' }}>
      <ReportHeader data={data} />

      {/* Tab bar */}
      <div className="sticky top-0 z-10 px-6 border-b"
        style={{ background: '#0a0a0a', borderColor: '#1a1a1a' }}>
        <div className="max-w-6xl mx-auto flex gap-0">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className="relative px-4 py-3.5 text-sm font-medium transition-colors"
              style={{ color: activeTab === i ? '#f5f5f5' : '#404040' }}
            >
              {tab}
              {activeTab === i && (
                <motion.div layoutId="tab-underline"
                  className="absolute bottom-0 left-0 right-0 h-0.5"
                  style={{ background: '#3b82f6' }}
                  transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            {activeTab === 0 && <RatiosTab data={data} />}
            {activeTab === 1 && <SignalsTab data={data} />}
            {activeTab === 2 && <SentimentTab data={data} />}
            {activeTab === 3 && <AskTab ticker={ticker} year={year} />}
            {activeTab === 4 && <BeatMissTab data={data} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

export default function ReportPage() {
  const params = useParams()
  const ticker = (params.ticker as string).toUpperCase()
  const searchParams = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search)
    : new URLSearchParams()
  const year = searchParams.get('year') ?? '2025'
  return <ReportContent ticker={ticker} filingType="10K" year={year} />
}
