import React, { useEffect, useRef, useState, useCallback } from 'react'
import { api, subscribe } from './api'
import { FlowCanvas, Inspector, Palette } from './Builder'
import RunView from './RunView'
import DebugView from './DebugView'
import Observe from './Observe'

function JsonDrawer({ comp, flow, setFlow, issues, onClose }) {
  const [text, setText] = useState(''), [dirty, setDirty] = useState(false), [msg, setMsg] = useState('')
  useEffect(() => { if (!dirty) setText(comp ? JSON.stringify(comp, null, 2) : '') }, [comp, dirty])
  const apply = async () => {
    try {
      const positions = Object.fromEntries(flow.nodes.map(n => [n.id, n.position]))
      const { flow: f } = await api.decompile(JSON.parse(text), positions); setFlow(f); setDirty(false); setMsg('已应用到画布')
    } catch (e) { setMsg('应用失败：' + (e.body?.detail || e.message)) }
  }
  return (
    <div className="drawer">
      <div className="hd"><b>agentTeamComponent</b><span className="chip">{comp?.provider?.split('.').pop() || '—'}</span>
        {comp ? <span className="chip ok">编译通过</span> : issues.some(i => i.level === 'error') ? <span className="chip err">存在错误，无法编译</span> : <span className="chip">编译中…</span>}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>{msg}</span>
        <button className="btn sm" onClick={() => navigator.clipboard?.writeText(text)}>复制</button>
        <button className="btn sm" onClick={() => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' })); a.download = `${flow.team.name}.component.json`; a.click() }}>下载</button>
        <button className="btn sm" disabled={!dirty} onClick={apply}>应用到画布</button>
        <button className="btn sm" onClick={onClose}>收起</button></div>
      <textarea value={text} spellCheck={false} onChange={e => { setText(e.target.value); setDirty(true); setMsg('') }} />
    </div>)
}

export default function App() {
  const [tab, setTab] = useState('build')
  const [tools, setTools] = useState([]), [tpls, setTpls] = useState([]), [saved, setSaved] = useState([])
  const [flow, setFlow] = useState(null), [selected, setSelected] = useState(null)
  const [issues, setIssues] = useState([]), [comp, setComp] = useState(null), [drawer, setDrawer] = useState(true)
  const [scn, setScn] = useState({ v: 'V1', m: 'day_ahead' })
  const [run, setRun] = useState({ id: null, events: [], status: 'idle', artifacts: {} })
  const [runsKey, setRunsKey] = useState(0), [debugNode, setDebugNode] = useState(null), [toast, setToast] = useState('')
  const timer = useRef()

  useEffect(() => { Promise.all([api.tools(), api.templates(), api.listWs()]).then(([t, p, w]) => { setTools(t); setTpls(p); setSaved(w); setFlow(p[0].flow) }) }, [])
  // 编辑后自动校验 + 编译（防抖）
  useEffect(() => {
    if (!flow) return; clearTimeout(timer.current)
    timer.current = setTimeout(async () => { try { const r = await api.compile(flow); setIssues(r.issues); setComp(r.component) } catch { } }, 300)
    return () => clearTimeout(timer.current)
  }, [flow])
  const note = m => { setToast(m); setTimeout(() => setToast(''), 2400) }

  const loadTemplate = id => {
    setRun({ id: null, events: [], status: 'idle', artifacts: {} })
    const t = tpls.find(x => x.id === id); if (t) { setFlow(JSON.parse(JSON.stringify(t.flow))); setSelected(null); note('已载入模板：' + t.name); return }
    api.getWs(id).then(w => { setFlow(w.flow); setSelected(null); note('已载入：' + w.name) })
  }
  const save = async () => { await api.saveWs(flow.team.name, flow.team.label || flow.team.name, flow); setSaved(await api.listWs()); note('已保存到工作区：' + flow.team.name) }
  const startRun = async () => {
    setRun({ id: null, events: [], status: 'running', artifacts: {} })
    try {
      const { run_id } = await api.run({ flow, version: scn.v, mode: scn.m })
      const evs = [], arts = {}
      subscribe(run_id, e => { evs.push(e); if (e.type === 'artifact') arts[e.key] = e.value; setRun({ id: run_id, events: [...evs], status: 'running', artifacts: { ...arts } }) },
        () => { setRun(r => ({ ...r, status: evs.some(e => e.type === 'error') ? 'failed' : 'completed' })); setRunsKey(k => k + 1) })
    } catch (e) { setRun({ id: null, events: [], status: 'failed', artifacts: {} }); note('无法启动：' + JSON.stringify(e.body?.detail?.issues?.map(i => i.msg) || e.body || e.message)) }
  }
  if (!flow) return <div className="empty">正在加载…</div>
  const errs = issues.filter(i => i.level === 'error').length
  const tabs = [['build', '编排', '拖拽 · 表单'], ['debug', '调试', '单节点'], ['run', '运行', '实时轨迹'], ['obs', '观测', '记录 · 对比']]
  return (
    <div className="app">
      <nav className="rail" aria-label="主导航">
        <div className="brand">CoalPlan Studio<small>煤电机组智能排程 · 多智能体编排台</small></div>
        {tabs.map(([k, n, s]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}<br /><small style={{ opacity: .65, fontSize: 11 }}>{s}</small></button>)}
      </nav>
      <div className="main">
        <header className="topbar">
          <h1>{flow.team.label || flow.team.name}</h1>
          <select aria-label="载入模板或已保存团队" value="" onChange={e => e.target.value && loadTemplate(e.target.value)} className="btn">
            <option value="">载入模板 / 已保存…</option>
            <optgroup label="预置模板">{tpls.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>
            {saved.length > 0 && <optgroup label="已保存">{saved.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</optgroup>}</select>
          <span className={`chip ${errs ? 'err' : 'ok'}`}>{errs ? `${errs} 个错误` : '校验通过'}</span>
          <span className="chip">{flow.nodes.length} 智能体 · {flow.edges.length} 连线</span>
          <span className="sp" />
          {tab === 'build' && !drawer && <button className="btn" onClick={() => setDrawer(true)}>查看 JSON</button>}
          <button className="btn" onClick={save}>保存</button>
          <button className="btn pri" disabled={errs > 0} onClick={() => { setTab('run'); startRun() }}>运行</button>
          {toast && <span className="chip warn" role="status">{toast}</span>}
        </header>
        <div className="content">
          {tab === 'build' && <div className="builder">
            <Palette tools={tools} />
            <div className="canvaswrap"><FlowCanvas flow={flow} setFlow={setFlow} tools={tools} selected={selected} setSelected={setSelected} issues={issues} />
              {drawer && <JsonDrawer comp={comp} flow={flow} setFlow={setFlow} issues={issues} onClose={() => setDrawer(false)} />}</div>
            <Inspector flow={flow} setFlow={setFlow} tools={tools} selected={selected} issues={issues} onDebug={id => { setDebugNode(id); setTab('debug') }} /></div>}
          {tab === 'debug' && <DebugView flow={flow} tools={tools} preselect={debugNode} scn={scn} />}
          {tab === 'run' && <RunView flow={flow} setFlow={setFlow} tools={tools} issues={issues} run={run} startRun={startRun} scn={scn} setScn={setScn} />}
          {tab === 'obs' && <Observe refreshKey={runsKey} />}
        </div>
      </div>
    </div>)
}
