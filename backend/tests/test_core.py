import asyncio, copy, os, tempfile
os.environ["COALPLAN_DATA"] = tempfile.mkdtemp()
import pytest
from app import compiler, runner, scenario as sc, solver as sv


def _lim(U): return {n: {"avail": [U[n]["p_max"]] * 24, "ramp_h": U[n]["ramp_mw_min"] * 60} for n in U}


def test_solver_optimal_and_feasible():
    U, D = sc.units(), sc.demand("V1"); r = sv.solve(U, D, _lim(U))
    assert r["status"] == "optimal"
    v = sv.verify(U, D, _lim(U), r["output"]); assert v["pass_rate"] == 1.0
    assert all(abs(sum(r["output"][n][t] for n in U) - D[t]) < 1e-6 for t in range(24))


def test_solver_beats_naive_even_split():
    U, D = sc.units(), sc.demand("V1"); r = sv.solve(U, D, _lim(U))
    naive = {n: [min(max(D[t] / 2, U[n]["p_min"]), U[n]["p_max"]) for t in range(24)] for n in U}
    # 朴素均分需先满足平衡；此处仅比较“可平衡的时段”的小时成本不低于最优
    ok = [t for t in range(24) if abs(sum(naive[n][t] for n in U) - D[t]) < 1e-6]
    assert ok and all(sum(sv.unit_cost(U[n], naive[n][t]) for n in U) >= r["cost_hourly"][t] - 1e-6 for t in ok)


def test_rolling_locks_executed_hours():
    U = sc.units(); base = sv.solve(U, sc.demand("V1"), _lim(U)); st = sc.REVISION["issued_at_hour"]
    locked = {n: base["output"][n][:st] for n in U}
    r = sv.solve(U, sc.demand("V2"), _lim(U), start=st, locked=locked)
    assert r["status"] == "optimal" and all(r["output"][n][:st] == base["output"][n][:st] for n in U)
    assert sv.verify(U, sc.demand("V2"), _lim(U), r["output"])["pass_rate"] == 1.0


def test_ramp_infeasible_is_reported():
    U = sc.units(); lim = _lim(U); lim["B-U2"]["ramp_h"] = 1; lim["B-U1"]["ramp_h"] = 1
    assert sv.solve(U, sc.demand("V1"), lim)["status"] == "infeasible"


def test_oral_example_numbers():
    U = sc.units(); a = 500 * U["B-U1"]["ref_cost"] + 500 * U["B-U2"]["ref_cost"]; b = 600 * U["B-U1"]["ref_cost"] + 400 * U["B-U2"]["ref_cost"]
    assert (a, b, a - b, round((a - b) / a * 100, 2)) == (315000, 312000, 3000, 0.95)


def test_all_templates_compile_roundtrip():
    for t in compiler.templates().values():
        assert not [i for i in compiler.validate(t["flow"]) if i["level"] == "error"]
        comp = compiler.compile_flow(t["flow"]); assert not compiler.check_providers(comp)
        back = compiler.decompile(comp); assert {n["id"] for n in back["nodes"]} == {n["id"] for n in t["flow"]["nodes"]}
        assert {(e["source"], e["target"]) for e in back["edges"]} == {(e["source"], e["target"]) for e in t["flow"]["edges"]}


def test_validation_catches_missing_upstream_and_cycle():
    f = copy.deepcopy(compiler.templates()["day_ahead_team"]["flow"])
    f["edges"] = [e for e in f["edges"] if e["source"] != "fuel_agent"]
    assert any("cost_model" in i["msg"] for i in compiler.validate(f))
    g = copy.deepcopy(compiler.templates()["day_ahead_team"]["flow"]); g["edges"].append({"source": "reporter", "target": "planner"})
    assert any("环" in i["msg"] for i in compiler.validate(g))


def test_provider_allowlist_blocks_arbitrary_import():
    comp = compiler.compile_flow(compiler.templates()["single_agent"]["flow"])
    comp["config"]["participants"][0]["provider"] = "os.system"
    assert compiler.check_providers(comp) == ["os.system"]
    with pytest.raises(PermissionError): asyncio.run(runner.execute(comp))


def test_end_to_end_day_ahead_then_rolling():
    T = compiler.templates()
    async def go():
        r1 = runner.load_run(await runner.execute(compiler.compile_flow(T["day_ahead_team"]["flow"]), "V1", "day_ahead", wait=True))
        r2 = runner.load_run(await runner.execute(compiler.compile_flow(T["intraday_rolling_team"]["flow"]), "V2", "rolling", wait=True))
        return r1, r2
    r1, r2 = asyncio.run(go())
    assert r1["status"] == r2["status"] == "completed"
    assert r2["artifacts"]["diff"]["locked_hours_unchanged"] is True
    assert r2["artifacts"]["diff"]["changed_hours"] == [18, 19, 20, 21]
    assert "report" in r2["artifacts"] and r2["summary"]["pass_rate"] == 1.0
