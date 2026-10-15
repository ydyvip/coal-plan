"""专业工具注册表 + 运行上下文（黑板）。

每个“专业智能体”= 一个 ToolAgent（agents.py）+ 此处注册的一个确定性专业工具。
工具声明 requires / provides（产出物键），用于：
  1) 编排校验：上游是否提供了所需产出物；
  2) 运行时：严格模式下缺上游即报错；调试模式下惰性补全上游，便于单节点调试。
关键原则：出力/成本等数值只来自 solver.py，其他智能体只做组织、校验、解释。"""
from __future__ import annotations
import asyncio, time, uuid
from dataclasses import dataclass, field
from typing import Any, Callable
from . import scenario as sc, solver as sv

# ───────────────────────── 运行上下文 ─────────────────────────
class MissingUpstream(Exception):
    pass


@dataclass
class RunContext:
    run_id: str
    version: str = "V1"                 # 数据版本：V1 日前 / V2 日内修订
    mode: str = "day_ahead"             # day_ahead | rolling
    strict: bool = True                 # 严格：上游缺失即报错；调试：惰性补全
    artifacts: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    queue: asyncio.Queue | None = None
    baseline_provider: Callable[[], dict | None] | None = None
    t0: float = field(default_factory=time.perf_counter)
    current_agent: str | None = None

    def emit(self, type_: str, **data):
        ev = {"seq": len(self.events), "t": round(time.perf_counter() - self.t0, 4),
              "ts": time.time(), "type": type_, "agent": self.current_agent, **data}
        self.events.append(ev)
        if self.queue is not None:
            self.queue.put_nowait(ev)
        return ev

    def put(self, key: str, value: Any):
        self.artifacts[key] = value
        self.emit("artifact", key=key, value=value)

    def require(self, key: str):
        if key in self.artifacts:
            return self.artifacts[key]
        if self.strict:
            raise MissingUpstream(f"缺少上游产出物 `{key}`，请检查编排连线")
        # 调试模式：惰性补全
        prod = next(t for t in TOOLS.values() if key in t.provides)
        self.emit("note", text=f"调试模式：自动补全上游产出物 `{key}`（来自 {prod.label} 默认参数）")
        prod.fn(self, {p["key"]: p["default"] for p in prod.params})
        return self.artifacts[key]


@dataclass
class Tool:
    key: str; label: str; role: str; color: str; desc: str
    params: list; requires: list; provides: list; fn: Callable
    boundary: str = ""


def _p(key, label, type_, default, **kw):
    return {"key": key, "label": label, "type": type_, "default": default, **kw}


# ───────────────────────── 工具实现 ─────────────────────────
def t_plan_task(ctx: RunContext, p: dict) -> str:
    D = sc.demand(ctx.version); U = sc.units()
    rolling = ctx.mode == "rolling"
    card = {"date": sc.DATE, "version": ctx.version, "mode": ctx.mode, "demand": D, "unit_names": list(U),
            "objective": p["objective"], "peak": max(D), "valley": min(D),
            "revision": ({"issued_at_hour": sc.REVISION["issued_at_hour"], "window": list(sc.REVISION["window"]),
                          "source": sc.REVISION["source"]} if rolling else None)}
    tasks = [{"id": "T1", "name": "逐时总需求与功率平衡", "owner": "发电计划智能体"},
             {"id": "T2", "name": "机组容量/爬坡边界", "owner": "运行约束智能体"},
             {"id": "T3", "name": "分段煤耗与成本口径", "owner": "燃料经济智能体"},
             {"id": "T4", "name": "约束校验与结果说明", "owner": "计划评审智能体"},
             {"id": "S1", "name": "调用专项求解器" + ("（滚动：锁定已执行时段）" if rolling else ""), "owner": "专项求解器"},
             {"id": "R1", "name": "生成《日前生产计划及日内修订报告》", "owner": "报告生成"}]
    ctx.put("task_tree", {"card": card, "tasks": tasks})
    return (f"任务解析完成：{sc.DATE}，数据版本 {ctx.version}，24 点需求 {min(D):.0f}–{max(D):.0f} MW，"
            f"2 台机组，目标「{p['objective']}」；已分派 {len(tasks)} 项任务。"
            "出力与成本数值将只取自专项求解器，不由智能体自行推算。")


