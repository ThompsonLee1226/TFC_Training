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

def _encode_promotional_pressure(pp: str) -> float:
    return {"Low": 0.0, "Middle": 0.5, "High": 1.0}[pp]

def _encode_promotion_horizon(ph: str) -> float:
    return {"Short": 0.0, "Medium": 0.5, "Long": 1.0}[ph]

def _encode_trade_unit_sales(tu: str) -> float:
    return {"Pallet": 1.0, "Pallet layer": 0.5}[tu]

CUSTOMER_CI_WEIGHTS = {
    "service_level":        0.002,
    "shelf_life":           0.003,
    "payment_term":        -0.005,
    "trade_unit":           0.03,
    "promotional_pressure": 0.02,
    "promotion_horizon":    0.01,
}
CUSTOMER_CI_BASELINE = {"service_level": 95.0, "shelf_life": 75.0, "payment_term": 4}


def predict_customer_ci(customer_id: str) -> float:
    """根据 CUSTOMER_DECISIONS 中的参数预测客户 Contract Index"""
    d = CUSTOMER_DECISIONS.get(customer_id)
    if not d:
        return 1.0

    w = CUSTOMER_CI_WEIGHTS
    index = 1.000

    index += w["service_level"] * (d["service_level_pct"] - CUSTOMER_CI_BASELINE["service_level"])
    index += w["shelf_life"] * (d["shelf_life_pct"] - CUSTOMER_CI_BASELINE["shelf_life"])
    index += w["payment_term"] * (d["payment_term_weeks"] - CUSTOMER_CI_BASELINE["payment_term"])

    tu = _encode_trade_unit_sales(d["trade_unit"])
    index += w["trade_unit"] * (tu - 0.5) * 2

    pp = _encode_promotional_pressure(d["promotional_pressure"])
    index += w["promotional_pressure"] * (pp - 0.5) * 2

    ph = _encode_promotion_horizon(d["promotion_horizon"])
    index += w["promotion_horizon"] * (ph - 0.5) * 2

    if d.get("vmi"):
        index += 0.005

    return round(max(0.85, min(1.20, index)), 6)


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
