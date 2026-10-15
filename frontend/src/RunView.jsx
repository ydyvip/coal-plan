import React, { useMemo, useRef, useEffect } from 'react'
import { FlowCanvas } from './Builder'
import Results from './Results'
import { nodeStatus, fmt } from './api'

export function eventLine(e) {
  switch (e.type) {
    case 'run_start': return `▶ 运行开始 · ${e.team} · 版本 ${e.version} · ${e.mode}`
    case 'agent_start': return `→ ${e.label}（${e.agent}）开始`
    case 'tool_call': return `  ⚙ 工具 ${e.tool} · ${(e.seconds * 1000).toFixed(1)} ms → ${e.provides.join(',')}`
    case 'solver_call': return `  ⚙ 调用求解器 ${e.solver}：从 ${e.start_hour} 时起 ${e.n_hours} 个时段`
    case 'solver_result': return `  ✔ 求解器返回 ${e.status} · ${(e.seconds * 1000).toFixed(0)} ms · 成本 ${fmt(e.cost)} 元`
    case 'artifact': return `  ▣ 产出物 ${e.key}`
    case 'note': return `  ℹ ${e.text}`
    case 'message': return `✉ ${e.source}：${e.content.slice(0, 120)}`
    case 'agent_end': return e.ok ? `← ${e.agent} 完成 ${(e.seconds * 1000).toFixed(1)} ms` : `✗ ${e.agent} 失败：${e.error}`
    case 'team_result': return `■ 团队结束：${e.stop_reason}`
    case 'error': return `✗ 错误：${e.message}`
    case 'run_end': return `■ 运行${e.status === 'completed' ? '完成' : '失败'} · ${(e.seconds * 1000).toFixed(0)} ms`
    default: return e.type
  }
}
export function EventLog({ events }) {
  const ref = useRef(); useEffect(() => { ref.current?.scrollTo(0, 1e9) }, [events.length])
  return <div className="evlog" ref={ref}>{events.length === 0 && <span style={{ color: 'var(--muted)' }}>事件将实时显示在这里</span>}
    {events.map(e => <div key={e.seq} className={`ev ${e.type === 'error' || (e.type === 'agent_end' && !e.ok) ? 'err' : ''}`}><span className="tt">{e.t.toFixed(3)}s </span>{eventLine(e)}</div>)}</div>
}

export default function RunView({ flow, setFlow, tools, issues, run, startRun, scn, setScn }) {
  const statuses = useMemo(() => nodeStatus(run.events), [run.events])
  const a = run.artifacts
  const narr = run.events.find(e => e.type === 'message' && flow.nodes.find(n => n.id === e.source && n.kind === 'llm'))?.content
  const running = run.status === 'running'
  const errs = issues.filter(i => i.level === 'error')
  const opts = [{ v: 'V1', m: 'day_ahead', t: '日前排程', s: 'V1 · 明日 24 点需求' }, { v: 'V2', m: 'rolling', t: '日内滚动重排', s: '最新 18:00—21:00 调度计划' }]
  return (
    <div className="runview">
      <div className="leftcol">
        <div className="sec"><h3>数据版本与模式</h3>
          <div className="seg">{opts.map(o => <button key={o.v} className={scn.v === o.v ? 'on' : ''} onClick={() => setScn({ v: o.v, m: o.m })}>{o.t}<small>{o.s}</small></button>)}</div>
          {scn.m === 'rolling' && <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 8px' }}>滚动模式：锁定 17:00 前已执行时段（取自已发布 V1），仅对剩余时段重新求解。团队需包含「专项求解器」，建议含「版本差异分析」。</p>}
          <button className="btn pri" disabled={running || errs.length > 0} onClick={startRun} style={{ width: '100%', padding: '8px' }}>
            {running ? '运行中…' : scn.m === 'rolling' ? '滚动重排' : '启动智能排程'}</button>
          {errs.length > 0 && <p style={{ fontSize: 12, color: 'var(--brick)' }}>编排存在 {errs.length} 个错误，请先到「编排」页修复。</p>}
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 0 }}>当前团队：<b>{flow.team.label || flow.team.name}</b>（{flow.nodes.length} 个智能体）</p>
        </div>
        <div className="sec" style={{ paddingBottom: 4 }}><h3 style={{ margin: 0 }}>执行轨迹 {run.id && <span className="chip">{run.id}</span>}
          <span className={`chip ${run.status === 'completed' ? 'ok' : run.status === 'failed' ? 'err' : run.status === 'running' ? 'warn' : ''}`}>{{ idle: '空闲', running: '运行中', completed: '已完成', failed: '失败' }[run.status]}</span></h3></div>
        <EventLog events={run.events} />
      </div>
      <div className="rightcol">
        <div className="miniflow"><FlowCanvas flow={flow} setFlow={setFlow} tools={tools} selected={null} setSelected={() => {}} statuses={statuses} readonly fit /></div>
        <Results artifacts={a} runId={run.status === 'completed' ? run.id : null} narrator={narr} />
      </div>
    </div>)
}
