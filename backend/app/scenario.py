"""演示场景数据：两台常规燃煤机组 + 明日 24 点需求（V1）+ 18:00-21:00 最新调度修订（V2）。
全部为模拟数据。需求/机组参数与分段煤耗均可在此替换为真实数据源（见 README §9）。"""
from copy import deepcopy

DATE = "明日(演示日)"
HOURS = list(range(24))

# 每台机组：额定/最小稳定/最大可用/爬坡(MW/min)/初始出力/参考变动成本(元/MWh)
# segments: 分段煤耗成本（凸、边际成本递增）(上端 MW, 边际成本 元/MWh)，p_min 处的基础成本由 base_cost_per_mwh 给出
UNITS = {
    "B-U1": {
        "label": "B-U1 机组", "rated": 600, "p_min": 240, "p_max": 600,
        "ramp_mw_min": 6, "initial": 450, "ref_cost": 300, "fuel": "煤",
        "base_cost_per_mwh": 300,  # 最小稳定出力点的平均成本(演示)
        "segments": [(400, 288), (520, 304), (600, 326)],
    },
    "B-U2": {
        "label": "B-U2 机组", "rated": 600, "p_min": 300, "p_max": 600,
        "ramp_mw_min": 4, "initial": 450, "ref_cost": 330, "fuel": "煤",
        "base_cost_per_mwh": 330,
        "segments": [(420, 318), (520, 332), (600, 348)],
    },
}

# 检修窗口（演示：无）。格式 {unit: [(start_h, end_h_exclusive, max_mw)]}
MAINTENANCE = {"B-U1": [], "B-U2": []}

DEMAND_V1 = [920, 905, 900, 900, 915, 950, 1010, 1060, 1090, 1100, 1085, 1060,
             1030, 1000, 1020, 1045, 1070, 1095, 1100, 1080, 1040, 1000, 960, 930]

# V2：调度下发的最新 18:00-21:00 目标（正常业务更新，非异常）
REVISION = {"issued_at_hour": 17, "window": (18, 21),
            "demand_override": {18: 1160, 19: 1190, 20: 1150, 21: 1090},
            "source": "最新18:00—21:00调度计划"}


def demand(version: str) -> list[float]:
    d = list(DEMAND_V1)
    if version.upper() == "V2":
        for h, v in REVISION["demand_override"].items():
            d[h] = v
    return [float(x) for x in d]


def units() -> dict:
    return deepcopy(UNITS)
