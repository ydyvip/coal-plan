"""运行服务：加载 agentTeamComponent → 在 RunContext 内执行 → 事件流 + 持久化。"""
from __future__ import annotations
import asyncio, hashlib, json, os, time
from pathlib import Path
from autogen_agentchat.base import TaskResult
from autogen_agentchat.teams import BaseGroupChat
from autogen_core import ComponentLoader
from . import compiler, scenario as sc
from .agents import CURRENT_RUN, _FALLBACK
from .tools import RunContext, TOOLS, new_run_id

DATA = Path(os.environ.get("COALPLAN_DATA", Path(__file__).resolve().parent.parent / "data"))
(DATA / "runs").mkdir(parents=True, exist_ok=True)
(DATA / "workspaces").mkdir(parents=True, exist_ok=True)
LIVE: dict[str, RunContext] = {}
DONE: set[str] = set()
_lock = asyncio.Lock()   # 演示环境串行执行，保证回退全局上下文安全；contextvar 正常传播时可去掉


def _np(o):
    try:
        return o.item()
    except Exception:
        return str(o)


def _baseline_path(): return DATA / "published_V1.json"


def baseline_v1() -> dict | None:
    """日内滚动修订的基线：已发布的 V1 计划；若不存在则用默认参数即时求解 V1（并注明）。"""
    p = _baseline_path()
    if p.exists(): return json.loads(p.read_text())
    ctx = RunContext("baseline", version="V1", mode="day_ahead", strict=False)
    for k in ["plan_task", "load_plan", "unit_constraints", "fuel_economy", "optimizer"]:
        TOOLS[k].fn(ctx, {q["key"]: q["default"] for q in TOOLS[k].params})
    return ctx.artifacts["schedule"]


def digest(comp: dict) -> str:
    return hashlib.sha1(json.dumps(comp, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def _summary(ctx: RunContext) -> dict:
    a = ctx.artifacts; s = a.get("schedule") or {}; r = a.get("review") or {}
    return {"cost_total": s.get("cost_total"), "status": s.get("status"), "solve_seconds": s.get("solve_seconds"),
            "pass_rate": r.get("pass_rate"), "verdict": r.get("verdict"), "has_report": "report" in a,
            "diff": (a.get("diff") or {}).get("summary")}


async def execute(comp: dict, version: str = "V1", mode: str = "day_ahead", strict: bool = True,
                  meta: dict | None = None, wait: bool = False) -> str:
    bad = compiler.check_providers(comp)
    if bad: raise PermissionError(f"未授权的 provider: {bad}")
    run_id = new_run_id()
    ctx = RunContext(run_id, version=version, mode=mode, strict=strict, baseline_provider=baseline_v1)
    LIVE[run_id] = ctx
    meta = meta or {}
    async def _go():
        async with _lock:
            token = CURRENT_RUN.set(ctx); _FALLBACK["ctx"] = ctx
            t0 = time.perf_counter(); status = "completed"
            ctx.emit("run_start", run_id=run_id, version=version, mode=mode, strict=strict,
                     team=comp.get("label"), digest=digest(comp),
                     agents=[p["config"]["name"] for p in comp["config"]["participants"]])
            try:
                have_key = bool(os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))
                team = ComponentLoader.load_component(compiler.to_runnable(comp, have_key), BaseGroupChat) \
                    if False else BaseGroupChat.load_component(compiler.to_runnable(comp, have_key))
                task = f"执行{sc.DATE}生产计划任务：数据版本 {version}，模式 {mode}"
                async for ev in team.run_stream(task=task):
                    if isinstance(ev, TaskResult):
                        ctx.emit("team_result", stop_reason=ev.stop_reason, n_messages=len(ev.messages))
                    else:
                        ctx.emit("message", source=getattr(ev, "source", ""), mtype=type(ev).__name__,
                                 content=str(getattr(ev, "content", ""))[:2000])
            except Exception as e:  # noqa
                status = "failed"; ctx.emit("error", message=f"{type(e).__name__}: {e}")
            finally:
                CURRENT_RUN.reset(token); _FALLBACK["ctx"] = None
            dur = round(time.perf_counter() - t0, 4)
            ctx.emit("run_end", status=status, seconds=dur)
            rec = {"id": run_id, "created": time.time(), "version": version, "mode": mode, "strict": strict, "status": status,
                   "seconds": dur, "team": comp.get("label"), "digest": digest(comp), "component": comp,
                   "events": ctx.events, "artifacts": ctx.artifacts, "summary": _summary(ctx), **meta}
            (DATA / "runs" / f"{run_id}.json").write_text(json.dumps(rec, ensure_ascii=False, default=_np))
            if status == "completed" and version == "V1" and mode == "day_ahead" and "schedule" in ctx.artifacts and strict:
                _baseline_path().write_text(json.dumps(ctx.artifacts["schedule"], ensure_ascii=False, default=_np))  # 发布 V1 基线
            DONE.add(run_id)
    task = asyncio.create_task(_go())
    if wait: await task
    return run_id


def load_run(run_id: str) -> dict | None:
    p = DATA / "runs" / f"{run_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def list_runs() -> list[dict]:
    out = []
    for p in sorted((DATA / "runs").glob("run_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:60]:
        r = json.loads(p.read_text())
        out.append({k: r[k] for k in ("id", "created", "version", "mode", "status", "seconds", "team", "digest", "summary")} |
                   {"kind": r.get("kind", "run"), "n_events": len(r["events"])})
    return out
