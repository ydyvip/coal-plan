import React, { useState, useEffect } from 'react'
import { api, subscribe, fmt } from './api'
import { EventLog } from './RunView'

export default function DebugView({ flow, tools, preselect, scn }) {
  const [node, setNode] = useState(preselect || flow.nodes[0]?.id)
  const [state, setState] = useState({ events: [], artifacts: {}, status: 'idle', err: null })
  const [ver, setVer] = useState(scn)
  useEffect(() => { if (preselect) setNode(preselect) }, [preselect])
  const n = flow.nodes.find(x => x.id === node); const spec = n && tools.find(t => t.key === n.tool)
  const go = async upto => {
    setState({ events: [], artifacts: {}, status: 'running', err: null })
    try {
      const { run_id } = await api.debug({ flow, node_id: node, upto, version: ver.v, mode: ver.m })
      const evs = []; const arts = {}
      subscribe(run_id, e => { evs.push(e); if (e.type === 'artifact') arts[e.key] = e.value; setState(s => ({ ...s, events: [...evs], artifacts: { ...arts } })) },
        () => setState(s => ({ ...s, status: evs.some(e => e.type === 'error') ? 'failed' : 'completed' })))
    } catch (e) { setState(s => ({ ...s, status: 'failed', err: JSON.stringify(e.body?.detail?.issues || e.body || e.message) })) }
  }
  return (
    <div className="debugv">
      <div className="leftcol"><div className="sec"><h3>选择节点</h3>
        <div className="field"><select value={node || ''} onChange={e => setNode(e.target.value)}>{flow.nodes.map(x => <option key={x.id} value={x.id}>{x.label}（{x.id}）</option>)}</select></div>
        <div className="seg">{[['V1', 'day_ahead', 'V1 日前'], ['V2', 'rolling', 'V2 滚动']].map(([v, m, t]) => <button key={v} className={ver.v === v ? 'on' : ''} onClick={() => setVer({ v, m })}>{t}</button>)}</div>
        <div style={{ display: 'grid', gap: 8 }}>
          <button className="btn" disabled={!n || state.status === 'running'} onClick={() => go(false)}>仅运行此节点（自动补全上游）</button>
          <button className="btn pri" disabled={!n || state.status === 'running'} onClick={() => go(true)}>运行至此节点（含全部上游，严格）</button></div>
        {state.err && <p style={{ color: 'var(--brick)', fontSize: 12 }}>{state.err}</p>}
        {n && <><h3 style={{ marginTop: 14 }}>输入参数</h3><pre style={{ font: '12px var(--mono)', margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(n.kind === 'tool' ? { tool: n.tool, ...Object.fromEntries((spec?.params || []).map(p => [p.key, n.params?.[p.key] ?? p.default])) } : { model: n.model, system_message: n.system_message }, null, 1)}</pre>
          {spec && <p style={{ fontSize: 12 }}>读取：{spec.requires.join('、') || '无'}；产出：{spec.provides.join('、')}</p>}</>}
      </div><EventLog events={state.events} /></div>
      <div className="pad">
        <h3 style={{ marginTop: 0 }}>节点输出（产出物）</h3>
        {Object.keys(state.artifacts).length === 0 && <div className="empty">运行后在此查看该节点（及补全的上游）产出的结构化数据。</div>}
        {Object.entries(state.artifacts).map(([k, v]) => <div className="card" key={k}><h4>{k}</h4>
          <pre style={{ font: '12px/1.4 var(--mono)', margin: 0, maxHeight: 280, overflow: 'auto' }}>{JSON.stringify(v, (kk, x) => Array.isArray(x) && x.length > 12 && typeof x[0] === 'number' ? `[${x.length} 个数值] ` + x.slice(0, 6).map(y => Math.round(y * 10) / 10).join(', ') + ' …' : x, 1)}</pre></div>)}
      </div>
    </div>)
}