def t_load_plan(ctx: RunContext, p: dict) -> str:
    D = sc.demand(ctx.version); U = sc.units()
    cap = sum(u["p_max"] for u in U.values()); floor = sum(u["p_min"] for u in U.values())
    ok = all(floor <= d <= cap for d in D)
    ctx.put("demand", {"version": ctx.version, "hourly": D, "peak": max(D), "valley": min(D),
                       "avg": round(sum(D) / 24, 2), "energy_mwh": sum(D),
                       "balance_rule": "Σ P(unit,t) = D(t)，容差 %.3f MW" % p["balance_tolerance_mw"],
                       "envelope_ok": ok, "envelope": [floor, cap]})
    return (f"需求曲线 {ctx.version}：峰值 {max(D):.0f} MW、谷值 {min(D):.0f} MW、日电量 {sum(D):.0f} MWh；"
            f"全厂可调区间 [{floor},{cap}] MW，{'覆盖全部时段' if ok else '存在越界时段！'}。")


def t_unit_constraints(ctx: RunContext, p: dict) -> str:
    U = sc.units(); out = {}
    for n, u in U.items():
        avail = [float(u["p_max"])] * 24
        if p["include_maintenance"]:
            for a, b, mx in sc.MAINTENANCE.get(n, []):
                for h in range(a, b): avail[h] = float(min(avail[h], mx))
        out[n] = {"label": u["label"], "p_min": u["p_min"], "p_max": u["p_max"], "rated": u["rated"],
                  "ramp_mw_min": u["ramp_mw_min"], "ramp_h": u["ramp_mw_min"] * 60 * p["ramp_derate"],
                  "avail": avail, "initial": u["initial"], "fuel": u["fuel"],
                  "maintenance": sc.MAINTENANCE.get(n, [])}
    ctx.put("unit_limits", {"units": out, "ramp_rule": "爬坡 MW/min × 60 × 折减系数 → 每整点最大变化量",
                            "ramp_derate": p["ramp_derate"]})
    return "；".join(f"{n}: {o['p_min']}–{o['p_max']} MW，爬坡 {o['ramp_mw_min']} MW/min（{o['ramp_h']:.0f} MW/h）"
                     for n, o in out.items()) + "。两机组均在线，不做启停优化。"


def t_fuel_economy(ctx: RunContext, p: dict) -> str:
    U = sc.units(); model = {}
    for n, u in U.items():
        segs, lo = [], u["p_min"]
        for hi, m in u["segments"]:
            segs.append({"from": lo, "to": hi, "marginal": round(m * p["coal_price_factor"] + p["aux_cost"], 3)}); lo = hi
        model[n] = {"label": u["label"], "p_min": u["p_min"], "base_cost_per_mwh": u["base_cost_per_mwh"],
                    "segments": segs, "ref_cost": u["ref_cost"]}
    c1 = 500 * U["B-U1"]["ref_cost"] + 500 * U["B-U2"]["ref_cost"]
    c2 = 600 * U["B-U1"]["ref_cost"] + 400 * U["B-U2"]["ref_cost"]
    ctx.put("cost_model", {"units": model, "coal_price_factor": p["coal_price_factor"], "aux_cost": p["aux_cost"],
                           "formula": "成本(P)=P_min×基础成本 + Σ 分段(MW)×分段边际成本（凸，LP 精确）",
                           "ref_example": {"load": 1000, "split_a": [500, 500], "cost_a": c1,
                                           "split_b": [600, 400], "cost_b": c2, "diff": c1 - c2,
                                           "diff_pct": round((c1 - c2) / c1 * 100, 2),
                                           "note": "单时段口头解释算例，仅用参考变动成本；不代表全天效果，不外推。"}})
    return (f"成本口径就绪（煤价系数 {p['coal_price_factor']}）。口头算例：全厂 1000 MW 时 500/500 为 {c1:,.0f} 元/h，"
            f"600/400 为 {c2:,.0f} 元/h，差 {c1-c2:,.0f} 元/h（{(c1-c2)/c1*100:.2f}%）；不外推全天。")


