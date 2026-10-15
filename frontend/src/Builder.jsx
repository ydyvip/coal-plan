import React, { useCallback, useMemo, useRef, useState, useEffect } from 'react'
import { ReactFlow, ReactFlowProvider, Background, Controls, Handle, Position, MarkerType, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from './api'

const LLM_COLOR = '#6a4c93'

function AgentNode({ data }) {
  const st = data.status || 'idle'
  const label = { idle: '', running: '运行中', done: '完成', error: '失败' }[st]
  return (
    <div className={`rfnode ${st} ${data.selected ? 'sel' : ''}`} style={{ '--c': data.color }}>
      <Handle type="target" position={Position.Left} />
      {label && <span className="st">{label}</span>}
      <div className="t">{data.label}</div>
      <div className="s">{data.kind === 'llm' ? `LLM · ${data.model || 'gpt-4o-mini'}` : data.tool}</div>
      {data.issueCount > 0 && <div className="iss">⚠ {data.issueCount} 个问题</div>}
      <Handle type="source" position={Position.Right} />
    </div>)
}
const nodeTypes = { agent: AgentNode }

function Canvas({ flow, setFlow, tools, selected, setSelected, statuses = {}, issues = [], readonly = false, fit = false }) {
  const rf = useReactFlow(), wrap = useRef(null)
  const toolBy = useMemo(() => Object.fromEntries(tools.map(t => [t.key, t])), [tools])
  const nodes = useMemo(() => flow.nodes.map(n => ({
    id: n.id, type: 'agent', position: n.position || { x: 0, y: 0 }, draggable: !readonly,
    data: { ...n, color: n.kind === 'llm' ? LLM_COLOR : toolBy[n.tool]?.color || '#555', status: statuses[n.id], selected: n.id === selected,
            issueCount: issues.filter(i => i.node === n.id && i.level === 'error').length },
  })), [flow.nodes, toolBy, statuses, selected, issues, readonly])
  const edges = useMemo(() => flow.edges.map(e => ({
    id: `${e.source}->${e.target}`, source: e.source, target: e.target, markerEnd: { type: MarkerType.ArrowClosed },
    animated: statuses[e.source] === 'done' && statuses[e.target] === 'running', style: { strokeWidth: 1.6 },
  })), [flow.edges, statuses])

  const onNodesChange = useCallback(ch => {
    if (readonly) return
    const sel = ch.find(c => c.type === 'select' && c.selected); if (sel) setSelected(sel.id)
    const moved = ch.filter(c => c.type === 'position' && c.position), removed = ch.filter(c => c.type === 'remove').map(c => c.id)
    if (!moved.length && !removed.length) return          // 忽略 dimensions/select 等测量事件，避免无限更新
    setFlow(f => ({ ...f,
      nodes: f.nodes.filter(n => !removed.includes(n.id)).map(n => { const m = moved.find(c => c.id === n.id); return m ? { ...n, position: m.position } : n }),
      edges: f.edges.filter(e => !removed.includes(e.source) && !removed.includes(e.target)) }))
  }, [readonly])
  const onEdgesChange = useCallback(ch => {
    if (readonly) return
    const rm = ch.filter(c => c.type === 'remove').map(c => c.id)
    if (rm.length) setFlow(f => ({ ...f, edges: f.edges.filter(e => !rm.includes(`${e.source}->${e.target}`)) }))
  }, [readonly])
  const onConnect = useCallback(c => {
    if (c.source === c.target) return
    setFlow(f => f.edges.some(e => e.source === c.source && e.target === c.target) ? f : { ...f, edges: [...f.edges, { source: c.source, target: c.target }] })
  }, [])
  const onDrop = useCallback(ev => {
    ev.preventDefault(); if (readonly) return
    const raw = ev.dataTransfer.getData('application/x-agent'); if (!raw) return
    const spec = JSON.parse(raw), pos = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY })
    setFlow(f => {
      const base = spec.kind === 'llm' ? 'llm_agent' : spec.tool; let id = base, k = 2
      while (f.nodes.some(n => n.id === id)) id = `${base}_${k++}`
      const node = spec.kind === 'llm'
        ? { id, kind: 'llm', label: 'LLM 智能体', model: 'gpt-4o-mini', system_message: '', params: {}, position: pos }
        : { id, kind: 'tool', tool: spec.tool, label: toolBy[spec.tool].label, params: {}, position: pos }
      setTimeout(() => setSelected(id), 0)
      return { ...f, nodes: [...f.nodes, node] }
    })
  }, [readonly, toolBy])
  useEffect(() => { const t = setTimeout(() => rf.fitView({ padding: 0.12, maxZoom: 1.1 }), 80); return () => clearTimeout(t) }, [flow.nodes.length, flow.team.name, fit])
  return (
    <div className="canvas" ref={wrap} onDrop={onDrop} onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onConnect={onConnect} onPaneClick={() => setSelected(null)} nodesConnectable={!readonly} elementsSelectable fitView
        fitViewOptions={{ padding: .15 }} deleteKeyCode={readonly ? null : ['Backspace', 'Delete']} proOptions={{ hideAttribution: true }}>
        <Background gap={18} color="#8aa1ab55" /><Controls showInteractive={false} />
      </ReactFlow>
    </div>)
}
export function FlowCanvas(props) { return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider> }

