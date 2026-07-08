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
# 双源采购配置 (per purchasing_info.txt:75-78)
# 为每个组件启用双源采购需 €40,000/年/额外供应商
# ═══════════════════════════════════════════════════════════════
DUAL_SOURCING: Dict[str, bool] = {
    "pack_1l":   False,
    "pet":       False,
    "orange":    False,
    "mango":     False,
    "vitamin_c": False,
}

DUAL_SOURCING_COST_ANNUAL = 40000.0  # €/年/额外供应商


def calculate_dual_sourcing_cost() -> float:
    """双源采购成本（26周）"""
    count = sum(1 for v in DUAL_SOURCING.values() if v)
    return count * DUAL_SOURCING_COST_ANNUAL * 0.5  # half year


# ═══════════════════════════════════════════════════════════════
# Supplier Contract Index 模型
# ================================================================
# 公式来源：对 TFC V9 游戏 API 进行系统性参数扫描，实测破解
# 测试日期：2026-07-02，团队：Tsinghua University 2026 Pool 2 - Team 1
# ================================================================
# 核心公式：
#   CI = REF_CI + ΔQ(Quality) + ΔPT(PaymentTerm) + ΔR(Reliability)
#               + ΔD(DeliveryWindow) + ΔV(VMI) + ΔT(TradeUnit)
# 所有效应为加法性（已通过交叉测试验证无交互作用）
# ================================================================


# ── 各参数效应函数 ──

def _quality_effect(q: str) -> float:
    """质量效应：线性递减 -0.0020/级（实测值）"""
    return {"High": 0.0, "Middle": -0.0020, "Poor": -0.0040}[q]


def _payment_term_effect(pt_weeks: int) -> float:
    """付款周期效应：非线性加速增长（实测值，范围 1-8 周）"""
    table = {
        1: -0.0072, 2: -0.0066, 3: -0.0058, 4: -0.0048,
        5: -0.0036, 6: -0.0020, 7:  0.0000, 8: +0.0020,
    }
    if pt_weeks in table:
        return table[pt_weeks]
    # 外推（近似二次公式）
    return 0.00013333 * pt_weeks**2 + 0.00010952 * pt_weeks - 0.00739286 + 0.9468 - (
        0.00013333 * 49 + 0.00010952 * 7 - 0.00739286 + 0.9468
    )


def _reliability_effect(rel_pct: float) -> float:
    """交货可靠性效应：阶跃 + 递减边际（实测值）"""
    rel = int(rel_pct)
    if rel <= 85:
        return 0.0
    table = {
        86: 0.0050, 87: 0.0140, 88: 0.0220, 89: 0.0290,
        90: 0.0350, 91: 0.0400, 92: 0.0440, 93: 0.0470,
        94: 0.0490, 95: 0.0500, 96: 0.0510, 97: 0.0530,
        98: 0.0560, 99: 0.0600,
    }
    if rel in table:
        return table[rel]
    if rel > 99:
        return table[99]
    return 0.0


def _delivery_window_effect(dw: str) -> float:
    """交货窗口效应：非线性（实测值）"""
    return {"4 hours": +0.0020, "1 day": 0.0,
            "2 days": -0.0016, "1 week": -0.0040}[dw]


def _vmi_effect(vmi: bool) -> float:
    """VMI 效应：最大负面因素（实测值）"""
    return -0.0112 if vmi else 0.0


def _trade_unit_effect(tu: str) -> float:
    """贸易单位效应：仅对 Pallet 类产品有效（实测值）"""
    return {"Pallet": 0.0, "FTL": -0.0030}.get(tu, 0.0)


# ── 各供应商参考 CI 值 ──
# 从 TFC V9 游戏当前回合 (Round 4) 实测获取
# 参考 CI = 当前参数配置下游戏实际显示的 Contract Index
SUPPLIER_REFERENCE_CI = {
    "s_pack":   0.9468,   # Pak,      基线: High/PT=7/Rel=82%/1day/Pallet
    "s_pet":    1.0102,   # PET,      基线: Middle/PT=5/Rel=93%/1day/Pallet
    "s_orange": 1.0091,   # Orange,   基线: High/PT=8/Rel=98%/1day/Tank
    "s_mango":  1.0116,   # Mango,    基线: High/PT=7/Rel=84%/1day/IBC
    "s_vitc":   1.0518,   # VitaminC, 基线: High/PT=6/Rel=98%/4hours/IBC
}

# 各供应商参考参数配置（用于计算效应增量）
SUPPLIER_REFERENCE_PARAMS = {
    "s_pack":   {"quality": "High", "payment_term_weeks": 7,
                 "delivery_reliability_pct": 82.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Pallet"},
    "s_pet":    {"quality": "Middle", "payment_term_weeks": 5,
                 "delivery_reliability_pct": 93.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Pallet"},
    "s_orange": {"quality": "High", "payment_term_weeks": 8,
                 "delivery_reliability_pct": 98.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Tank"},
    "s_mango":  {"quality": "High", "payment_term_weeks": 7,
                 "delivery_reliability_pct": 84.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "IBC"},
    "s_vitc":   {"quality": "High", "payment_term_weeks": 6,
                 "delivery_reliability_pct": 98.0, "delivery_window": "4 hours",
                 "vmi": False, "trade_unit": "IBC"},
}


def predict_supplier_ci(supplier_id: str) -> float:
    """根据 SUPPLIER_DECISIONS 中的参数预测供应商 Contract Index

    公式: CI = REF_CI + Σ ΔEffect
    其中 ΔEffect = Effect(new_param) - Effect(ref_param)
    参考 CI 为游戏当前回合实测值
    """
    d = SUPPLIER_DECISIONS.get(supplier_id)
    if not d:
        return 1.0

    ref = SUPPLIER_REFERENCE_PARAMS.get(supplier_id)
    ref_ci = SUPPLIER_REFERENCE_CI.get(supplier_id, 0.9468)

    if not ref:
        return ref_ci

    # 计算各参数效应增量
    ci = ref_ci
    ci += _quality_effect(d["quality"]) - _quality_effect(ref["quality"])
    ci += _payment_term_effect(d["payment_term_weeks"]) - _payment_term_effect(ref["payment_term_weeks"])
    ci += _reliability_effect(d["delivery_reliability_pct"]) - _reliability_effect(ref["delivery_reliability_pct"])
    ci += _delivery_window_effect(d["delivery_window"]) - _delivery_window_effect(ref["delivery_window"])
    ci += _vmi_effect(d.get("vmi", False)) - _vmi_effect(ref.get("vmi", False))

    # 贸易单位：仅当新产品选项不同于参考时才应用
    new_tu = d.get("trade_unit", "")
    ref_tu = ref.get("trade_unit", "")
    if new_tu != ref_tu:
        ci += _trade_unit_effect(new_tu) - _trade_unit_effect(ref_tu)

    # Supplier Development 实测无影响，省略也不添加
    # 注意：游戏实际 CI 不含产能调整

    return round(max(0.85, min(1.20, ci)), 6)


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