def _lim(ul):
    return {n: {"avail": o["avail"], "ramp_h": o["ramp_h"]} for n, o in ul["units"].items()}


def _baseline(ctx):
    if ctx.baseline_provider is None:
        return None
    return ctx.baseline_provider()


def t_optimizer(ctx: RunContext, p: dict) -> str:
    dem = ctx.require("demand"); ul = ctx.require("unit_limits"); cm = ctx.require("cost_model")
    U = sc.units(); D = dem["hourly"]; lim = _lim(ul)
    start, locked, initial = 0, None, {n: U[n]["initial"] for n in U}
    if ctx.mode == "rolling":
        base = _baseline(ctx)
        if base is None:
            raise MissingUpstream("滚动重排需要 V1 基线计划，且未能获取")
        start = sc.REVISION["issued_at_hour"]
        locked = {n: base["output"][n][:start] for n in U}
        ctx.emit("note", text=f"滚动优化：锁定 0–{start-1} 时已执行时段（取自 V1 计划），仅重算 {start}–23 时")
    ctx.emit("solver_call", solver=p["solver"], start_hour=start, n_hours=24 - start,
             price_factor=cm["coal_price_factor"], time_limit=p["time_limit_s"])
    r = sv.solve(U, D, lim, start=start, locked=locked, initial=initial,
                 price_factor=cm["coal_price_factor"], aux=cm["aux_cost"], time_limit=p["time_limit_s"])
    r.update({"mode": ctx.mode, "start_hour": start, "locked_hours": list(range(start)), "version": ctx.version,
              "initial": initial})
    ctx.put("schedule", r)
    ctx.emit("solver_result", status=r["status"], seconds=r["solve_seconds"], cost=r.get("cost_total"))
    if r["status"] != "optimal":
        raise RuntimeError(f"求解器未返回最优解：{r['status']} — {r.get('message')}")
    return (f"求解完成：状态 {r['status']}，24 时总成本 {r['cost_total']:,.0f} 元，用时 {r['solve_seconds']*1000:.0f} ms，"
            f"{r['n_variables']} 变量 / {r['n_constraints']} 约束" + (f"；已锁定 {start} 个已执行时段。" if start else "。"))


def _marginal_units(U, P, lam):
    out = []
    for t in range(24):
        found = []
        for n, u in U.items():
            p_ = P[n][t]; lo = u["p_min"]
            for hi, m in u["segments"]:
                if (lo - 1e-6 <= p_ <= hi + 1e-6) and abs(m - (lam[t] or -1)) < 1e-3 and lo + 1e-6 < p_ < hi - 1e-6 + 1e-9:
                    found.append(n)
                lo = hi
        out.append(found[0] if found else "-")
    return out


