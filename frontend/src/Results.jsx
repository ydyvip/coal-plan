import React, { useState, useMemo } from 'react'
import { LineChart, Bars } from './charts'
import { fmt } from './api'

const hh = i => String(i).padStart(2, '0') + ':00'

function TaskCard({ a }) {
  const c = a.card
  return <>
    <div className="card"><h4>任务卡 · {c.date}</h4>
      <dl className="kv"><dt>数据版本</dt><dd>{c.version}（{c.mode === 'rolling' ? '日内滚动修订' : '日前排程'}）</dd>
        <dt>需求范围</dt><dd>{fmt(c.valley)}–{fmt(c.peak)} MW × 24 点</dd><dt>机组</dt><dd>{c.unit_names.join('、')}（常规燃煤）</dd>
        <dt>优化目标</dt><dd>{c.objective}</dd>
        {c.revision && <><dt>调度修订</dt><dd>{c.revision.source}，{hh(c.revision.issued_at_hour)} 下发，窗口 {hh(c.revision.window[0])}–{hh(c.revision.window[1])}</dd></>}</dl>
      <LineChart series={[{ name: '全厂需求', values: c.demand, area: true, color: '#12232d' }]} height={170} />
    </div>
    <div className="card"><h4>分派的专业任务</h4>
      <table className="t left"><thead><tr><th>编号</th><th>任务</th><th>负责</th></tr></thead>
        <tbody>{a.tasks.map(t => <tr key={t.id}><td>{t.id}</td><td style={{ textAlign: 'left' }}>{t.name}</td><td style={{ textAlign: 'left' }}>{t.owner}</td></tr>)}</tbody></table></div></>
}

function Specialists({ art }) {
  const { demand: d, unit_limits: ul, cost_model: cm } = art
  const cons = ul && [...Object.entries(ul.units).flatMap(([n, o]) => [`${n}：${o.p_min} ≤ P ≤ ${o.p_max} MW`, `${n}：|ΔP| ≤ ${o.ramp_h} MW/h`]), d && `功率平衡：${d.balance_rule}`].filter(Boolean)
  return <div className="grid2">
    <div className="card"><h4>① 负荷曲线（发电计划智能体）</h4>{d ? <>
      <dl className="kv"><dt>版本</dt><dd>{d.version}</dd><dt>峰/谷/均</dt><dd>{fmt(d.peak)} / {fmt(d.valley)} / {fmt(d.avg, 1)} MW</dd><dt>日电量</dt><dd>{fmt(d.energy_mwh)} MWh</dd>
        <dt>可调区间</dt><dd>[{d.envelope.join(', ')}] MW {d.envelope_ok ? '✓覆盖' : '✗越界'}</dd></dl>
      <LineChart series={[{ name: '需求', values: d.hourly, color: '#12232d', area: true }]} height={150} /></> : <Wait />}</div>
    <div className="card"><h4>② 容量 / 爬坡边界（运行约束智能体）</h4>{ul ? <table className="t"><thead><tr><th>机组</th><th>P_min</th><th>P_max</th><th>MW/min</th><th>MW/h</th><th>初始</th></tr></thead>
      <tbody>{Object.entries(ul.units).map(([n, o]) => <tr key={n}><td>{n}</td><td>{o.p_min}</td><td>{o.p_max}</td><td>{o.ramp_mw_min}</td><td>{o.ramp_h}</td><td>{o.initial}</td></tr>)}</tbody></table> : <Wait />}</div>
    <div className="card"><h4>③ 煤耗函数（燃料经济智能体）</h4>{cm ? <>
      <table className="t"><thead><tr><th>机组</th><th>分段 MW</th><th>边际 元/MWh</th></tr></thead><tbody>
        {Object.entries(cm.units).flatMap(([n, o]) => o.segments.map((s, i) => <tr key={n + i}><td>{i === 0 ? n : ''}</td><td>{s.from}–{s.to}</td><td>{fmt(s.marginal, 1)}</td></tr>))}</tbody></table>
      <p style={{ fontSize: 12, margin: '8px 0 0' }}><b>口头算例（单时段）</b>：全厂 {cm.ref_example.load} MW，500/500 = {fmt(cm.ref_example.cost_a)} 元/h；600/400 = {fmt(cm.ref_example.cost_b)} 元/h；差 {fmt(cm.ref_example.diff)} 元/h（{cm.ref_example.diff_pct}%）。{cm.ref_example.note}</p></> : <Wait />}</div>
    <div className="card"><h4>④ 约束清单</h4>{cons ? <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{cons.map(c => <li key={c}>{c}</li>)}</ul> : <Wait />}</div>
  </div>
}
const Wait = () => <div className="empty" style={{ padding: 12 }}>等待对应智能体产出…</div>

