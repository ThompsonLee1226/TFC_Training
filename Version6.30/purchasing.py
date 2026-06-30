"""
Purchasing 模块 — 对应游戏 Purchasing 页面
==========================================
包含：供应商决策参数、供应商 Contract Index 模型、采购成本计算。

使用方法：修改下方 SUPPLIER_DECISIONS 字典中的参数，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, List
from entities import (
    SUPPLIERS, SUPPLIER_MAP, COMPONENT_MAP, BOM,
    TradeUnit, TransportMode,
)
from config import WEEKS_PER_ROUND


# ═══════════════════════════════════════════════════════════════
# 供应商决策参数（对应 Purchasing 页面每个供应商的 SLA 设置）
# 修改这里的值来测试不同采购策略
# ═══════════════════════════════════════════════════════════════

SUPPLIER_DECISIONS: Dict[str, dict] = {
    # Mono Packaging Materials — Pack 1 liter (法国, 卡车, 500km, 15天)
    "s_pack": {
        "quality":              "High",
        "payment_term_weeks":   7,
        "trade_unit":           "Pallet",
        "delivery_reliability_pct": 82.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # Philip Jones Plastics — PET (荷兰, 卡车, 100km, 5天)
    "s_pet": {
        "quality":              "Middle",
        "payment_term_weeks":   5,
        "trade_unit":           "Pallet",
        "delivery_reliability_pct": 93.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # Miami Oranges — Orange (美国, 海运, 7500km, 30天)
    "s_orange": {
        "quality":              "High",
        "payment_term_weeks":   8,
        "trade_unit":           "Tank",
        "delivery_reliability_pct": 98.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # NO8DO Mango — Mango (西班牙, 卡车, 1800km, 10天)
    "s_mango": {
        "quality":              "High",
        "payment_term_weeks":   7,
        "trade_unit":           "IBC",
        "delivery_reliability_pct": 84.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # SYI — Vitamin C (荷兰, 卡车, 80km, 4天)
    "s_vitc": {
        "quality":              "High",
        "payment_term_weeks":   6,
        "trade_unit":           "IBC",
        "delivery_reliability_pct": 98.0,
        "delivery_window":      "4 hours",
        "supplier_development": False,
        "vmi":                  False,
    },
}


# ═══════════════════════════════════════════════════════════════
# Supplier Contract Index 模型
# ═══════════════════════════════════════════════════════════════

# 参数编码：文字选项 → 数值 [0, 1]
def _encode_quality(q: str) -> float:
    return {"High": 1.0, "Middle": 0.5, "Poor": 0.0}[q]

def _encode_delivery_window(dw: str) -> float:
    return {"4 hours": 1.0, "1 day": 0.75, "2 days": 0.5, "1 week": 0.25}[dw]

def _encode_trade_unit(tu: str) -> float:
    return {"Tank": 1.0, "IBC": 0.6, "FTL": 0.4, "Pallet": 0.2}[tu]

# 权重（由 5 个供应商已知 CI 值标定）
SUPPLIER_CI_WEIGHTS = {
    "quality":              0.04,
    "delivery_window":      0.06,
    "delivery_reliability": 0.0008,
    "payment_term":         0.004,
    "trade_unit":          -0.03,
}
SUPPLIER_CI_BASELINE = {"delivery_reliability": 90.0, "payment_term": 6}


def predict_supplier_ci(supplier_id: str) -> float:
    """根据 SUPPLIER_DECISIONS 中的参数预测供应商 Contract Index"""
    d = SUPPLIER_DECISIONS.get(supplier_id)
    if not d:
        return 1.0

    w = SUPPLIER_CI_WEIGHTS
    index = 0.995

    q = _encode_quality(d["quality"])
    index += w["quality"] * (q - 0.5) * 2

    dw = _encode_delivery_window(d["delivery_window"])
    index += w["delivery_window"] * (dw - 0.75) * 4

    index += w["delivery_reliability"] * (d["delivery_reliability_pct"] - SUPPLIER_CI_BASELINE["delivery_reliability"])
    index += w["payment_term"] * (d["payment_term_weeks"] - SUPPLIER_CI_BASELINE["payment_term"])

    tu = _encode_trade_unit(d["trade_unit"])
    index += w["trade_unit"] * (tu - 0.4) * 2

    # 产能紧张度（来自实体数据）
    s = SUPPLIER_MAP.get(supplier_id)
    if s:
        index += -0.0005 * (s.free_capacity_pct - 20.0)

    if d.get("vmi"):
        index -= 0.005
    if d.get("supplier_development"):
        index -= 0.010

    return round(max(0.85, min(1.20, index)), 6)


def get_effective_purchase_price(supplier_id: str) -> float:
    """实际采购单价 = 基础价 × Contract Index"""
    s = SUPPLIER_MAP.get(supplier_id)
    if not s:
        return 0.0
    return s.base_price * predict_supplier_ci(supplier_id)


def get_supplier_lead_time(supplier_id: str) -> int:
    """供应商交货提前期（天）"""
    s = SUPPLIER_MAP.get(supplier_id)
    return s.lead_time_days if s else 7


# ═══════════════════════════════════════════════════════════════
# 采购成本计算
# ═══════════════════════════════════════════════════════════════

# 运输距离 (km)
_SUPPLIER_DISTANCE = {
    "s_pack": 500, "s_pet": 100, "s_orange": 7500,
    "s_mango": 1800, "s_vitc": 80,
}

# 运输参数
_TRANSPORT_COST_PER_KM_PALLET = 0.15
_BOAT_FACTOR = 0.3
_FTL_DISCOUNT = 0.7
_EXPRESS_FACTOR = 1.5


def calculate_inbound_transport(supplier_id: str, total_liters: float) -> float:
    """计算单供应商 26 周的入库运输成本"""
    s = SUPPLIER_MAP.get(supplier_id)
    if not s:
        return 0.0

    d = SUPPLIER_DECISIONS.get(supplier_id, {})
    trade_unit = d.get("trade_unit", "Pallet")
    comp = COMPONENT_MAP.get(s.component_id)
    distance = _SUPPLIER_DISTANCE.get(supplier_id, 500)

    # 运输模式费率
    is_boat = s.transport_mode == TransportMode.BOAT
    is_express = distance > 600

    # ── 按贸易单位分别计算 ──
    if trade_unit == "Tank":
        # 罐车：每车 30,000L，按整车运费算
        liters_per_truck = 30000
        num_trucks = max(1, total_liters / liters_per_truck)
        rate_per_km = 1.50  # EUR/km for a tanker truck
        if is_boat:
            rate_per_km *= _BOAT_FACTOR
        cost = distance * rate_per_km * num_trucks

    elif trade_unit == "IBC":
        # IBC：每个 1,000L，按托盘运输（1 IBC ≈ 1 pallet）
        num_ibcs = max(1, total_liters / 1000)
        rate_per_km_pallet = _TRANSPORT_COST_PER_KM_PALLET
        cost = distance * rate_per_km_pallet * num_ibcs

    elif trade_unit == "FTL":
        # 整车：30 pallets/truck
        pallet_content = comp.pallet_content or 600
        liters_per_truck = 30 * pallet_content
        num_trucks = max(1, total_liters / liters_per_truck)
        rate_per_km_pallet = _TRANSPORT_COST_PER_KM_PALLET * _FTL_DISCOUNT
        cost = distance * rate_per_km_pallet * 30 * num_trucks

    else:  # Pallet
        pallet_content = comp.pallet_content or 600
        num_pallets = max(1, total_liters / pallet_content)
        rate_per_km_pallet = _TRANSPORT_COST_PER_KM_PALLET
        cost = distance * rate_per_km_pallet * num_pallets

    if is_express and trade_unit != "Tank":
        cost *= _EXPRESS_FACTOR

    return cost


def calculate_purchase_costs(component_needs: Dict[str, float]) -> Dict:
    """
    根据组件需求量计算完整采购成本。

    参数:
        component_needs: {component_id: total_liters_over_26_weeks}

    返回:
        {
            "total_purchase": float,       # 总采购金额
            "total_transport": float,      # 总入库运输费
            "by_supplier": {supplier_id: {"purchase": ..., "transport": ...}},
            "ci_deltas": {supplier_id: delta},
        }
    """
    total_purchase = 0.0
    total_transport = 0.0
    by_supplier = {}
    ci_deltas = {}

    for s in SUPPLIERS:
        liters = component_needs.get(s.component_id, 0.0)
        if liters <= 0:
            ci_deltas[s.id] = 1.0
            continue

        price = get_effective_purchase_price(s.id)
        purchase = liters * price
        transport = calculate_inbound_transport(s.id, liters)

        total_purchase += purchase
        total_transport += transport
        by_supplier[s.id] = {"purchase": purchase, "transport": transport}

        new_ci = predict_supplier_ci(s.id)
        ci_deltas[s.id] = new_ci / s.contract_index if s.contract_index else 1.0

    return {
        "total_purchase": total_purchase,
        "total_transport": total_transport,
        "by_supplier": by_supplier,
        "ci_deltas": ci_deltas,
    }


# ═══════════════════════════════════════════════════════════════
# 校准报告
# ═══════════════════════════════════════════════════════════════

def calibration_report() -> str:
    """供应商 CI 预测值 vs 实际值对比"""
    lines = ["Supplier Contract Index 校准", "-" * 50]
    lines.append(f"{'Supplier':<28} {'Actual':>7} {'Pred':>7} {'Err':>7}")
    lines.append("-" * 50)
    for s in SUPPLIERS:
        pred = predict_supplier_ci(s.id)
        err = pred - s.contract_index
        lines.append(f"{s.name:<28} {s.contract_index:>7.4f} {pred:>7.4f} {err:>+7.4f}")
    return "\n".join(lines)
