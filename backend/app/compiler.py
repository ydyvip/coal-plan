"""编排图(flow) ⇄ agentTeamComponent（autogen 组件树）编译、反编译与校验。

flow（前端编辑态）:
 {"team":{"name","label","flow":"graph|roundrobin","max_messages"},
  "nodes":[{"id","kind":"tool|llm","tool","label","params","system_message","model","position"}],
  "edges":[{"source","target"}]}
agentTeamComponent: autogen `team.dump_component()` 的 JSON（GraphFlow / RoundRobinGroupChat）。"""
from __future__ import annotations
import copy
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow, RoundRobinGroupChat
from autogen_ext.models.replay import ReplayChatCompletionClient
from .agents import ToolAgent
from .tools import TOOLS

OFFLINE_LLM_TEXT = ("【离线演示模式】未配置 LLM_API_KEY，本节点返回固定文案：请以专业智能体与求解器给出的数值为准，"
                    "本节点只做自然语言解释，不生成任何出力或成本数值。")
OPENAI_CLIENT = {"provider": "autogen_ext.models.openai.OpenAIChatCompletionClient", "component_type": "model",
                 "version": 1, "component_version": 1, "label": "OpenAIChatCompletionClient",
                 "config": {"model": "gpt-4o-mini"}}


# provider 白名单：load_component 会按 provider 路径导入并实例化任意类，必须限制来源（防任意代码执行）
ALLOWED_PROVIDERS = {
    "app.agents.ToolAgent", "autogen_agentchat.agents.AssistantAgent",
    "autogen_agentchat.teams.GraphFlow", "autogen_agentchat.teams.RoundRobinGroupChat",
    "autogen_agentchat.conditions.MaxMessageTermination",
    "autogen_core.model_context.UnboundedChatCompletionContext", "autogen_core.tools.StaticStreamWorkbench",
    "autogen_ext.models.openai.OpenAIChatCompletionClient", "autogen_ext.models.replay.ReplayChatCompletionClient",
}


def check_providers(comp) -> list[str]:
    bad = []
    def walk(x):
        if isinstance(x, dict):
            p = x.get("provider")
            if isinstance(p, str) and p not in ALLOWED_PROVIDERS: bad.append(p)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(comp)
    return sorted(set(bad))


def _ident(s: str) -> bool:
    return isinstance(s, str) and s.isidentifier() and not s.startswith("_")


# ───────────────────────── 校验 ─────────────────────────
def _order(flow: dict) -> list[str] | None:
    ids = [n["id"] for n in flow["nodes"]]
    indeg = {i: 0 for i in ids}; adj = {i: [] for i in ids}
    for e in flow["edges"]:
        if e["source"] in adj and e["target"] in indeg:
            adj[e["source"]].append(e["target"]); indeg[e["target"]] += 1
    q = sorted([i for i in ids if indeg[i] == 0]); out = []
    while q:
        x = q.pop(0); out.append(x)
        for y in adj[x]:
            indeg[y] -= 1
            if indeg[y] == 0: q.append(y)
    return out if len(out) == len(ids) else None


def ancestors(flow: dict) -> dict[str, set]:
    par = {n["id"]: set() for n in flow["nodes"]}
    for e in flow["edges"]:
        if e["target"] in par and e["source"] in par: par[e["target"]].add(e["source"])
    memo = {}
    def go(i):
        if i in memo: return memo[i]
        memo[i] = set(); s = set()
        for p in par[i]: s |= {p} | go(p)
        memo[i] = s; return s
    return {i: go(i) for i in par}