function ParamField({ spec, value, onChange }) {
  const v = value ?? spec.default
  if (spec.type === 'boolean') return <div className="field"><label><input type="checkbox" checked={!!v} onChange={e => onChange(e.target.checked)} /> {spec.label}</label></div>
  if (spec.type === 'select') return <div className="field"><label>{spec.label}</label><select value={v} onChange={e => onChange(e.target.value)}>{spec.options.map(o => <option key={o}>{o}</option>)}</select></div>
  if (spec.type === 'number') return <div className="field"><label>{spec.label}{spec.min != null && <span> （{spec.min}–{spec.max}）</span>}</label>
    <input type="number" value={v} step={spec.step || 1} min={spec.min} max={spec.max} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} /></div>
  return <div className="field"><label>{spec.label}</label><input type="text" value={v} onChange={e => onChange(e.target.value)} /></div>
}

export function Inspector({ flow, setFlow, tools, selected, issues, onDebug }) {
  const node = flow.nodes.find(n => n.id === selected)
  const toolBy = Object.fromEntries(tools.map(t => [t.key, t]))
  const upd = patch => setFlow(f => ({ ...f, nodes: f.nodes.map(n => n.id === selected ? { ...n, ...patch } : n) }))
  const del = () => setFlow(f => ({ nodes: f.nodes.filter(n => n.id !== selected), edges: f.edges.filter(e => e.source !== selected && e.target !== selected), team: f.team }))
  if (!node) return (
    <div className="inspector">
      <h3>团队设置</h3>
      <div className="field"><label>团队名称（标识符）</label><input type="text" value={flow.team.name} onChange={e => setFlow(f => ({ ...f, team: { ...f.team, name: e.target.value } }))} /></div>
      <div className="field"><label>显示名称</label><input type="text" value={flow.team.label || ''} onChange={e => setFlow(f => ({ ...f, team: { ...f.team, label: e.target.value } }))} /></div>
      <div className="field"><label>编排方式</label>
        <select value={flow.team.flow} onChange={e => setFlow(f => ({ ...f, team: { ...f.team, flow: e.target.value } }))}>
          <option value="graph">GraphFlow：有向图（并行 / 汇聚）</option><option value="roundrobin">RoundRobinGroupChat：按横向位置顺序轮询（单智能体用）</option></select></div>
      <div className="field"><label>终止条件：最大消息数</label><input type="number" value={flow.team.max_messages || 40} onChange={e => setFlow(f => ({ ...f, team: { ...f.team, max_messages: Number(e.target.value) } }))} /></div>
      <h3>校验</h3>
      {issues.length === 0 ? <span className="chip ok">无问题，可运行</span> :
        <ul className="issues">{issues.map((i, k) => <li key={k}><span className={`chip ${i.level === 'error' ? 'err' : 'warn'}`}>{i.level === 'error' ? '错误' : '提示'}</span>{i.node ? <b>{i.node}：</b> : null}{i.msg}</li>)}</ul>}
      <h3>操作提示</h3>
      <p style={{ fontSize: 12, color: 'var(--muted)' }}>从左侧拖入智能体 → 拖动圆点连线（并行分支 = 一个节点连多个下游；汇聚 = 多个上游连同一节点）→ 点击节点编辑参数 → Delete 删除。</p>
    </div>)
  const spec = toolBy[node.tool]
  const mine = issues.filter(i => i.node === node.id)
  return (
    <div className="inspector">
      <h3>{node.kind === 'llm' ? 'LLM 智能体' : spec?.role + ' · ' + spec?.label}</h3>
      <div className="field"><label>节点标识（编译为 autogen agent name）</label><input type="text" value={node.id} readOnly /></div>
      <div className="field"><label>显示名称</label><input type="text" value={node.label} onChange={e => upd({ label: e.target.value })} /></div>
      {node.kind === 'tool' && spec && <>
        <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 8px' }}>{spec.desc}</p>
        <div style={{ marginBottom: 8, fontSize: 12 }}>读取：{spec.requires.length ? spec.requires.map(r => <span className="chip" key={r}>{r}</span>) : <span className="chip">无</span>}<br />产出：{spec.provides.map(r => <span className="chip ok" key={r}>{r}</span>)}</div>
        {spec.boundary && <div style={{ fontSize: 12, marginBottom: 8 }}>责任边界：<b>{spec.boundary}</b></div>}
        {spec.params.map(p => <ParamField key={p.key} spec={p} value={node.params?.[p.key]} onChange={v => upd({ params: { ...node.params, [p.key]: v } })} />)}
      </>}
      {node.kind === 'llm' && <>
        <div className="field"><label>模型</label><input type="text" value={node.model || ''} onChange={e => upd({ model: e.target.value })} /></div>
        <div className="field"><label>系统提示词</label><textarea value={node.system_message || ''} onChange={e => upd({ system_message: e.target.value })} /></div>
        <p style={{ fontSize: 12, color: 'var(--muted)' }}>后端设置环境变量 LLM_API_KEY 后调用真实模型；未设置时返回固定离线文案。LLM 节点只做解释，数值以求解器为准。</p>
      </>}
      {mine.length > 0 && <ul className="issues">{mine.map((i, k) => <li key={k}><span className={`chip ${i.level === 'error' ? 'err' : 'warn'}`}>{i.level === 'error' ? '错误' : '提示'}</span>{i.msg}</li>)}</ul>}
      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <button className="btn" onClick={() => onDebug(node.id)}>去调试此节点</button>
        <button className="btn" onClick={del}>删除节点</button></div>
    </div>)
}

export function Palette({ tools }) {
  const groups = {}; tools.forEach(t => (groups[t.role] = groups[t.role] || []).push(t))
  const drag = (ev, spec) => { ev.dataTransfer.setData('application/x-agent', JSON.stringify(spec)); ev.dataTransfer.effectAllowed = 'move' }
  return (
    <div className="palette">
      <h3 style={{ marginTop: 0 }}>专业智能体（拖入画布）</h3>
      {Object.entries(groups).map(([role, ts]) => ts.map(t => (
        <div key={t.key} className="pitem" style={{ borderLeftColor: t.color }} draggable onDragStart={e => drag(e, { kind: 'tool', tool: t.key })} title={t.desc}>
          <b>{t.label}</b><span>{role === t.label ? t.provides.join(' / ') : `${role} · ${t.provides.join(' / ')}`}</span></div>)))}
      <h3>通用</h3>
      <div className="pitem" style={{ borderLeftColor: LLM_COLOR }} draggable onDragStart={e => drag(e, { kind: 'llm' })}><b>LLM 智能体</b><span>AssistantAgent · 自定义提示词</span></div>
    </div>)
}
