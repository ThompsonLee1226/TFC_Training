"""
Sales 模块 — 对应游戏 Sales 页面
================================
包含：客户决策参数、周需求数据、客户 Contract Index 模型、销售收入计算。

使用方法：修改 CUSTOMER_DECISIONS 和 WEEKLY_DEMAND 字典，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, Tuple
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
# 需求辅助函数
# ═══════════════════════════════════════════════════════════════

def weekly_demand_liters(product_id: str = None, customer_id: str = None) -> float:
    """查询周需求（升）。可指定产品/客户，或汇总全部。"""
    total = 0.0
    for (pid, cid), pieces in WEEKLY_DEMAND_PIECES.items():
        if product_id and pid != product_id:
            continue
        if customer_id and cid != customer_id:
            continue
        p = PRODUCT_MAP.get(pid)
        if p:
            total += pieces * p.liters_per_pack
    return total


def weekly_demand_by_product() -> Dict[str, float]:
    """每种产品的周需求（升）"""
    result: Dict[str, float] = {}
    for (pid, _), pieces in WEEKLY_DEMAND_PIECES.items():
        p = PRODUCT_MAP.get(pid)
        liters = pieces * (p.liters_per_pack if p else 1.0)
        result[pid] = result.get(pid, 0.0) + liters
    return result


def weekly_demand_by_customer() -> Dict[str, float]:
    """每个客户的周需求（升）"""
    result: Dict[str, float] = {}
    for (pid, cid), pieces in WEEKLY_DEMAND_PIECES.items():
        p = PRODUCT_MAP.get(pid)
        liters = pieces * (p.liters_per_pack if p else 1.0)
        result[cid] = result.get(cid, 0.0) + liters
    return result


def total_round_demand_liters() -> float:
    """整轮（26 周）总需求（升）"""
    return weekly_demand_liters() * WEEKS_PER_ROUND


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
#      + slf_main × (SLf_benefit偏离)
#      - slf_pen × max(0, SLf - 80)
#      + pt_main × (min(PT,6)偏离)
#      + od × (OrderDeadline偏离)
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
    od = _encode_order_deadline(d["order_deadline"])
    tu = _encode_trade_unit(d["trade_unit"])
    pp = _encode_promo_pressure(d["promotional_pressure"])
    ph = _encode_promo_horizon(d["promotion_horizon"])
    vmi = 1.0 if d.get("vmi") else 0.0

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
    slf_benefit = max(0.0, min(slf, 80.0) - 50.0)
    bl_benefit = max(0.0, min(bl["slf"], 80.0) - 50.0)
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
# 销售收入计算
# ═══════════════════════════════════════════════════════════════

def calculate_revenue() -> Dict:
    """
    计算 26 周销售收入。

    逻辑：Revenue = Σ(周需求 × 26 × 基础售价 × 客户 CI)
    使用游戏实际售价数据进行标定。

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

    for (pid, cid), pieces in WEEKLY_DEMAND_PIECES.items():
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
