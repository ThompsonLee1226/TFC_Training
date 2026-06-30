"""
TFC Contract Index 模型 — SLA参数 → 价格乘数

Contract Index 是 TFC 的核心价格机制:
  - 供应商: 更好条款 → 更高Index → 更高采购成本
  - 客户: 更好条款 → 更高Index → 更高售价

模型采用加权线性映射 + 最小二乘拟合，用 8 个已知值标定。
"""

from typing import Dict, Any
import math


# ── 参数编码 ──────────────────────────────────────────

def encode_quality(quality_str: str) -> float:
    """Quality → [0, 1], High=1.0, Middle=0.5, Poor=0.0"""
    return {"High": 1.0, "Middle": 0.5, "Poor": 0.0}.get(quality_str, 0.5)


def encode_delivery_window(window_str: str) -> float:
    """Delivery window → [0, 1], 越短越苛刻 (导致更高Index)"""
    return {"4 hours": 1.0, "1 day": 0.75, "2 days": 0.5, "1 week": 0.25}.get(window_str, 0.5)


def encode_trade_unit_purchasing(unit_str: str) -> float:
    """Trade unit for purchasing → [0, 1], 越大越便宜"""
    return {"Tank": 1.0, "IBC": 0.6, "FTL": 0.4, "Pallet": 0.2}.get(unit_str, 0.3)


def encode_trade_unit_sales(unit_str: str) -> float:
    """Trade unit for sales → [0, 1], 越大越有利于客户 → 更高Index"""
    return {"Pallet": 1.0, "Pallet layer": 0.5}.get(unit_str, 0.5)


def encode_promotional_pressure(pressure_str: str) -> float:
    """Promotional pressure → [0, 1]"""
    return {"Low": 0.0, "Middle": 0.5, "High": 1.0}.get(pressure_str, 0.5)


def encode_promotion_horizon(horizon_str: str) -> float:
    """Promotion horizon → [0, 1]"""
    return {"Short": 0.0, "Medium": 0.5, "Long": 1.0}.get(horizon_str, 0.5)


# ── 权重模型（基于经济学直觉 + 最小二乘标定） ──────

# ══════════════════════════════════════════════════════════════════════════════
# 可调参数 — 集中声明，方便调参
# ══════════════════════════════════════════════════════════════════════════════

# ── 供应商 Contract Index 权重 ──
# 解释变量: quality, delivery_window, delivery_reliability, payment_term, trade_unit, free_capacity
SUPPLIER_WEIGHTS = {
    "quality":              0.04,   # High +0.04, Poor -0.04
    "delivery_window":      0.06,   # 4h +0.06, 1week -0.06
    "delivery_reliability": 0.0008, # per % above/below baseline
    "payment_term":         0.004,  # per week above/below baseline
    "trade_unit":          -0.03,   # Tank/IBC 折扣, Pallet 溢价
}

SUPPLIER_BASELINE = {
    "delivery_reliability": 90.0,
    "payment_term": 6,
}

SUPPLIER_BASE_INDEX: float = 0.995       # 供应商 CI 基准值
FREE_CAPACITY_COEFF: float = -0.0005     # 产能系数 (每%偏离基线)
FREE_CAPACITY_BASELINE: float = 20.0     # 产能基线 (%)
VMI_SUPPLIER_DELTA: float = -0.005       # VMI 对供应商 CI 的影响
SUPPLIER_DEV_DELTA: float = -0.010       # 供应商发展项目对 CI 的影响

# ── 客户 Contract Index 权重 ──
CUSTOMER_WEIGHTS = {
    "service_level":        0.002,  # per % above/below baseline
    "shelf_life":           0.003,  # per % above/below baseline
    "payment_term":        -0.005,  # per week above/below (更长对客户有利)
    "trade_unit":           0.03,   # Pallet vs Pallet layer
    "promotional_pressure": 0.02,
    "promotion_horizon":    0.01,
}

CUSTOMER_BASELINE = {
    "service_level": 95.0,
    "shelf_life": 75.0,
    "payment_term": 4,
}

CUSTOMER_BASE_INDEX: float = 1.000      # 客户 CI 基准值
VMI_CUSTOMER_DELTA: float = 0.005       # VMI 对客户 CI 的影响

# ── Contract Index 裁剪范围 ──
CI_CLAMP_MIN: float = 0.85
CI_CLAMP_MAX: float = 1.20


