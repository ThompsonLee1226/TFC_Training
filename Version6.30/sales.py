"""
Sales 模块 — 对应游戏 Sales 页面
================================
包含：客户决策参数、周需求数据、客户 Contract Index 模型、销售收入计算。

使用方法：修改 CUSTOMER_DECISIONS 和 WEEKLY_DEMAND 字典，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass, field
import random

from entities import (
    CUSTOMERS, CUSTOMER_MAP, PRODUCTS, PRODUCT_MAP,
)
from config import WEEKS_PER_ROUND


# ═══════════════════════════════════════════════════════════════
# 客户决策参数（对应 Sales 页面每个客户的 SLA 设置）
# ═══════════════════════════════════════════════════════════════

CUSTOMER_DECISIONS: Dict[str, dict] = {
    # Food & Groceries
    "c_fg": {
        "service_level_pct":     95.0,
        "shelf_life_pct":        75.0,
        "order_deadline":        "20:00",
        "trade_unit":            "Pallet layer",
        "payment_term_weeks":    4,
        "promotional_pressure":  "Middle",
        "promotion_horizon":     "Short",
        "vmi":                   False,
    },
    # LAND Market
    "c_land": {
        "service_level_pct":     96.0,
        "shelf_life_pct":        75.0,
        "order_deadline":        "17:00",
        "trade_unit":            "Pallet layer",
        "payment_term_weeks":    4,
        "promotional_pressure":  "Middle",
        "promotion_horizon":     "Short",
        "vmi":                   False,
    },
    # Dominick's
    "c_dom": {
        "service_level_pct":     96.0,
        "shelf_life_pct":        75.0,
        "order_deadline":        "12:00",
        "trade_unit":            "Pallet",
        "payment_term_weeks":    4,
        "promotional_pressure":  "Middle",
        "promotion_horizon":     "Short",
        "vmi":                   False,
    },
}


# ═══════════════════════════════════════════════════════════════
# 周需求数据（pieces / 周）
# 来源：Sales → History → Round 3 → Customer Product report
# ═══════════════════════════════════════════════════════════════

# 格式：{(product_id, customer_id): pieces_per_week}
WEEKLY_DEMAND_PIECES: Dict[Tuple[str, str], int] = {
    # ── Food & Groceries ──
    ("p_orange_1l",  "c_fg"):   42637,
    ("p_ocp_1l",     "c_fg"):    7182,
    ("p_om_1l",      "c_fg"):   26777,
    ("p_orange_pet", "c_fg"):   35873,
    ("p_ocp_pet",    "c_fg"):    5412,
    ("p_om_pet",     "c_fg"):   15539,
    # ── LAND Market ──
    ("p_orange_1l",  "c_land"): 24756,
    ("p_ocp_1l",     "c_land"):  4179,
    ("p_om_1l",      "c_land"): 15385,
    ("p_orange_pet", "c_land"): 11935,
    ("p_ocp_pet",    "c_land"):  1818,
    ("p_om_pet",     "c_land"):  5132,
    # ── Dominick's (仅 PET 产品) ──
    ("p_orange_pet", "c_dom"):  70276,
    ("p_ocp_pet",    "c_dom"):  10512,
    ("p_om_pet",     "c_dom"):  30370,
}

# 从游戏 Sales History 页面提取的实际销售单价（EUR / piece）
# 用于校准和验证
ACTUAL_SALES_PRICES: Dict[Tuple[str, str], float] = {
    ("p_orange_1l",  "c_fg"):   0.46,
    ("p_ocp_1l",     "c_fg"):   0.56,
    ("p_om_1l",      "c_fg"):   0.49,
    ("p_orange_pet", "c_fg"):   0.22,
    ("p_ocp_pet",    "c_fg"):   0.33,
    ("p_om_pet",     "c_fg"):   0.25,
    ("p_orange_1l",  "c_land"): 0.44,
    ("p_ocp_1l",     "c_land"): 0.53,
    ("p_om_1l",      "c_land"): 0.47,
    ("p_orange_pet", "c_land"): 0.21,
    ("p_ocp_pet",    "c_land"): 0.31,
    ("p_om_pet",     "c_land"): 0.24,
    ("p_orange_pet", "c_dom"):  0.23,
    ("p_ocp_pet",    "c_dom"):  0.33,
    ("p_om_pet",     "c_dom"):  0.26,
}


# ═══════════════════════════════════════════════════════════════
# 促销压力对需求的影响
# 来源：sales_info.txt — Promotional pressure 章节
# ═══════════════════════════════════════════════════════════════
#
# 促销压力会增加客户需求量（相对于基准需求）：
#   Benchmark / None  →   0% additional sales
#   Low                →   0.5% - 1.0% additional sales
#   Middle             →   1.5% - 2.0% additional sales
#   High               →   4.0% - 5.5% additional sales
#
# Value for Money 客户: 上述比例翻倍
# Slowmover 产品-客户组合: 上述比例翻倍

# 各促销压力等级对应的需求提升比例（取区间中值）
PROMO_DEMAND_UPLIFT = {
    "Benchmark": 0.0,
    "None":      0.0,
    "Low":       0.0075,    # 0.5%-1.0% → 中值 0.75%
    "Light":     0.0075,
    "Middle":    0.0175,    # 1.5%-2.0% → 中值 1.75%
    "Medium":    0.0175,
    "High":      0.0475,    # 4.0%-5.5% → 中值 4.75%
    "Heavy":     0.0475,
}

# WEEKLY_DEMAND_PIECES 数据采集时的促销状态（Round 3: 所有客户均为 Middle）
ROUND3_PROMO_PRESSURE = "Middle"

# "Value for Money" 客户 ID 集合（促销需求翻倍）
VALUE_FOR_MONEY_CUSTOMERS: set = set()

# Slowmover 产品-客户组合（促销需求翻倍）
# 格式: {(product_id, customer_id), ...}
SLOWMOVER_COMBINATIONS: set = set()

# VMI 项目年费 (€)
# 来源: sales_info.txt — "A VMI project costs €5,000 per annum"
VMI_COST_ANNUAL = 5000.0


def get_promo_demand_multiplier(customer_id: str, product_id: str = None) -> float:
    """获取当前促销压力下的需求乘数（相对于基准需求）。

    multiplier = 1 + uplift × (2 if VFM or slowmover else 1)

    Args:
        customer_id: 客户 ID
        product_id: 产品 ID（用于检查 slowmover 组合）

    Returns:
        需求乘数（≥ 1.0）
    """
    d = CUSTOMER_DECISIONS.get(customer_id)
    if not d:
        return 1.0

    uplift = PROMO_DEMAND_UPLIFT.get(d["promotional_pressure"], 0.0)

    # Value for Money 客户: 翻倍
    if customer_id in VALUE_FOR_MONEY_CUSTOMERS:
        uplift *= 2.0

    # Slowmover 产品-客户组合: 翻倍
    if product_id and (product_id, customer_id) in SLOWMOVER_COMBINATIONS:
        uplift *= 2.0

    return 1.0 + uplift


def get_effective_weekly_demand_pieces() -> Dict[Tuple[str, str], float]:
    """计算有效周需求（应用当前促销压力后的需求量）。

    WEEKLY_DEMAND_PIECES 来自 Round 3 游戏数据，当时所有客户为 Middle 促销压力。
    此函数先还原为基准需求（无促销），再应用 CUSTOMER_DECISIONS 中当前促销的乘数。

    Returns:
        {(product_id, customer_id): effective_pieces_per_week}
    """
    round3_multiplier = 1.0 + PROMO_DEMAND_UPLIFT.get(ROUND3_PROMO_PRESSURE, 0.0175)
    effective = {}
    for (pid, cid), pieces in WEEKLY_DEMAND_PIECES.items():
        benchmark = pieces / round3_multiplier
        current_multiplier = get_promo_demand_multiplier(cid, pid)
        effective[(pid, cid)] = round(benchmark * current_multiplier, 4)
    return effective


# ═══════════════════════════════════════════════════════════════
# 需求辅助函数
# ═══════════════════════════════════════════════════════════════

def weekly_demand_liters(product_id: str = None, customer_id: str = None,
                         effective: bool = True) -> float:
    """查询周需求（升）。可指定产品/客户，或汇总全部。

    Args:
        effective: True=应用当前促销压力后的有效需求，False=使用原始游戏数据
    """
    demand_data = get_effective_weekly_demand_pieces() if effective else WEEKLY_DEMAND_PIECES
    total = 0.0
    for (pid, cid), pieces in demand_data.items():
        if product_id and pid != product_id:
            continue
        if customer_id and cid != customer_id:
            continue
        p = PRODUCT_MAP.get(pid)
        if p:
            total += pieces * p.liters_per_pack
    return total


def weekly_demand_by_product(effective: bool = True) -> Dict[str, float]:
    """每种产品的周需求（升）"""
    demand_data = get_effective_weekly_demand_pieces() if effective else WEEKLY_DEMAND_PIECES
    result: Dict[str, float] = {}
    for (pid, _), pieces in demand_data.items():
        p = PRODUCT_MAP.get(pid)
        liters = pieces * (p.liters_per_pack if p else 1.0)
        result[pid] = result.get(pid, 0.0) + liters
    return result


def weekly_demand_by_customer(effective: bool = True) -> Dict[str, float]:
    """每个客户的周需求（升）"""
    demand_data = get_effective_weekly_demand_pieces() if effective else WEEKLY_DEMAND_PIECES
    result: Dict[str, float] = {}
    for (pid, cid), pieces in demand_data.items():
        p = PRODUCT_MAP.get(pid)
        liters = pieces * (p.liters_per_pack if p else 1.0)
        result[cid] = result.get(cid, 0.0) + liters
    return result


def total_round_demand_liters(effective: bool = True) -> float:
    """整轮（26 周）总需求（升）"""
    return weekly_demand_liters(effective=effective) * WEEKS_PER_ROUND


def get_vmi_annual_cost() -> float:
    """计算 VMI 项目年费总额。

    来源: sales_info.txt — "A VMI project costs €5,000 per annum"
    对每个启用 VMI 的客户收取 €5,000/年。

    Returns:
        总 VMI 年费 (€)
    """
    total = 0.0
    for cid, d in CUSTOMER_DECISIONS.items():
        if d.get("vmi", False):
            total += VMI_COST_ANNUAL
    return total


# ═══════════════════════════════════════════════════════════════
# Customer Contract Index 模型
# ═══════════════════════════════════════════════════════════════
#
# 公式来源：基于 TFC 游戏网站三个客户共 125 次实验数据的回归分析
# 实验设计：OFAT + 交互项测试 (FG=69, LAND=28, Dominick's=28)
#
# 模型结构（三个客户共享）：
#   CI = bl_ci
#      + 分段SL效应 (<bl_sl: sl_lo×Δ, >bl_sl: sl_hi×Δ)
#      + slf_main × (SLf_benefit偏离, 范围 [40%, 80%])
#      - slf_pen × max(0, SLf - 80)
#      + pt_main × (min(PT,6)偏离)
#      + od × (OrderDeadline偏离, VMI开启时覆盖为14:00)
#      + pp × (PromoPressure偏离)
#      + ph × (PromoHorizon偏离)
#      + vmi × (VMI偏离)
#
# 硬规则（三个客户共享）：SLf ≥ 90% → CI 锁定为客户各自的 bl_ci
#
# 各客户拟合性能：
#   Food & Groceries: R²=0.9949  RMSE=0.0048
#   LAND Market:      R²=0.9969  RMSE=0.0030
#   Dominick's:       R²=0.9925  RMSE=0.0026
# ═══════════════════════════════════════════════════════════════

# ── 编码函数 ──

def _encode_order_deadline(od_str: str) -> float:
    """Order Deadline → 数值索引"""
    od_map = {
        "12:00": 0.0, "12.00 pm": 0.0, "12": 0.0,
        "14:00": 1.0, "14.00 pm": 1.0, "14": 1.0,
        "17:00": 2.0, "17.00 pm": 2.0, "17": 2.0,
        "20:00": 3.0, "20.00 pm": 3.0, "20": 3.0,
    }
    for key, val in od_map.items():
        if key in str(od_str):
            return val
    return 1.0

def _encode_trade_unit(tu: str) -> float:
    """Trade Unit → 数值"""
    return {"Box": 0.0, "Pallet layer": 1.0, "Pallet": 2.0}.get(tu, 1.0)

def _encode_promo_pressure(pp: str) -> float:
    """Promotional Pressure → 数值 (4级: None/Light/Middle/Heavy)"""
    return {"None": 0.0, "Light": 1.0, "Middle": 2.0, "Heavy": 3.0,
            "Low": 0.0, "Medium": 2.0, "High": 3.0}.get(pp, 2.0)

def _encode_promo_horizon(ph: str) -> float:
    """Promotion Horizon → 数值"""
    return {"Short": 0.0, "Middle": 1.0, "Medium": 1.0, "Long": 2.0}.get(ph, 0.0)


# ── 客户特定 CI 配置 ──
# bl = 该客户在当前游戏状态下的"基准点"参数和 CI 值
# coefs = 该客户对各因子的敏感度系数

CUSTOMER_CI_CONFIG = {
    "c_fg": {
        "bl": {"sl": 95.0, "slf": 75.0, "pt": 3, "od": 1, "tu": 1, "pp": 2, "ph": 0, "vmi": 0, "ci": 0.9985},
        "coefs": {
            "sl_lo": 0.025000,    # SL < bl_sl: per % effect
            "sl_hi": 0.012750,    # SL > bl_sl: per % effect (饱和)
            "slf_main": 0.006300, # Shelf Life benefit per % [50-80]
            "slf_pen":  0.003150, # Shelf Life penalty per % > 80
            "pt_main":  0.001930, # Payment Term per week (≤6)
            "od":       0.004000, # Order Deadline per step
            "pp":      -0.005500, # Promo Pressure per level
            "ph":      -0.002725, # Promo Horizon per level
            "vmi":     -0.000600, # VMI on/off
        },
    },
    "c_land": {
        "bl": {"sl": 95.0, "slf": 75.0, "pt": 3, "od": 1, "tu": 1, "pp": 2, "ph": 0, "vmi": 0, "ci": 0.9570},
        "coefs": {
            "sl_lo": 0.012000,
            "sl_hi": 0.006504,
            "slf_main": 0.005600,
            "slf_pen":  0.002800,
            "pt_main":  0.001933,
            "od":       0.002500,
            "pp":      -0.001500,
            "ph":      -0.000750,
            "vmi":     -0.001200,
        },
    },
    "c_dom": {
        "bl": {"sl": 95.0, "slf": 70.0, "pt": 4, "od": 1, "tu": 2, "pp": 3, "ph": 0, "vmi": 0, "ci": 0.9977},
        "coefs": {
            "sl_lo": 0.010520,
            "sl_hi": 0.005678,
            "slf_main": 0.002800,
            "slf_pen":  0.001400,
            "pt_main":  0.001900,
            "od":       0.005000,
            "pp":      -0.010000,
            "ph":      -0.002500,
            "vmi":      0.000000,
        },
    },
}


def predict_customer_ci(customer_id: str) -> float:
    """
    根据 CUSTOMER_DECISIONS 中的参数预测客户 Contract Index。

    基于 TFC 三个客户共 125 次实验数据的客户特定模型。
    共享公式结构，每个客户有独立的基准值和敏感度系数。

    硬规则：Shelf Life ≥ 90% → CI 锁定为客户的基准 CI
    """
    d = CUSTOMER_DECISIONS.get(customer_id)
    if not d:
        return 1.0

    cfg = CUSTOMER_CI_CONFIG.get(customer_id)
    if not cfg:
        return 1.0

    bl = cfg["bl"]
    c = cfg["coefs"]

    # ── 编码当前参数 ──
    sl = d["service_level_pct"]
    slf = d["shelf_life_pct"]
    pt = float(d["payment_term_weeks"])
    # VMI 开启时订单截止时间覆盖为 14:00（订单可提前准备）
    # 来源: sales_info.txt — "the order placement deadline can be lowered to 14:00"
    vmi_enabled = d.get("vmi", False)
    effective_od_str = "14:00" if vmi_enabled else d["order_deadline"]
    od = _encode_order_deadline(effective_od_str)
    tu = _encode_trade_unit(d["trade_unit"])
    pp = _encode_promo_pressure(d["promotional_pressure"])
    ph = _encode_promo_horizon(d["promotion_horizon"])
    vmi = 1.0 if vmi_enabled else 0.0

    # ── 硬规则: SLf ≥ 90% → CI = bl_ci ──
    if slf >= 90.0:
        return bl["ci"]

    # ── 基准值 ──
    ci = bl["ci"]

    # ── 1. Service Level: 分段线性 ──
    sl_dev = sl - bl["sl"]
    if sl_dev < 0:
        ci += c["sl_lo"] * sl_dev
    else:
        ci += c["sl_hi"] * sl_dev

    # ── 2. Shelf Life: Benefit + Penalty ──
    # 受益区间: [40%, 80%]（对齐 sales_info.txt 最低 40%、最高 85% 的规定）
    slf_benefit = max(0.0, min(slf, 80.0) - 40.0)
    bl_benefit = max(0.0, min(bl["slf"], 80.0) - 40.0)
    ci += c["slf_main"] * (slf_benefit - bl_benefit)

    slf_penalty = max(0.0, slf - 80.0)
    ci -= c["slf_pen"] * slf_penalty

    # ── 3. Payment Term: 封顶于6周 ──
    pt_eff = min(pt, 6.0)
    ci += c["pt_main"] * (pt_eff - min(float(bl["pt"]), 6.0))

    # ── 4-8. 次要因子 (相对于各客户自身基准的偏差) ──
    ci += c["od"] * (od - bl["od"])
    ci += c["pp"] * (pp - bl["pp"])
    ci += c["ph"] * (ph - bl["ph"])
    ci += c["vmi"] * (vmi - bl["vmi"])

    # ── 约束 CI 范围 ──
    return round(max(0.70, min(1.07, ci)), 6)


def get_customer_ci_deltas() -> Dict[str, float]:
    """每个客户 CI 变化倍数（新决策 CI / 原始 CI）"""
    deltas = {}
    for c in CUSTOMERS:
        new_ci = predict_customer_ci(c.id)
        deltas[c.id] = new_ci / c.contract_index if c.contract_index else 1.0
    return deltas


# ═══════════════════════════════════════════════════════════════
# 日级需求配置
# ═══════════════════════════════════════════════════════════════

# 每日需求权重（周一至周五），默认均匀分配
# 例如 [0.25, 0.15, 0.20, 0.25, 0.15] 表示周一和周四需求更高
DAILY_DEMAND_WEIGHTS = [0.20, 0.20, 0.20, 0.20, 0.20]

# 日需求随机波动标准差（相对值），仅 USE_NOISE=True 时生效
DAILY_DEMAND_NOISE_STD = 0.05


# ═══════════════════════════════════════════════════════════════
# 日级销售仿真 — 数据结构和模拟器
# ═══════════════════════════════════════════════════════════════
#
# 设计原则（对齐 operations.py 日级仿真）：
#   - 每周拆为 5 个工作日 (Mon-Fri)，逐天模拟
#   - 日需求 = 周需求 × 日权重 + 可选的随机波动
#   - 逐天库存检查：成品库存不足时等比缩减发货量
#   - 日级服务水平 = 当天发货 / 当天需求
#   - 对外接口不变：weekly_demand_*() 和 calculate_revenue() 保持兼容
# ═══════════════════════════════════════════════════════════════


@dataclass
class DailySalesResult:
    """单日销售结果（日级离散仿真的最小单元）"""
    day: int                                              # 1-5 (Mon-Fri)
    demand_liters: float = 0.0                            # 当天订单需求量
    fulfilled_liters: float = 0.0                         # 当天实际发货量
    shortfall_liters: float = 0.0                         # 当天未满足的需求
    revenue: float = 0.0                                  # 当天销售收入
    service_level: float = 1.0                            # 当天服务水平 = fulfilled/demand
    # 明细
    demand_by_product: Dict[str, float] = field(default_factory=dict)
    fulfilled_by_product: Dict[str, float] = field(default_factory=dict)
    revenue_by_customer: Dict[str, float] = field(default_factory=dict)
    revenue_by_product: Dict[str, float] = field(default_factory=dict)


@dataclass
class WeeklySalesResult:
    """一周销售结果（由 5 个 DailySalesResult 汇总）"""
    week: int
    total_demand_liters: float = 0.0
    total_fulfilled_liters: float = 0.0
    total_shortfall_liters: float = 0.0
    total_revenue: float = 0.0
    service_level: float = 1.0                            # 加权平均服务水平
    daily_results: List[DailySalesResult] = field(default_factory=list)
    revenue_by_customer: Dict[str, float] = field(default_factory=dict)
    revenue_by_product: Dict[str, float] = field(default_factory=dict)


class DailySalesSimulator:
    """日级离散销售仿真器。

    将每周需求拆分为 5 个工作日，逐天模拟订单接收、库存检查和发货。
    支持可选的成品库存约束，缺货时按比例缩减发货量。

    核心改进（对齐 operations.py 的日级仿真模式）：
      1. 日级需求拆分 — 周需求按权重分配到每天，支持随机波动
      2. 逐天库存检查 — 每天独立检查 FG 库存，不足则等比缩减
      3. 日级服务水平 — fulfilled/demand 按天计算，可汇总为周/轮级别
      4. 跨天库存追踪 — 前一天的发货会消耗库存，影响后一天的可用量
      5. 对外接口不变 — weekly_demand_*() 和 calculate_revenue() 保持兼容
    """

    DAYS_PER_WEEK = 5

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._ci_deltas: Dict[str, float] = {}

    # ── 日需求拆分 ──────────────────────────────────────────

    def _split_weekly_to_daily(self) -> List[Dict[Tuple[str, str], float]]:
        """将有效周需求按 DAILY_DEMAND_WEIGHTS 拆分为 5 天需求。

        使用 get_effective_weekly_demand_pieces() 以反映促销压力对需求的影响。

        返回:
            [{ (product_id, customer_id): daily_pieces }, ...] 长度为 5
        """
        from config import USE_NOISE

        # 使用有效需求（已应用促销压力乘数）
        effective_weekly = get_effective_weekly_demand_pieces()

        weights = DAILY_DEMAND_WEIGHTS
        # 归一化确保总需求不变
        total_w = sum(weights)
        norm_weights = [w / total_w for w in weights]

        daily_demands: List[Dict[Tuple[str, str], float]] = []
        for day_idx in range(self.DAYS_PER_WEEK):
            day: Dict[Tuple[str, str], float] = {}
            weight = norm_weights[day_idx]
            for (pid, cid), weekly_pieces in effective_weekly.items():
                daily_pieces = weekly_pieces * weight
                # 离散日间波动（独立随机，模拟客户每日下单的自然波动）
                if USE_NOISE:
                    noise = self.rng.gauss(0.0, DAILY_DEMAND_NOISE_STD)
                    daily_pieces *= (1.0 + noise)
                    daily_pieces = max(0.0, daily_pieces)
                if daily_pieces > 0.01:
                    day[(pid, cid)] = round(daily_pieces, 4)
            daily_demands.append(day)

        return daily_demands

    # ── 日级仿真核心 ────────────────────────────────────────

    def simulate_day(self, day: int,
                     daily_demand: Dict[Tuple[str, str], float],
                     fg_inventory: Optional[Dict[str, float]] = None
                     ) -> DailySalesResult:
        """模拟单日销售。

        当天需求先按产品汇总，再与成品库存比对。
        库存不足时等比缩减所有客户订单（公平分配）。

        Args:
            day: 1-5 (Mon-Fri)
            daily_demand: {(product_id, customer_id): pieces} 当天订单量
            fg_inventory: 可选，{product_id: available_liters} 成品可用库存。
                          传入后按产品检查库存约束，不足则等比缩减。
                          不传则假定库存无限（向后兼容，全部满足）。

        Returns:
            DailySalesResult 包含当日发货量、收入、服务水平和明细
        """
        result = DailySalesResult(day=day)
        ci_deltas = get_customer_ci_deltas()
        self._ci_deltas = ci_deltas

        if not daily_demand:
            return result

        # ── 1) 汇总当天需求（按产品升数 & 按产品-客户升数）──
        product_demand: Dict[str, float] = {}       # pid → total liters
        detail_demand: Dict[Tuple[str, str], float] = {}  # (pid, cid) → liters

        for (pid, cid), pieces in daily_demand.items():
            p = PRODUCT_MAP.get(pid)
            if not p:
                continue
            liters = pieces * p.liters_per_pack
            detail_demand[(pid, cid)] = liters
            product_demand[pid] = product_demand.get(pid, 0.0) + liters
            result.demand_by_product[pid] = result.demand_by_product.get(pid, 0.0) + liters

        original_total_demand = sum(product_demand.values())
        result.demand_liters = original_total_demand

        # ── 2) 库存约束（对齐 operations._check_component_availability 的逻辑）──
        # 找最紧张的产品 → 确定最大可行比例 → 等比缩减所有客户订单
        # 注意：fg_inventory 中未列出的产品视为不限量（与 operations 的 component_stock 一致）
        scale_factor = 1.0
        if fg_inventory is not None:
            for pid, need in product_demand.items():
                if pid not in fg_inventory:
                    continue  # 未传入 = 不限量
                available = fg_inventory[pid]
                if need > 0 and available < need:
                    s = available / need
                    if s < scale_factor:
                        scale_factor = s

        # ── 3) 按比例发货 & 计算收入 ──
        for (pid, cid), liters in detail_demand.items():
            p = PRODUCT_MAP.get(pid)
            if not p or liters <= 0:
                continue

            fulfilled = liters * scale_factor
            if fulfilled < 0.001:
                continue

            # 使用游戏实际售价作为基准，乘以 CI delta
            actual_price = ACTUAL_SALES_PRICES.get((pid, cid), p.base_price)
            price_per_liter = actual_price / p.liters_per_pack

            rev = fulfilled * price_per_liter * ci_deltas.get(cid, 1.0)

            result.fulfilled_liters += fulfilled
            result.revenue += rev
            result.fulfilled_by_product[pid] = (
                result.fulfilled_by_product.get(pid, 0.0) + fulfilled)
            result.revenue_by_customer[cid] = (
                result.revenue_by_customer.get(cid, 0.0) + rev)
            result.revenue_by_product[pid] = (
                result.revenue_by_product.get(pid, 0.0) + rev)

            # 消耗成品库存（供调用方更新）
            if fg_inventory is not None and pid in fg_inventory:
                fg_inventory[pid] = max(0.0, fg_inventory[pid] - fulfilled)

        # ── 4) Shortfall & Service Level ──
        result.shortfall_liters = max(0.0, original_total_demand - result.fulfilled_liters)
        result.service_level = (result.fulfilled_liters / original_total_demand
                                if original_total_demand > 0 else 1.0)

        return result

    # ── 周级接口（兼容旧调用方）─────────────────────────────

    def simulate_week(self, week: int,
                      fg_inventory: Optional[Dict[str, float]] = None
                      ) -> WeeklySalesResult:
        """模拟一周销售（日级离散）。

        Args:
            week: 周次
            fg_inventory: 可选，{product_id: available_liters} 成品初始库存。
                          传入后会逐天消耗；不传则假定库存无限。

        流程:
          1. 按权重拆分周需求 → 5 天日需求
          2. 逐天 simulate_day()
          3. 汇总 WeeklySalesResult
        """
        result = WeeklySalesResult(week=week)
        daily_demands = self._split_weekly_to_daily()

        for day_idx, day_demand in enumerate(daily_demands):
            day_result = self.simulate_day(
                day=day_idx + 1,
                daily_demand=day_demand,
                fg_inventory=fg_inventory,  # 逐天消耗同一份库存
            )
            result.daily_results.append(day_result)
            result.total_demand_liters += day_result.demand_liters
            result.total_fulfilled_liters += day_result.fulfilled_liters
            result.total_shortfall_liters += day_result.shortfall_liters
            result.total_revenue += day_result.revenue

            # 汇总 revenue_by_customer / by_product
            for cid, rev in day_result.revenue_by_customer.items():
                result.revenue_by_customer[cid] = (
                    result.revenue_by_customer.get(cid, 0.0) + rev)
            for pid, rev in day_result.revenue_by_product.items():
                result.revenue_by_product[pid] = (
                    result.revenue_by_product.get(pid, 0.0) + rev)

        # 加权平均服务水平
        result.service_level = (result.total_fulfilled_liters / result.total_demand_liters
                                if result.total_demand_liters > 0 else 1.0)
        return result

    # ── 整轮仿真 ──────────────────────────────────────────

    def calculate_round_revenue(self,
                                 fg_inventory_by_week: Optional[Dict[int, Dict[str, float]]] = None
                                 ) -> Dict:
        """使用日级仿真计算整轮（26 周）销售收入。

        Args:
            fg_inventory_by_week: 可选，{week: {product_id: available_liters}}
                                  每周初始的成品库存。传入后库存约束逐天生效。

        返回:
            与 calculate_revenue() 相同格式的字典:
            {
                "total_revenue": float,
                "by_customer": {customer_id: float},
                "by_product": {product_id: float},
                "ci_deltas": {customer_id: delta},
                "service_level": float,
                "weekly_results": [WeeklySalesResult, ...],
            }
        """
        total_revenue = 0.0
        by_customer: Dict[str, float] = {}
        by_product: Dict[str, float] = {}
        all_weekly: List[WeeklySalesResult] = []
        total_demand = 0.0
        total_fulfilled = 0.0

        for week in range(1, WEEKS_PER_ROUND + 1):
            fg_inv = (fg_inventory_by_week.get(week)
                      if fg_inventory_by_week else None)
            wr = self.simulate_week(week, fg_inventory=fg_inv)
            all_weekly.append(wr)

            total_revenue += wr.total_revenue
            total_demand += wr.total_demand_liters
            total_fulfilled += wr.total_fulfilled_liters

            for cid, rev in wr.revenue_by_customer.items():
                by_customer[cid] = by_customer.get(cid, 0.0) + rev
            for pid, rev in wr.revenue_by_product.items():
                by_product[pid] = by_product.get(pid, 0.0) + rev

        ci_deltas = get_customer_ci_deltas()
        service_level = total_fulfilled / total_demand if total_demand > 0 else 1.0

        return {
            "total_revenue": total_revenue,
            "by_customer": by_customer,
            "by_product": by_product,
            "ci_deltas": ci_deltas,
            "service_level": service_level,
            "weekly_results": all_weekly,
        }


# ═══════════════════════════════════════════════════════════════
# 销售收入计算（周级，向后兼容）
# ═══════════════════════════════════════════════════════════════

def calculate_revenue() -> Dict:
    """
    计算 26 周销售收入。

    逻辑：Revenue = Σ(有效周需求 × 26 × 基础售价 × 客户 CI)
    有效需求已包含促销压力的影响，使用游戏实际售价数据进行标定。

    返回:
        {
            "total_revenue": float,
            "by_customer": {customer_id: float},
            "by_product": {product_id: float},
            "ci_deltas": {customer_id: delta},
        }
    """
    total_revenue = 0.0
    by_customer: Dict[str, float] = {}
    by_product: Dict[str, float] = {}
    ci_deltas = get_customer_ci_deltas()

    # 使用有效需求（已应用促销压力影响）
    effective_demand = get_effective_weekly_demand_pieces()
    for (pid, cid), pieces in effective_demand.items():
        p = PRODUCT_MAP.get(pid)
        if not p:
            continue
        liters_per_week = pieces * p.liters_per_pack
        # 使用实际售价（来自游戏数据）作为基准，乘以 CI delta 反映决策变化
        actual_price = ACTUAL_SALES_PRICES.get((pid, cid), p.base_price)
        price_per_liter = actual_price / p.liters_per_pack  # 换算为 EUR/L

        weekly_revenue = liters_per_week * price_per_liter * ci_deltas.get(cid, 1.0)
        round_revenue = weekly_revenue * WEEKS_PER_ROUND

        total_revenue += round_revenue
        by_customer[cid] = by_customer.get(cid, 0.0) + round_revenue
        by_product[pid] = by_product.get(pid, 0.0) + round_revenue

    return {
        "total_revenue": total_revenue,
        "by_customer": by_customer,
        "by_product": by_product,
        "ci_deltas": ci_deltas,
    }


# ═══════════════════════════════════════════════════════════════
# 校准报告
# ═══════════════════════════════════════════════════════════════

def calibration_report() -> str:
    """客户 CI 预测值 vs 实际值对比"""
    lines = ["Customer Contract Index 校准", "-" * 50]
    lines.append(f"{'Customer':<28} {'Actual':>7} {'Pred':>7} {'Err':>7}")
    lines.append("-" * 50)
    for c in CUSTOMERS:
        pred = predict_customer_ci(c.id)
        err = pred - c.contract_index
        lines.append(f"{c.name:<28} {c.contract_index:>7.4f} {pred:>7.4f} {err:>+7.4f}")
    return "\n".join(lines)
