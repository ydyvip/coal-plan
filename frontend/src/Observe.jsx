import React, { useEffect, useState } from 'react'
import { api, fmt } from './api'
import { eventLine } from './RunView'

function Gantt({ events }) {
  const spans = {}
  events.forEach(e => { if (e.type === 'agent_start') spans[e.agent] = { s: e.t, label: e.label }; if (e.type === 'agent_end' && spans[e.agent]) { spans[e.agent].e = e.t; spans[e.agent].ok = e.ok } })
  const list = Object.entries(spans), T = Math.max(...list.map(([, v]) => v.e ?? v.s), 0.001)
  return <div className="gantt">{list.map(([id, v]) => <div className="row" key={id}><div className="lab" title={id}>{v.label}</div>
    <div className="trk"><div className="bar" style={{ left: `${v.s / T * 100}%`, width: `${Math.max(((v.e ?? v.s) - v.s) / T * 100, 0.8)}%`, background: v.ok === false ? 'var(--brick)' : 'var(--steel)' }} /></div>
    <div style={{ width: 70, textAlign: 'right', fontFamily: 'var(--mono)', fontSize: 11 }}>{(((v.e ?? v.s) - v.s) * 1000).toFixed(1)} ms</div></div>)}</div>
}

export default function Observe({ refreshKey }) {
  const [runs, setRuns] = useState([]), [sel, setSel] = useState(null), [rec, setRec] = useState(null), [cmp, setCmp] = useState([]), [cmpRecs, setCmpRecs] = useState([])
  useEffect(() => { api.runs().then(setRuns) }, [refreshKey])
  useEffect(() => { if (sel) api.getRun(sel).then(setRec) }, [sel])
  useEffect(() => { Promise.all(cmp.map(api.getRun)).then(setCmpRecs) }, [cmp])
  const toggle = id => setCmp(c => c.includes(id) ? c.filter(x => x !== id) : [...c, id].slice(-2))
  return (
    <div className="observe">
      <div className="leftcol">
        <div className="sec"><h3 style={{ margin: 0 }}>运行记录（{runs.length}）</h3><span style={{ fontSize: 12, color: 'var(--muted)' }}>勾选两条可对比</span></div>
        {runs.map(r => <div key={r.id} className={`runrow ${sel === r.id ? 'on' : ''}`} onClick={() => setSel(r.id)}>
          <input type="checkbox" checked={cmp.includes(r.id)} onChange={() => toggle(r.id)} onClick={e => e.stopPropagation()} style={{ float: 'right' }} />
          <b style={{ fontSize: 13 }}>{r.team}</b><br />
          <span className={`chip ${r.status === 'completed' ? 'ok' : 'err'}`}>{r.status}</span><span className="chip">{r.version}</span><span className="chip">{r.mode}</span>{r.kind === 'debug' && <span className="chip warn">调试</span>}<br />
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>{new Date(r.created * 1000).toLocaleTimeString()} · {(r.seconds * 1000).toFixed(0)} ms · {r.summary.cost_total ? fmt(r.summary.cost_total) + ' 元' : '—'}</span></div>)}
        {runs.length === 0 && <div className="empty">还没有运行记录</div>}
      </div>
      <div className="pad">
        {cmpRecs.length === 2 && <div className="card"><h4>运行对比</h4><table className="t"><thead><tr><th>指标</th>{cmpRecs.map(r => <th key={r.id}>{r.id} ({r.version})</th>)}<th>差</th></tr></thead><tbody>
          {[['总成本 元', r => r.summary.cost_total], ['求解用时 s', r => r.summary.solve_seconds], ['约束通过率', r => r.summary.pass_rate], ['总耗时 s', r => r.seconds]].map(([n, f]) => {
            const [x, y] = cmpRecs.map(f); return <tr key={n}><td>{n}</td><td>{x == null ? '—' : fmt(x, x < 10 ? 4 : 0)}</td><td>{y == null ? '—' : fmt(y, y < 10 ? 4 : 0)}</td><td>{x != null && y != null ? fmt(y - x, Math.abs(y - x) < 10 ? 4 : 0) : '—'}</td></tr>
          })}</tbody></table>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 0 }}>组件摘要 {cmpRecs[0].digest} / {cmpRecs[1].digest}{cmpRecs[0].digest === cmpRecs[1].digest ? '（同一编排）' : '（编排不同）'}。</p></div>}
        {!rec ? <div className="empty">选择左侧一条运行记录，查看时间线、优化调用记录与完整事件。</div> : <>
          <div className="card"><h4>{rec.team} · {rec.id}</h4>
            <dl className="kv"><dt>状态</dt><dd>{rec.status}</dd><dt>总耗时</dt><dd>{(rec.seconds * 1000).toFixed(0)} ms</dd><dt>组件摘要</dt><dd>{rec.digest}</dd><dt>数据版本/模式</dt><dd>{rec.version} / {rec.mode}{rec.strict ? '' : '（调试·非严格）'}</dd>
              <dt>求解</dt><dd>{rec.summary.status || '—'} · 成本 {rec.summary.cost_total ? fmt(rec.summary.cost_total) : '—'} 元 · 校验 {rec.summary.pass_rate != null ? (rec.summary.pass_rate * 100).toFixed(1) + '%' : '—'}</dd></dl></div>
          <div className="card"><h4>智能体时间线</h4><Gantt events={rec.events} /></div>
          <div className="card"><h4>工具 / 优化器调用记录</h4><table className="t"><thead><tr><th>智能体</th><th>工具</th><th>产出</th><th>ms</th><th>摘要</th></tr></thead><tbody>
            {rec.events.filter(e => e.type === 'tool_call').map(e => <tr key={e.seq}><td>{e.agent}</td><td>{e.tool}</td><td>{e.provides.join(',')}</td><td>{(e.seconds * 1000).toFixed(1)}</td><td style={{ textAlign: 'left', fontFamily: 'var(--font)', maxWidth: 380 }}>{e.summary.slice(0, 90)}</td></tr>)}</tbody></table>
            {rec.events.filter(e => e.type === 'solver_call').map(e => <p key={e.seq} style={{ fontSize: 12, margin: '6px 0 0' }}>求解器调用：{e.solver} · 起始 {e.start_hour} 时 · 时段 {e.n_hours} · 煤价系数 {e.price_factor} · 时限 {e.time_limit}s</p>)}</div>
          <div className="card"><h4>完整事件（{rec.events.length}）</h4><div className="scroll" style={{ font: '12px/1.5 var(--mono)' }}>{rec.events.map(e => <div key={e.seq} className="ev"><span className="tt">{e.t.toFixed(3)}s </span>{eventLine(e)}</div>)}</div></div>
          <details className="card"><summary>agentTeamComponent（本次运行使用的序列化组件）</summary>
            <pre style={{ font: '12px/1.4 var(--mono)', maxHeight: 340, overflow: 'auto' }}>{JSON.stringify(rec.component, null, 2)}</pre></details></>}
      </div>
    </div>)
}
