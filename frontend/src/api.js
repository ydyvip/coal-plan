const j = async (r) => {
  if (!r.ok) { let b = null; try { b = await r.json() } catch {} ; const e = new Error('HTTP ' + r.status); e.body = b; throw e }
  return r.json()
}
const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(j)
export const api = {
  tools: () => fetch('/api/tools').then(j),
  scenario: () => fetch('/api/scenario').then(j),
  templates: () => fetch('/api/templates').then(j),
  validate: (flow) => post('/api/validate', { flow }),
  compile: (flow) => post('/api/compile', { flow }),
  decompile: (component, positions) => post('/api/decompile', { component, positions }),
  run: (body) => post('/api/runs', body),
  debug: (body) => post('/api/debug/node', body),
  runs: () => fetch('/api/runs').then(j),
  getRun: (id) => fetch('/api/runs/' + id).then(j),
  saveWs: (id, name, flow) => post('/api/workspaces', { id, name, flow }),
  listWs: () => fetch('/api/workspaces').then(j),
  getWs: (id) => fetch('/api/workspaces/' + id).then(j),
  resetBaseline: () => fetch('/api/baseline', { method: 'DELETE' }).then(j),
}
// 订阅运行事件（SSE）；返回关闭函数
export function subscribe(runId, onEvent, onEnd) {
  const es = new EventSource(`/api/runs/${runId}/stream`)
  es.onmessage = (m) => onEvent(JSON.parse(m.data))
  es.addEventListener('end', () => { es.close(); onEnd && onEnd() })
  es.onerror = () => { es.close(); onEnd && onEnd() }
  return () => es.close()
}
// 事件 → 节点状态
export function nodeStatus(events) {
  const s = {}
  for (const e of events) {
    if (e.type === 'agent_start') s[e.agent] = 'running'
    else if (e.type === 'agent_end') s[e.agent] = e.ok ? 'done' : 'error'
  }
  return s
}
export const fmt = (x, d = 0) => x == null ? '—' : Number(x).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