def validate(flow: dict) -> list[dict]:
    iss = []
    def add(level, node, msg): iss.append({"level": level, "node": node, "msg": msg})
    nodes = flow.get("nodes", [])
    if not nodes:
        add("error", None, "画布为空：请至少拖入 1 个智能体"); return iss
    seen = set()
    for n in nodes:
        if not _ident(n["id"]): add("error", n["id"], "节点标识必须是合法 Python 标识符（字母/数字/下划线，不以数字开头）")
        if n["id"] in seen: add("error", n["id"], "节点标识重复")
        seen.add(n["id"])
        if n["kind"] == "tool":
            spec = TOOLS.get(n.get("tool"))
            if not spec: add("error", n["id"], f"未知专业工具 {n.get('tool')}"); continue
            for p in spec.params:
                v = (n.get("params") or {}).get(p["key"], p["default"])
                if p["type"] == "number":
                    try:
                        fv = float(v)
                        if "min" in p and fv < p["min"] or "max" in p and fv > p["max"]:
                            add("error", n["id"], f"参数「{p['label']}」应在 [{p.get('min')}, {p.get('max')}]")
                    except (TypeError, ValueError):
                        add("error", n["id"], f"参数「{p['label']}」必须为数字")
        elif n["kind"] == "llm":
            if not (n.get("system_message") or "").strip(): add("error", n["id"], "LLM 智能体必须填写系统提示词")
        else:
            add("error", n["id"], f"未知节点类型 {n['kind']}")
    mode = flow["team"].get("flow", "graph")
    order = _order(flow)
    ids = {n["id"] for n in nodes}
    for e in flow["edges"]:
        if e["source"] not in ids or e["target"] not in ids: add("error", None, "存在指向不存在节点的连线")
    if mode == "graph":
        if order is None: add("error", None, "编排图存在环：当前仅支持有向无环图（DAG）")
        if len(nodes) > 1:
            linked = {e["source"] for e in flow["edges"]} | {e["target"] for e in flow["edges"]}
            for n in nodes:
                if n["id"] not in linked: add("warn", n["id"], "该节点未连线，GraphFlow 会把它当作独立起点并行执行")
        anc = ancestors(flow) if order else {}
    else:
        seq = sorted(nodes, key=lambda n: (n.get("position", {}).get("x", 0), n.get("position", {}).get("y", 0)))
        anc = {n["id"]: {m["id"] for m in seq[:i]} for i, n in enumerate(seq)}
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        if n["kind"] != "tool" or n.get("tool") not in TOOLS: continue
        have = set()
        for a in anc.get(n["id"], ()):
            if by_id[a]["kind"] == "tool": have |= set(TOOLS[by_id[a]["tool"]].provides)
        miss = [r for r in TOOLS[n["tool"]].requires if r not in have]
        if miss: add("error", n["id"], f"缺少上游产出物：{', '.join(miss)}（请连接提供它们的专业智能体）")
    tools = [n.get("tool") for n in nodes if n["kind"] == "tool"]
    if tools and "optimizer" not in tools and "pipeline_all" not in tools:
        add("warn", None, "未包含「专项求解器」：团队不会产出排程，数值权威来源缺失")
    if len(tools) != len(set(tools)) and "pipeline_all" not in tools:
        add("warn", None, "同一专业工具出现多次，后者会覆盖前者产出物")
    return iss


# ───────────────────────── 编译 ─────────────────────────
def _build_agent(n: dict):
    if n["kind"] == "tool":
        return ToolAgent(n["id"], n.get("label", ""), n["tool"], n.get("params") or {})
    return AssistantAgent(n["id"], model_client=ReplayChatCompletionClient([OFFLINE_LLM_TEXT]),
                          description=n.get("label", ""), system_message=n["system_message"])


def compile_flow(flow: dict) -> dict:
    nodes = flow["nodes"]; team_meta = flow["team"]
    agents = {n["id"]: _build_agent(n) for n in nodes}
    maxm = int(team_meta.get("max_messages") or (len(nodes) * 2 + 4))
    term = MaxMessageTermination(maxm)
    if team_meta.get("flow", "graph") == "graph" and len(nodes) > 0:
        b = DiGraphBuilder()
        for a in agents.values(): b.add_node(a)
        for e in flow["edges"]: b.add_edge(agents[e["source"]], agents[e["target"]])
        team = GraphFlow(list(agents.values()), graph=b.build(), termination_condition=term)
    else:
        seq = sorted(nodes, key=lambda n: (n.get("position", {}).get("x", 0), n.get("position", {}).get("y", 0)))
        team = RoundRobinGroupChat([agents[n["id"]] for n in seq], termination_condition=MaxMessageTermination(len(seq) + 1))
    comp = team.dump_component().model_dump(mode="json", exclude_none=True)
    comp["label"] = team_meta.get("label") or team_meta.get("name", "team")
    comp["description"] = team_meta.get("description") or comp.get("description", "")
    comp["config"]["name"] = team_meta.get("name", "team")
    by_id = {n["id"]: n for n in nodes}
    for part in comp["config"]["participants"]:
        n = by_id[part["config"]["name"]]
        part["label"] = n.get("label") or n["id"]
        if n["kind"] == "llm":
            part["config"]["model_client"] = copy.deepcopy(OPENAI_CLIENT)
            part["config"]["model_client"]["config"]["model"] = n.get("model") or "gpt-4o-mini"
    return comp


def decompile(comp: dict, positions: dict | None = None) -> dict:
    cfg = comp["config"]; parts = cfg["participants"]
    is_graph = comp["provider"].endswith("GraphFlow")
    nodes = []
    for p in parts:
        c = p["config"]
        if p["provider"].endswith("ToolAgent"):
            nodes.append({"id": c["name"], "kind": "tool", "tool": c["tool"], "label": p.get("label") or c["name"], "params": c.get("params", {})})
        else:
            nodes.append({"id": c["name"], "kind": "llm", "label": p.get("label") or c["name"],
                          "system_message": c.get("system_message", ""),
                          "model": (c.get("model_client", {}).get("config", {}) or {}).get("model", "gpt-4o-mini"), "params": {}})
    edges = []
    if is_graph:
        for src, nd in cfg["graph"]["nodes"].items():
            for e in nd.get("edges", []): edges.append({"source": src, "target": e["target"]})
    else:
        for a, b in zip(nodes, nodes[1:]): edges.append({"source": a["id"], "target": b["id"]})
    flow = {"team": {"name": cfg.get("name", "team"), "label": comp.get("label", ""), "flow": "graph" if is_graph else "roundrobin",
                     "description": comp.get("description", ""),
                     "max_messages": ((cfg.get("termination_condition") or {}).get("config") or {}).get("max_messages", 30)},
            "nodes": nodes, "edges": edges}
    layout(flow, positions)
    return flow