function Schedule({ sch, dem, base }) {
  const names = Object.keys(sch.output)
  const [view, setView] = useState('chart')
  const colors = { 'B-U1': '#2f6f8f', 'B-U2': '#b9720f' }
  const series = [{ name: '需求', values: dem?.hourly || sch.output[names[0]].map((_, t) => names.reduce((s, n) => s + sch.output[n][t], 0)), color: '#12232d', dash: '5 4', w: 1.5 },
    ...names.map(n => ({ name: n, values: sch.output[n], color: colors[n] })),
    ...(base && sch.mode === 'rolling' ? names.map(n => ({ name: n + '(V1)', values: base.output[n], color: colors[n], dash: '2 3', w: 1.2 })) : [])]
  return <>
    <div className="grid2" style={{ marginBottom: 12 }}>
      <div className="card"><div className="bigl">24 时燃料变动成本</div><div className="big">{fmt(sch.cost_total)} <span style={{ fontSize: 14 }}>元</span></div></div>
      <div className="card"><div className="bigl">求解状态 / 用时</div><div className="big" style={{ color: sch.status === 'optimal' ? 'var(--teal)' : 'var(--brick)' }}>{sch.status}</div>
        <div className="bigl">{(sch.solve_seconds * 1000).toFixed(0)} ms · {sch.n_variables} 变量 · {sch.n_constraints} 约束 · {sch.solver}</div></div></div>
    <div className="card"><div className="tabs" style={{ border: 0, padding: 0, marginBottom: 6 }}>
      <button className={view === 'chart' ? 'on' : ''} onClick={() => setView('chart')}>出力曲线</button><button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')}>逐时数据</button></div>
      {view === 'chart' ? <LineChart series={series} height={280} yMin={200} lockedTo={sch.start_hour || 0} /> :
        <div className="scroll"><table className="t"><thead><tr><th>时段</th><th>需求</th>{names.map(n => <th key={n}>{n}</th>)}<th>边际成本</th><th>小时成本</th></tr></thead>
          <tbody>{Array.from({ length: 24 }, (_, t) => <tr key={t} className={t < (sch.start_hour || 0) ? 'lk' : ''}><td>{hh(t)}{t < (sch.start_hour || 0) ? ' 🔒' : ''}</td><td>{fmt(series[0].values[t])}</td>
            {names.map(n => <td key={n}>{fmt(sch.output[n][t], 1)}</td>)}<td>{sch.marginal_price[t] == null ? '—' : fmt(sch.marginal_price[t])}</td><td>{fmt(sch.cost_hourly[t])}</td></tr>)}</tbody></table></div>}
    </div></>
}

function Review({ rv, sch }) {
  const lbl = { power_balance: '功率平衡', p_min: '最小稳定出力', p_max: '最大可用出力', ramp: '爬坡速率' }
  return <>
    <div className="grid2"><div className="card"><div className="bigl">约束通过率</div><div className="big" style={{ color: rv.pass_rate === 1 ? 'var(--teal)' : 'var(--brick)' }}>{(rv.pass_rate * 100).toFixed(1)}%</div><div className="bigl">{rv.passed}/{rv.total} 项 · 结论：{rv.verdict}</div></div>
      <div className="card"><h4>分类校验</h4><Bars items={Object.entries(rv.by_type).map(([k, v]) => ({ label: lbl[k] || k, pct: v.passed / v.total * 100, text: `${v.passed}/${v.total}` }))} /></div></div>
    <div className="card"><h4>求解说明</h4><ol style={{ margin: 0, paddingLeft: 20 }}>{rv.explanation.map((x, i) => <li key={i} style={{ marginBottom: 4 }}>{x}</li>)}</ol>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 0 }}>{rv.boundary}</p></div>
    <div className="card"><h4>逐时边际机组与系统边际成本</h4>
      <LineChart series={[{ name: '边际成本', values: sch.marginal_price.map(v => v ?? sch.marginal_price.find(x => x != null)), color: '#9b2f3c' }]} height={150} unit="元/MWh" lockedTo={sch.start_hour || 0} yMin={300} yMax={360} /></div></>
}