def predict_supplier_contract_index(
    quality: str,
    delivery_window: str,
    delivery_reliability_pct: float,
    payment_term_weeks: int,
    trade_unit: str,
    free_capacity_pct: float = 20.0,
    vmi: bool = False,
    supplier_development: bool = False,
) -> float:
    """
    预测供应商 Contract Index。
    基准 0.995, 各参数边际调整。
    """
    index = SUPPLIER_BASE_INDEX

    w = SUPPLIER_WEIGHTS

    # Quality (centered at Middle=0.5)
    quality_val = encode_quality(quality)
    index += w["quality"] * (quality_val - 0.5) * 2  # range [-0.04, +0.04]

    # Delivery window (centered at 1day=0.75)
    dw_val = encode_delivery_window(delivery_window)
    index += w["delivery_window"] * (dw_val - 0.75) * 4  # range [-0.06, +0.06]

    # Delivery reliability
    index += w["delivery_reliability"] * (delivery_reliability_pct - SUPPLIER_BASELINE["delivery_reliability"])

    # Payment term (longer = supplier provides financing = higher index)
    index += w["payment_term"] * (payment_term_weeks - SUPPLIER_BASELINE["payment_term"])

    # Trade unit (bulk = discount)
    tu_val = encode_trade_unit_purchasing(trade_unit)
    index += w["trade_unit"] * (tu_val - 0.4) * 2

    # Free capacity (tight = supplier has power = higher index)
    index += FREE_CAPACITY_COEFF * (free_capacity_pct - FREE_CAPACITY_BASELINE)

    # Collaboration projects
    if vmi:
        index += VMI_SUPPLIER_DELTA  # VMI reduces supplier cost
    if supplier_development:
        index += SUPPLIER_DEV_DELTA  # Supplier dev investment pays off

    return round(max(CI_CLAMP_MIN, min(CI_CLAMP_MAX, index)), 6)


def predict_customer_contract_index(
    service_level_pct: float,
    shelf_life_pct: float,
    payment_term_weeks: int,
    trade_unit: str,
    promotional_pressure: str,
    promotion_horizon: str,
    vmi: bool = False,
) -> float:
    """
    预测客户 Contract Index。
    基准 1.000, 各参数边际调整。
    """
    index = CUSTOMER_BASE_INDEX
    w = CUSTOMER_WEIGHTS

    # Service level (higher = better for customer = higher price)
    index += w["service_level"] * (service_level_pct - CUSTOMER_BASELINE["service_level"])

    # Shelf life (higher = better for customer = higher price)
    index += w["shelf_life"] * (shelf_life_pct - CUSTOMER_BASELINE["shelf_life"])

    # Payment term (longer = customer pays later = worth more → higher index)
    index += w["payment_term"] * (payment_term_weeks - CUSTOMER_BASELINE["payment_term"])

    # Trade unit (Pallet = cheaper for customer than Pallet layer)
    tu_val = encode_trade_unit_sales(trade_unit)
    index += w["trade_unit"] * (tu_val - 0.5) * 2

    # Promotional pressure (higher = more sales = higher price)
    pp_val = encode_promotional_pressure(promotional_pressure)
    index += w["promotional_pressure"] * (pp_val - 0.5) * 2

    # Promotion horizon (longer = more commitment = better price)
    ph_val = encode_promotion_horizon(promotion_horizon)
    index += w["promotion_horizon"] * (ph_val - 0.5) * 2

    # VMI (retailer benefits → slightly higher price)
    if vmi:
        index += VMI_CUSTOMER_DELTA

    return round(max(CI_CLAMP_MIN, min(CI_CLAMP_MAX, index)), 6)


# ── 模型校准报告 ──────────────────────────────────────

def calibration_report() -> str:
    """输出模型预测 vs 实际 Contract Index 对比"""
    from entities import SUPPLIERS, CUSTOMERS

    lines = ["Contract Index 模型校准报告", "=" * 60, ""]

    lines.append("--- 供应商 ---")
    lines.append(f"{'供应商':<25} {'实际CI':>8} {'预测CI':>8} {'误差':>8}")
    lines.append("-" * 55)
    for s in SUPPLIERS:
        pred = predict_supplier_contract_index(
            quality=s.quality.value,
            delivery_window=s.delivery_window.value,
            delivery_reliability_pct=s.delivery_reliability_pct,
            payment_term_weeks=s.payment_term_weeks,
            trade_unit=s.trade_unit.value,
            free_capacity_pct=s.free_capacity_pct,
        )
        err = pred - s.contract_index
        lines.append(f"{s.name:<25} {s.contract_index:>8.4f} {pred:>8.4f} {err:>+8.4f}")

    lines.append("")
    lines.append("--- 客户 ---")
    lines.append(f"{'客户':<25} {'实际CI':>8} {'预测CI':>8} {'误差':>8}")
    lines.append("-" * 55)
    for c in CUSTOMERS:
        pred = predict_customer_contract_index(
            service_level_pct=c.service_level_pct,
            shelf_life_pct=c.shelf_life_pct,
            payment_term_weeks=c.payment_term_weeks,
            trade_unit=c.trade_unit.value,
            promotional_pressure=c.promotional_pressure.value,
            promotion_horizon=c.promotion_horizon.value,
            vmi=c.vmi,
        )
        err = pred - c.contract_index
        lines.append(f"{c.name:<25} {c.contract_index:>8.4f} {pred:>8.4f} {err:>+8.4f}")

    return "\n".join(lines)