def layout(flow: dict, positions: dict | None = None):
    """按拓扑深度自动布局；若提供 positions 则优先使用。"""
    par = {n["id"]: [] for n in flow["nodes"]}
    for e in flow["edges"]:
        if e["target"] in par: par[e["target"]].append(e["source"])
    depth = {}
    def d(i):
        if i not in depth: depth[i] = 0; depth[i] = 1 + max((d(p) for p in par[i]), default=-1)
        return depth[i]
    cols = {}
    for n in flow["nodes"]: cols.setdefault(d(n["id"]), []).append(n)
    for col, ns in cols.items():
        for r, n in enumerate(ns):
            n["position"] = (positions or {}).get(n["id"]) or {"x": 60 + col * 270, "y": 60 + r * 150 + (len(cols.get(1, [])) - len(ns)) * 60}


def to_runnable(comp: dict, have_key: bool) -> dict:
    """运行前处理：无 LLM 密钥时，把 OpenAI 模型客户端换成离线回放客户端。深拷贝，不改动存档的组件。"""
    comp = copy.deepcopy(comp)
    if have_key: return comp
    for p in comp["config"]["participants"]:
        mc = p["config"].get("model_client")
        if mc and "openai" in mc["provider"].lower():
            p["config"]["model_client"] = ReplayChatCompletionClient([OFFLINE_LLM_TEXT]).dump_component().model_dump(mode="json", exclude_none=True)
    return comp


# ───────────────────────── 预置模板 ─────────────────────────
def _t(id_, tool, label, **params): return {"id": id_, "kind": "tool", "tool": tool, "label": label, "params": params}
MULTI_NODES = [_t("planner", "plan_task", "主规划智能体"), _t("load_agent", "load_plan", "发电计划智能体"),
               _t("constraint_agent", "unit_constraints", "运行约束智能体"), _t("fuel_agent", "fuel_economy", "燃料经济智能体"),
               _t("solver", "optimizer", "专项求解器"), _t("reviewer", "plan_review", "计划评审智能体")]
MULTI_EDGES = [("planner", "load_agent"), ("planner", "constraint_agent"), ("planner", "fuel_agent"),
               ("load_agent", "solver"), ("constraint_agent", "solver"), ("fuel_agent", "solver"), ("solver", "reviewer")]
LLM_NODE = {"id": "narrator", "kind": "llm", "label": "LLM 解说（可选）", "model": "gpt-4o-mini",
            "system_message": "你是电厂生产计划说明助手。只复述上游智能体与求解器已给出的数值与结论，"
                              "用 3 句话向值长解释；严禁编造任何出力、成本或约束数值。"}


def templates() -> dict:
    def mk(id_, name, desc, nodes, edges, mode="graph", extra=None):
        flow = {"team": {"name": id_, "label": name, "description": desc, "flow": mode, "max_messages": 40},
                "nodes": copy.deepcopy(nodes), "edges": [{"source": a, "target": b} for a, b in edges]}
        layout(flow); return {"id": id_, "name": name, "desc": desc, "flow": flow}
    day = MULTI_NODES + [_t("reporter", "report", "报告生成")]
    day_e = MULTI_EDGES + [("reviewer", "reporter")]
    roll = MULTI_NODES + [_t("diff_agent", "plan_diff", "版本差异分析"), _t("reporter", "report", "报告生成")]
    roll_e = MULTI_EDGES + [("solver", "diff_agent"), ("reviewer", "reporter"), ("diff_agent", "reporter")]
    llm_nodes = day + [LLM_NODE]
    llm_e = MULTI_EDGES + [("reviewer", "narrator"), ("narrator", "reporter")]
    return {t["id"]: t for t in [
        mk("day_ahead_team", "日前排程团队（多智能体并行）", "B-1~B-5：任务→三专业并行→求解→评审→报告", day, day_e),
        mk("intraday_rolling_team", "日内滚动修订团队", "B-6：锁定已执行时段，重排 18:00–21:00 新目标并给出版本差异", roll, roll_e),
        mk("single_agent", "单智能体基线", "单个节点串行完成全部步骤（对照）", [_t("all_in_one", "pipeline_all", "全流程单智能体")], [], "roundrobin"),
        mk("team_with_llm", "多智能体 + LLM 解说", "在评审与报告之间插入 LLM 解说节点（无密钥时离线固定文案）", llm_nodes, llm_e),
    ]}
