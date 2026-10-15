from __future__ import annotations
import asyncio, json, time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import compiler, runner, scenario as sc
from .tools import tool_catalog

app = FastAPI(title="CoalPlan Studio · 多智能体协同决策系统")


class FlowIn(BaseModel):
    flow: dict


class RunIn(BaseModel):
    flow: dict | None = None
    component: dict | None = None
    version: str = "V1"
    mode: str = "day_ahead"


class DebugIn(BaseModel):
    flow: dict
    node_id: str
    upto: bool = False      # True：运行“到此节点”（含全部上游，严格模式）
    version: str = "V1"
    mode: str = "day_ahead"


def _errors(flow): return [i for i in compiler.validate(flow) if i["level"] == "error"]


@app.get("/api/health")
def health(): return {"ok": True, "time": time.time()}


@app.get("/api/tools")
def tools(): return tool_catalog()


@app.get("/api/scenario")
def scenario():
    return {"date": sc.DATE, "units": sc.units(), "demand": {"V1": sc.demand("V1"), "V2": sc.demand("V2")},
            "revision": {**sc.REVISION, "window": list(sc.REVISION["window"])}}


@app.get("/api/templates")
def templates(): return list(compiler.templates().values())


@app.post("/api/validate")
def validate(b: FlowIn): return {"issues": compiler.validate(b.flow)}


@app.post("/api/compile")
def compile_(b: FlowIn):
    issues = compiler.validate(b.flow)
    if any(i["level"] == "error" for i in issues):
        return {"component": None, "issues": issues}
    return {"component": compiler.compile_flow(b.flow), "issues": issues}


class CompIn(BaseModel):
    component: dict
    positions: dict | None = None


@app.post("/api/decompile")
def decompile(b: CompIn):
    try:
        return {"flow": compiler.decompile(b.component, b.positions)}
    except Exception as e:
        raise HTTPException(422, f"无法解析 agentTeamComponent：{e}")


# ── 工作区（保存的团队） ──
@app.get("/api/workspaces")
def ws_list():
    return [json.loads(p.read_text()) | {"component": None} for p in sorted((runner.DATA / "workspaces").glob("*.json"))]


class WsIn(BaseModel):
    id: str
    name: str
    flow: dict


@app.post("/api/workspaces")
def ws_save(b: WsIn):
    comp = compiler.compile_flow(b.flow) if not _errors(b.flow) else None
    rec = {"id": b.id, "name": b.name, "flow": b.flow, "component": comp, "updated": time.time()}
    (runner.DATA / "workspaces" / f"{b.id}.json").write_text(json.dumps(rec, ensure_ascii=False))
    return rec


@app.get("/api/workspaces/{wid}")
def ws_get(wid: str):
    p = runner.DATA / "workspaces" / f"{wid}.json"
    if not p.exists(): raise HTTPException(404)
    return json.loads(p.read_text())


@app.delete("/api/workspaces/{wid}")
def ws_del(wid: str):
    (runner.DATA / "workspaces" / f"{wid}.json").unlink(missing_ok=True); return {"ok": True}


# ── 运行 / 调试 / 观测 ──
@app.post("/api/runs")
async def run(b: RunIn):
    if b.component is None:
        if b.flow is None: raise HTTPException(422, "需要 flow 或 component")
        errs = _errors(b.flow)
        if errs: raise HTTPException(422, {"issues": errs})
        comp = compiler.compile_flow(b.flow)
    else:
        comp = b.component
        bad = compiler.check_providers(comp)
        if bad: raise HTTPException(422, f"component 含未授权的 provider（已拒绝）：{bad}")
        try: errs = _errors(compiler.decompile(comp))
        except Exception as e: raise HTTPException(422, f"component 无法解析：{e}")
        if errs: raise HTTPException(422, {"issues": errs})
    rid = await runner.execute(comp, b.version, b.mode, strict=True)
    return {"run_id": rid}


@app.post("/api/debug/node")
async def debug_node(b: DebugIn):
    """单节点调试：只编译并运行选中节点（非严格模式，惰性补全上游产出物）。"""
    n = next((x for x in b.flow["nodes"] if x["id"] == b.node_id), None)
    if n is None: raise HTTPException(404, "节点不存在")
    if b.upto:
        keep = compiler.ancestors(b.flow).get(b.node_id, set()) | {b.node_id}
        sub = {"team": {**b.flow["team"], "name": "debug_upto_" + n["id"], "label": f"运行至 · {n.get('label', n['id'])}", "flow": "graph"},
               "nodes": [x for x in b.flow["nodes"] if x["id"] in keep],
               "edges": [e for e in b.flow["edges"] if e["source"] in keep and e["target"] in keep]}
        errs = _errors(sub)
        if errs: raise HTTPException(422, {"issues": errs})
        rid = await runner.execute(compiler.compile_flow(sub), b.version, b.mode, strict=True, meta={"kind": "debug", "node": n["id"]})
        return {"run_id": rid}
    sub = {"team": {"name": "debug_" + n["id"], "label": f"调试 · {n.get('label', n['id'])}", "flow": "roundrobin", "max_messages": 4},
           "nodes": [{**n, "position": {"x": 0, "y": 0}}], "edges": []}
    rid = await runner.execute(compiler.compile_flow(sub), b.version, b.mode, strict=False, meta={"kind": "debug", "node": n["id"]})
    return {"run_id": rid}


@app.get("/api/runs")
def runs(): return runner.list_runs()


@app.get("/api/runs/{rid}")
def run_get(rid: str):
    r = runner.load_run(rid)
    if r: return r
    ctx = runner.LIVE.get(rid)
    if ctx: return {"id": rid, "status": "running", "events": ctx.events, "artifacts": ctx.artifacts}
    raise HTTPException(404)


@app.get("/api/runs/{rid}/stream")
async def stream(rid: str):
    ctx = runner.LIVE.get(rid)
    if ctx is None:
        r = runner.load_run(rid)
        if not r: raise HTTPException(404)
        evs = r["events"]
        async def replay():
            for e in evs: yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            yield "event: end\ndata: {}\n\n"
        return StreamingResponse(replay(), media_type="text/event-stream")
    async def gen():
        i = 0
        while True:
            while i < len(ctx.events):
                yield f"data: {json.dumps(ctx.events[i], ensure_ascii=False)}\n\n"; i += 1
            if rid in runner.DONE and i >= len(ctx.events): break
            await asyncio.sleep(0.04)
        yield "event: end\ndata: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{rid}/report.md", response_class=PlainTextResponse)
def report_md(rid: str):
    r = runner.load_run(rid)
    if not r or "report" not in r["artifacts"]: raise HTTPException(404, "该运行没有报告")
    return PlainTextResponse(r["artifacts"]["report"]["markdown"], headers={"Content-Disposition": f"attachment; filename={rid}_report.md"})


@app.delete("/api/baseline")
def reset_baseline():
    runner._baseline_path().unlink(missing_ok=True); return {"ok": True}


# ── 静态前端（npm run build 后 dist 会被复制到 backend/static） ──
STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        f = STATIC / path
        return FileResponse(f if f.is_file() else STATIC / "index.html")