def t_review(ctx: RunContext, p: dict) -> str:
    sch = ctx.require("schedule"); dem = ctx.require("demand"); ul = ctx.require("unit_limits")
    U = sc.units(); P = sch["output"]
    v = sv.verify(U, dem["hourly"], _lim(ul), P, initial=sch["initial"], tol=p["tolerance_mw"])
    by_type = {}
    for c in v["checks"]:
        b = by_type.setdefault(c["type"], {"total": 0, "passed": 0}); b["total"] += 1; b["passed"] += c["ok"]
    ramp_bind = [(c["unit"], c["hour"]) for c in v["checks"] if c["type"] == "ramp" and c["slack"] < 0.01]
    pmax_hours = {n: [t for t in range(24) if P[n][t] >= ul["units"][n]["avail"][t] - 0.01] for n in U}
    lam = sch["marginal_price"]; mu = _marginal_units(U, P, lam)
    e = {n: round(sum(P[n]), 1) for n in U}
    cheap = min(U, key=lambda n: U[n]["segments"][0][1])
    other = [n for n in U if n != cheap][0]
    exp = [f"功率平衡：{sum(1 for c in v['checks'] if c['type']=='power_balance' and c['ok'])}/24 个时段满足 Σ出力 = 需求。",
           f"{cheap} 的各段边际成本整体低于 {other}（首段 {U[cheap]['segments'][0][1]} vs {U[other]['segments'][0][1]} 元/MWh），"
           f"优化器在可行范围内让其多承担负荷：日发电量 {cheap} {e[cheap]:,.0f} MWh、{other} {e[other]:,.0f} MWh。",
           f"{cheap} 在 {len(pmax_hours[cheap])} 个时段已达最大可用出力，其余负荷由 {other} 补足。"]
    if ramp_bind:
        exp.append(f"爬坡约束在 {len(ramp_bind)} 处取等（紧约束）：" + "、".join(f"{n}@{h:02d}:00" for n, h in ramp_bind[:6]) + "。")
    else:
        exp.append("全部时段爬坡约束均有裕量，未成为紧约束。")
    mset = sorted({m for m in mu if m != "-"})
    exp.append(f"逐时系统边际成本（功率平衡影子价格）范围 {min(x for x in lam if x is not None):.0f}–{max(x for x in lam if x is not None):.0f} 元/MWh；"
               f"边际机组出现：{'、'.join(mset) if mset else '—'}。")
    verdict = "通过" if v["passed"] == v["total"] else "存在未满足约束"
    ctx.put("review", {"pass_rate": v["pass_rate"], "passed": v["passed"], "total": v["total"], "by_type": by_type,
                       "ramp_binding": ramp_bind, "pmax_hours": pmax_hours, "marginal_units": mu,
                       "energy_mwh": e, "explanation": exp, "verdict": verdict, "tolerance_mw": p["tolerance_mw"],
                       "violations": [c for c in v["checks"] if not c["ok"]][:20],
                       "boundary": "本评审为技术性约束校验，不代替专业审批。"})
    return f"约束校验 {v['passed']}/{v['total']}（通过率 {v['pass_rate']*100:.1f}%），结论：{verdict}。不代替专业审批。"


def t_plan_diff(ctx: RunContext, p: dict) -> str:
    sch = ctx.require("schedule"); base = _baseline(ctx)
    if base is None:
        ctx.put("diff", {"available": False, "summary": "无 V1 基线计划，跳过版本差异。"}); return "无基线，跳过。"
    U = list(sch["output"]); d = {n: [round(sch["output"][n][t] - base["output"][n][t], 3) for t in range(24)] for n in U}
    th = p["threshold_mw"]
    changed = sorted({t for n in U for t in range(24) if abs(d[n][t]) > th})
    mx = max((abs(x) for n in U for x in d[n]), default=0)
    s0 = sch.get("start_hour", 0)
    locked_ok = all(abs(d[n][t]) < 1e-6 for n in U for t in range(s0))
    dem_base = sc.demand("V1"); dem_new = sc.demand(sch["version"])
    ctx.put("diff", {"available": True, "baseline_version": "V1", "new_version": sch["version"],
                     "delta": d, "baseline_output": base["output"], "changed_hours": changed, "max_abs_delta_mw": round(mx, 2),
                     "cost_baseline": base["cost_total"], "cost_new": sch["cost_total"],
                     "cost_delta": round(sch["cost_total"] - base["cost_total"], 2),
                     "demand_changed_hours": [t for t in range(24) if dem_base[t] != dem_new[t]],
                     "locked_hours_unchanged": locked_ok, "threshold_mw": th,
                     "summary": f"差异时段 {len(changed)} 个（{min(changed) if changed else '-'}–{max(changed) if changed else '-'} 时），"
                                f"最大出力变动 {mx:.1f} MW，总成本 {sch['cost_total']-base['cost_total']:+,.0f} 元；"
                                f"已执行时段{'未被改动' if locked_ok else '被改动！'}。"})
    return ctx.artifacts["diff"]["summary"]


