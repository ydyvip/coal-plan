"""专项求解器：连续出力分配的分段线性规划（LP），HiGHS 求解（scipy.optimize.linprog）。
本模块是“数学优化唯一权威数值来源”：智能体不得自行编造出力/成本。
支持滚动优化：锁定已执行时段，仅对剩余窗口重求解。"""
from __future__ import annotations
import time
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

H = 24


def unit_cost(u: dict, p: float, price_factor: float = 1.0, aux: float = 0.0) -> float:
    """分段线性成本（元/h）：p_min 处基础成本 + 各段边际成本。"""
    cost = u["p_min"] * u["base_cost_per_mwh"]
    lo = u["p_min"]
    for hi, m in u["segments"]:
        seg = max(0.0, min(p, hi) - lo)
        cost += seg * m
        lo = hi
    return (cost) * price_factor + aux * p


def _segments(u):
    segs, lo = [], u["p_min"]
    for hi, m in u["segments"]:
        segs.append((hi - lo, m)); lo = hi
    return segs


def solve(units: dict, demand: list[float], limits: dict, *, start: int = 0,
          locked: dict | None = None, initial: dict | None = None,
          price_factor: float = 1.0, aux: float = 0.0, time_limit: float = 10.0) -> dict:
    """
    units:  机组参数；limits[unit] = {"avail":[24], "ramp_h": MW/h}
    start:  首个自由时段；locked[unit] = 已执行时段出力列表(长度=start)
    initial:00:00 之前初始出力（start=0）；start>0 时取 locked 末值
    """
    t_start = time.perf_counter()
    names = list(units)
    locked = locked or {n: [] for n in names}
    n_free = H - start
    seg_info = {n: _segments(units[n]) for n in names}
    # 变量索引
    idx, k = {}, 0
    for n in names:
        for t in range(start, H):
            for s in range(len(seg_info[n])):
                idx[(n, t, s)] = k; k += 1
    nv = k
    c = np.zeros(nv); ub = np.zeros(nv)
    for (n, t, s), j in idx.items():
        length, m = seg_info[n][s]
        c[j] = m * price_factor + aux
        ub[j] = length
    rows_eq, b_eq = [], []
    A_eq = lil_matrix((n_free, nv)); b_eq = np.zeros(n_free)
    # 功率平衡 Σ P = D
    for t in range(start, H):
        r = t - start
        for n in names:
            for s in range(len(seg_info[n])):
                A_eq[r, idx[(n, t, s)]] = 1.0
        b_eq[r] = demand[t] - sum(units[n]["p_min"] for n in names)
    ub_rows, b_ub = [], []
    def P_row(n, t):   # P[n,t] - p_min 的系数向量（稀疏字典）
        return {idx[(n, t, s)]: 1.0 for s in range(len(seg_info[n]))}
    for n in names:
        pmin = units[n]["p_min"]
        prev0 = (locked[n][-1] if (start > 0 and locked[n]) else
                 (initial or {}).get(n, units[n]["initial"]))
        ramp = limits[n]["ramp_h"]
        for t in range(start, H):
            row = P_row(n, t)
            # 可用容量上限
            ub_rows.append((row, limits[n]["avail"][t] - pmin))
            if t == start:  # 与前一时点
                ub_rows.append((row, prev0 + ramp - pmin))
                ub_rows.append(({j: -v for j, v in row.items()}, -(prev0 - ramp - pmin)))
            else:
                r1 = dict(row)
                for j, v in P_row(n, t - 1).items(): r1[j] = r1.get(j, 0) - v
                ub_rows.append((r1, ramp))
                ub_rows.append(({j: -v for j, v in r1.items()}, ramp))
    A_ub = lil_matrix((len(ub_rows), nv)); b_ub = np.zeros(len(ub_rows))
    for i, (row, rhs) in enumerate(ub_rows):
        for j, v in row.items(): A_ub[i, j] = v
        b_ub[i] = rhs
    res = linprog(c, A_ub=A_ub.tocsr(), b_ub=b_ub, A_eq=A_eq.tocsr(), b_eq=b_eq,
                  bounds=list(zip(np.zeros(nv), ub)), method="highs",
                  options={"time_limit": time_limit})
    elapsed = time.perf_counter() - t_start
    out = {"status": "optimal" if res.status == 0 else ("infeasible" if res.status == 2 else f"status_{res.status}"),
           "message": res.message, "solve_seconds": round(elapsed, 4),
           "n_variables": nv, "n_constraints": n_free + len(ub_rows), "solver": "HiGHS (scipy.linprog)"}
    if res.status != 0:
        return out
    x = res.x
    P = {}
    for n in names:
        pre = list(locked[n]) if start > 0 else []
        free = [units[n]["p_min"] + sum(x[idx[(n, t, s)]] for s in range(len(seg_info[n])))
                for t in range(start, H)]
        P[n] = [round(v, 3) for v in pre + free]
    out["output"] = P
    # 影子价格 = 系统边际成本（元/MWh）；locked 时段补 None
    lam = [None] * start + [round(float(v), 3) for v in res.eqlin.marginals]
    out["marginal_price"] = lam
    out["cost_total"] = round(total_cost(units, P, price_factor, aux), 2)
    out["cost_hourly"] = [round(sum(unit_cost(units[n], P[n][t], price_factor, aux) for n in names), 2) for t in range(H)]
    return out


def total_cost(units, P, price_factor=1.0, aux=0.0):
    return sum(unit_cost(units[n], P[n][t], price_factor, aux) for n in units for t in range(H))


def verify(units: dict, demand: list[float], limits: dict, P: dict, initial: dict | None = None,
           tol: float = 0.01) -> dict:
    """独立校验器：不依赖求解器内部变量，逐条重算约束。返回通过率与明细。"""
    checks = []
    for t in range(H):
        s = sum(P[n][t] for n in P)
        checks.append({"type": "power_balance", "hour": t, "unit": "ALL", "value": round(s, 3),
                       "limit": demand[t], "ok": bool(abs(s - demand[t]) <= tol), "slack": round(abs(s - demand[t]), 4)})
    for n in P:
        u = units[n]; ramp = limits[n]["ramp_h"]
        prev = (initial or {}).get(n, u["initial"])
        for t in range(H):
            p = P[n][t]
            checks.append({"type": "p_min", "hour": t, "unit": n, "value": p, "limit": u["p_min"], "ok": bool(p >= u["p_min"] - tol), "slack": round(p - u["p_min"], 3)})
            checks.append({"type": "p_max", "hour": t, "unit": n, "value": p, "limit": limits[n]["avail"][t], "ok": bool(p <= limits[n]["avail"][t] + tol), "slack": round(limits[n]["avail"][t] - p, 3)})
            d = abs(p - prev)
            checks.append({"type": "ramp", "hour": t, "unit": n, "value": round(d, 3), "limit": ramp, "ok": bool(d <= ramp + tol), "slack": round(ramp - d, 3)})
            prev = p
    ok = sum(1 for c in checks if c["ok"])
    return {"total": len(checks), "passed": ok, "pass_rate": round(ok / len(checks), 4), "checks": checks}