function Diff({ df, sch, base }) {
  if (!df.available) return <div className="empty">{df.summary}</div>
  const names = Object.keys(df.delta)
  return <>
    <div className="card"><h4>版本差异 V1 → {df.new_version}</h4><p style={{ margin: 0 }}>{df.summary}</p>
      <dl className="kv" style={{ marginTop: 8 }}><dt>V1 成本</dt><dd>{fmt(df.cost_baseline)} 元</dd><dt>{df.new_version} 成本</dt><dd>{fmt(df.cost_new)} 元（{df.cost_delta >= 0 ? '+' : ''}{fmt(df.cost_delta)}）</dd>
        <dt>需求变化时段</dt><dd>{df.demand_changed_hours.map(hh).join('、') || '—'}</dd><dt>已执行时段</dt><dd>{df.locked_hours_unchanged ? '✓ 未改动' : '✗ 被改动'}</dd></dl>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 0 }}>差异由调度目标变化引起，不代表方案优劣；未做耗时对比。</p></div>
    <div className="card"><h4>出力变化（MW，V2 − V1）</h4>
      <div className="scroll"><table className="t"><thead><tr><th>时段</th>{names.map(n => <th key={n}>{n} Δ</th>)}<th>V1 → V2 {names[0]}</th></tr></thead><tbody>
        {df.changed_hours.map(t => <tr key={t}><td>{hh(t)}</td>{names.map(n => <td key={n} style={{ color: df.delta[n][t] > 0 ? 'var(--amber)' : 'var(--teal)' }}>{df.delta[n][t] > 0 ? '+' : ''}{fmt(df.delta[n][t], 1)}</td>)}
          <td>{base ? `${fmt(base.output[names[0]][t], 0)} → ${fmt(sch.output[names[0]][t], 0)}` : ''}</td></tr>)}</tbody></table></div></div></>
}

function md(src) {   // 极简 Markdown：标题/列表/表格/粗体/引用
  const lines = src.split('\n'), out = []; let i = 0
  const inl = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>')
  while (i < lines.length) {
    const l = lines[i]
    if (l.startsWith('# ')) out.push(`<h1>${inl(l.slice(2))}</h1>`)
    else if (l.startsWith('## ')) out.push(`<h2>${inl(l.slice(3))}</h2>`)
    else if (l.startsWith('> ')) out.push(`<blockquote style="margin:6px 0;color:var(--muted)">${inl(l.slice(2))}</blockquote>`)
    else if (l.startsWith('|')) {
      const rows = []; while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++]); i--
      const cells = r => r.split('|').slice(1, -1).map(x => x.trim())
      out.push('<div class="scroll"><table class="t"><thead><tr>' + cells(rows[0]).map(c => `<th>${inl(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.slice(2).map(r => '<tr>' + cells(r).map(c => `<td>${inl(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>')
    } else if (l.startsWith('- ')) out.push(`<div style="padding-left:14px;text-indent:-10px">• ${inl(l.slice(2))}</div>`)
    else if (l.trim()) out.push(`<p>${inl(l)}</p>`)
    i++
  }
  return out.join('')
}
function Report({ rp, runId }) {
  return <div className="card md"><div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
    {runId && <a className="btn sm" href={`/api/runs/${runId}/report.md`}>下载 Markdown</a>}
    <button className="btn sm" onClick={() => navigator.clipboard?.writeText(rp.markdown)}>复制全文</button></div>
    <div dangerouslySetInnerHTML={{ __html: md(rp.markdown) }} /></div>
}

export default function Results({ artifacts: a, runId, narrator }) {
  const baseline = a.diff?.available ? { output: a.diff.baseline_output } : null
  const avail = { task: !!a.task_tree, pro: !!(a.demand || a.unit_limits || a.cost_model), sch: !!a.schedule, rv: !!a.review, df: !!a.diff, rp: !!a.report }
  const order = [['task', '任务卡'], ['pro', '专业协同'], ['sch', '排程结果'], ['rv', '求解说明'], ['df', '版本差异'], ['rp', '计划报告']]
  const [tab, setTab] = useState('task')
  const cur = avail[tab] ? tab : (order.find(([k]) => avail[k]) || ['task'])[0]
  return <>
    <div className="tabs">{order.map(([k, n]) => <button key={k} className={cur === k ? 'on' : ''} onClick={() => setTab(k)} disabled={false}>{n} {avail[k] && <span className="dot">●</span>}</button>)}</div>
    <div className="results">
      {!Object.keys(a).length && <div className="empty">尚无产出物。点击左侧「启动智能排程」或「滚动重排」。</div>}
      {cur === 'task' && a.task_tree && <TaskCard a={a.task_tree} />}
      {cur === 'pro' && <Specialists art={a} />}
      {cur === 'sch' && a.schedule && <Schedule sch={a.schedule} dem={a.demand} base={baseline} />}
      {cur === 'rv' && a.review && a.schedule && <Review rv={a.review} sch={a.schedule} />}
      {cur === 'df' && a.diff && <Diff df={a.diff} sch={a.schedule} base={baseline} />}
      {cur === 'rp' && a.report && <Report rp={a.report} runId={runId} />}
      {narrator && cur === 'rv' && <div className="card"><h4>LLM 解说节点输出</h4><p style={{ margin: 0 }}>{narrator}</p></div>}
    </div></>
}