def t_report(ctx: RunContext, p: dict) -> str:
    sch = ctx.require("schedule"); rv = ctx.require("review"); dem = ctx.require("demand")
    cm = ctx.require("cost_model"); ul = ctx.require("unit_limits"); tt = ctx.artifacts.get("task_tree")
    diff = ctx.artifacts.get("diff")
    P = sch["output"]; U = list(P)
    L = [f"# {p['title']}", "",
         f"> 数据版本 **{sch['version']}**　|　模式 **{'日内滚动修订' if sch['mode']=='rolling' else '日前排程'}**　|　求解器 {sch['solver']}　|　运行 `{ctx.run_id}`", "",
         "## 1. 任务与数据", f"- 日期：{sc.DATE}；机组：{'、'.join(U)}（均为常规燃煤机组，无生物质，无启停优化）",
         f"- 逐时需求：峰值 {dem['peak']:.0f} MW，谷值 {dem['valley']:.0f} MW，日电量 {dem['energy_mwh']:.0f} MWh",
         f"- 优化目标：{tt['card']['objective'] if tt else '燃料变动成本最小'}", "",
         "## 2. 机组运行边界"]
    for n, o in ul["units"].items():
        L.append(f"- {n}：{o['p_min']}–{o['p_max']} MW，爬坡 {o['ramp_mw_min']} MW/min（{o['ramp_h']:.0f} MW/h），初始出力 {o['initial']} MW")
    L += ["", "## 3. 成本口径", f"- {cm['formula']}；煤价系数 {cm['coal_price_factor']}",
          f"- 口头算例（不外推）：{cm['ref_example']['load']} MW 时 500/500 = {cm['ref_example']['cost_a']:,.0f} 元/h，"
          f"600/400 = {cm['ref_example']['cost_b']:,.0f} 元/h，差 {cm['ref_example']['diff']:,.0f} 元/h（{cm['ref_example']['diff_pct']}%）", "",
          "## 4. 优化结果（求解器输出）",
          f"- 状态 **{sch['status']}**，24 时燃料变动成本 **{sch['cost_total']:,.0f} 元**，求解 {sch['solve_seconds']*1000:.0f} ms",
          "", "| 时段 | 需求 MW | " + " | ".join(f"{n} MW" for n in U) + " | 边际成本 元/MWh |",
          "|---|---|" + "---|" * (len(U) + 1)]
    for t in range(24):
        lam = sch["marginal_price"][t]
        lock = "🔒" if t in sch.get("locked_hours", []) else ""
        L.append(f"| {t:02d}:00{lock} | {dem['hourly'][t]:.0f} | " + " | ".join(f"{P[n][t]:.1f}" for n in U) + f" | {'—' if lam is None else f'{lam:.0f}'} |")
    L += ["", "## 5. 约束校验与求解说明", f"- 校验 {rv['passed']}/{rv['total']}，结论：**{rv['verdict']}**"]
    L += [f"- {x}" for x in rv["explanation"]]
    L += ["", "## 6. 日内滚动修订"]
    if diff and diff.get("available"):
        L += [f"- 触发：{sc.REVISION['source']}（{sc.REVISION['issued_at_hour']:02d}:00 下发）；锁定 0–{sch['start_hour']-1} 时已执行时段",
              f"- {diff['summary']}", f"- 基线 V1 成本 {diff['cost_baseline']:,.0f} 元 → V2 {diff['cost_new']:,.0f} 元",
              "- 说明：本版本差异来自调度目标变化（正常业务更新），不代表优劣；未做耗时对比，不声称分钟级优势。"]
    else:
        L.append("- 本次为日前版本 V1，尚无日内修订。")
    L += ["", "## 7. 责任边界", "- 数值来源：专项求解器（HiGHS）；智能体仅负责数据组织、校验与解释。",
          "- 本报告为演示数据（模拟参数），不代替专业审批，不外推全天经济效果。"]
    ctx.put("report", {"title": p["title"], "markdown": "\n".join(L)})
    return f"报告已生成：{p['title']}（{len(L)} 行，数值全部取自求解器与校验器产出物）。"




def t_pipeline(ctx: RunContext, p: dict) -> str:
    """单智能体模式：一个节点串行执行全部专业步骤（用于对照多智能体协同）。"""
    parts = []
    for k in ["plan_task", "load_plan", "unit_constraints", "fuel_economy", "optimizer", "plan_review"]:
        parts.append(TOOLS[k].label + "：" + TOOLS[k].fn(ctx, {q["key"]: q["default"] for q in TOOLS[k].params}))
    if ctx.mode == "rolling":
        parts.append("版本差异分析：" + t_plan_diff(ctx, {"threshold_mw": 0.5}))
    parts.append("报告生成：" + t_report(ctx, {"title": p["title"]}))
    return "\n".join(parts)

