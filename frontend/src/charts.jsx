import React from 'react'
const COLORS = ['#2f6f8f', '#b9720f', '#4b4a8f', '#0e7c66']
// 通用折线/面积图：series=[{name,values,color,dash,area}]，lockedTo=前 N 点视为已执行（灰底）
export function LineChart({ series, height = 240, yMin, yMax, lockedTo = 0, unit = 'MW', stacked = false, marks = [] }) {
  const W = 760, H = height, m = { l: 48, r: 14, t: 30, b: 26 }
  const n = Math.max(...series.map(s => s.values.length))
  const all = series.flatMap(s => s.values.filter(v => v != null))
  const lo = yMin ?? Math.floor(Math.min(...all) / 50) * 50, hi = yMax ?? Math.ceil(Math.max(...all) / 50) * 50
  const x = i => m.l + (W - m.l - m.r) * i / (n - 1), y = v => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo || 1))
  const path = vs => vs.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const ticks = 5, ys = Array.from({ length: ticks + 1 }, (_, i) => lo + (hi - lo) * i / ticks)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label="时序曲线">
      {lockedTo > 0 && <g><rect x={m.l} y={m.t} width={x(lockedTo - 1) - m.l + (x(1) - x(0)) / 2} height={H - m.t - m.b} fill="#8aa1ab" opacity=".16" />
        <text x={m.l + 6} y={m.t + 14} fontSize="11" fill="currentColor" opacity=".6">已执行 · 锁定</text></g>}
      {ys.map((v, i) => <g key={i}><line x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} stroke="currentColor" opacity=".12" />
        <text x={m.l - 6} y={y(v) + 4} fontSize="11" textAnchor="end" fill="currentColor" opacity=".7">{Math.round(v)}</text></g>)}
      {Array.from({ length: n }, (_, i) => i % 3 === 0 && <text key={i} x={x(i)} y={H - 8} fontSize="11" textAnchor="middle" fill="currentColor" opacity=".7">{String(i).padStart(2, '0')}</text>)}
      {marks.map((k, i) => <rect key={i} x={x(k) - 5} y={m.t} width="10" height={H - m.t - m.b} fill="#9b2f3c" opacity=".1" />)}
      {series.map((s, i) => <g key={s.name}>
        {s.area && <path d={path(s.values) + `L${x(n - 1)},${y(lo)}L${x(0)},${y(lo)}Z`} fill={s.color || COLORS[i]} opacity=".12" />}
        <path d={path(s.values)} fill="none" stroke={s.color || COLORS[i % 4]} strokeWidth={s.w || 2} strokeDasharray={s.dash} />
      </g>)}
      <text x={m.l} y={H - 0} fontSize="0" />
      {series.map((s, i) => <g key={'l' + s.name} transform={`translate(${W - m.r - (series.length > 3 ? 108 : 150) * (series.length - i)},4)`}>
        <line x2="16" y1="4" y2="4" stroke={s.color || COLORS[i % 4]} strokeWidth="2.5" strokeDasharray={s.dash} />
        <text x="21" y="8" fontSize="11" fill="currentColor">{s.name}</text></g>)}
      <text x={4} y={14} fontSize="11" fill="currentColor" opacity=".6">{unit}</text>
    </svg>)
}
export function Bars({ items, color = '#2f6f8f' }) {   // 约束通过率等水平条
  return <div>{items.map(it => <div key={it.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '3px 0' }}>
    <span style={{ width: 90 }}>{it.label}</span>
    <div style={{ flex: 1, height: 10, background: '#8aa1ab26', borderRadius: 3 }}><div style={{ width: `${it.pct}%`, height: '100%', background: it.pct === 100 ? '#0e7c66' : '#9b2f3c', borderRadius: 3 }} /></div>
    <span style={{ width: 64, textAlign: 'right', fontFamily: 'var(--mono)' }}>{it.text}</span></div>)}</div>
}