# ───────────────────────── 注册表 ─────────────────────────
TOOLS: dict[str, Tool] = {t.key: t for t in [
    Tool("plan_task", "主规划智能体", "主规划", "#1f3a4d", "解析明日任务、生成任务卡与任务树，分派专业任务。",
         [_p("objective", "优化目标", "string", "24 时燃料变动成本最小")], [], ["task_tree"], t_plan_task,
         "不直接编造机组最优出力"),
    Tool("load_plan", "发电计划智能体", "发电计划", "#2f6f8f", "整理逐时总需求与初始出力，形成功率平衡约束。",
         [_p("balance_tolerance_mw", "平衡容差 (MW)", "number", 0.01, min=0, max=5, step=0.01)], [], ["demand"],
         t_load_plan, "检查计划满足功率平衡"),
    Tool("unit_constraints", "运行约束智能体", "运行约束", "#6b7f3a", "分时机组上下限、爬坡与检修窗口。",
         [_p("include_maintenance", "计入检修窗口", "boolean", True),
          _p("ramp_derate", "爬坡折减系数", "number", 1.0, min=0.1, max=1, step=0.05)], [], ["unit_limits"],
         t_unit_constraints, "检查可行性"),
    Tool("fuel_economy", "燃料经济智能体", "燃料经济", "#b0701a", "分段煤耗、煤价、辅机成本参数 → 变动成本函数与核算口径。",
         [_p("coal_price_factor", "煤价系数", "number", 1.0, min=0.5, max=2, step=0.05),
          _p("aux_cost", "辅机附加成本 (元/MWh)", "number", 0.0, min=0, max=50, step=0.5)], [], ["cost_model"],
         t_fuel_economy, "计算经济性"),
    Tool("optimizer", "专项求解器", "求解器", "#7a2e3b", "调用 LP/HiGHS 求解 24 时段×2 机组；mode=rolling 时锁定已执行时段。",
         [_p("solver", "求解器", "select", "highs", options=["highs"]),
          _p("time_limit_s", "求解时限 (s)", "number", 10, min=1, max=600, step=1)],
         ["demand", "unit_limits", "cost_model"], ["schedule"], t_optimizer, "数学优化的唯一权威数值来源"),
    Tool("plan_review", "计划评审智能体", "计划评审", "#4b4a8f", "独立重算全部约束并生成求解说明。",
         [_p("tolerance_mw", "校验容差 (MW)", "number", 0.01, min=0, max=5, step=0.01)],
         ["schedule", "demand", "unit_limits"], ["review"], t_review, "不代替专业审批"),
    Tool("plan_diff", "版本差异分析", "计划评审", "#4b4a8f", "确定性差分：对比 V1 基线与新版本的出力/成本。",
         [_p("threshold_mw", "差异阈值 (MW)", "number", 0.5, min=0, max=50, step=0.5)], ["schedule"], ["diff"],
         t_plan_diff, "仅陈述差异，不判优劣"),
    Tool("pipeline_all", "全流程单智能体", "单智能体", "#555555", "单个智能体串行完成全部专业步骤（对照用，不含并行与分工留痕）。",
         [_p("title", "报告标题", "string", "日前生产计划及日内修订报告")], [],
         ["task_tree", "demand", "unit_limits", "cost_model", "schedule", "review", "diff", "report"], t_pipeline,
         "同样只取数于求解器"),
    Tool("report", "报告生成", "报告", "#3b3b3b", "按模板汇总产出物，生成《日前生产计划及日内修订报告》。",
         [_p("title", "报告标题", "string", "日前生产计划及日内修订报告")],
         ["schedule", "review", "demand", "cost_model", "unit_limits"], ["report"], t_report, "数值全部来自产出物"),
]}


def tool_catalog() -> list[dict]:
    return [{"key": t.key, "label": t.label, "role": t.role, "color": t.color, "desc": t.desc, "params": t.params,
             "requires": t.requires, "provides": t.provides, "boundary": t.boundary} for t in TOOLS.values()]


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:8]
