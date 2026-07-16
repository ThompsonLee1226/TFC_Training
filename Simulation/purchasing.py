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
        "payment_term_weeks":   4,
        "trade_unit":           "Pallet",
        "delivery_reliability_pct": 96.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # Platin PET — PET (法国, 卡车, 500km, 15天)
    "s_pet": {
        "quality":              "High",
        "payment_term_weeks":   4,
        "trade_unit":           "Pallet",
        "delivery_reliability_pct": 96.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # Miami Oranges — Orange (美国, 海运, 7500km, 30天)
    "s_orange": {
        "quality":              "High",
        "payment_term_weeks":   4,
        "trade_unit":           "Tank",
        "delivery_reliability_pct": 98.0,
        "delivery_window":      "1 day",
        "supplier_development": False,
        "vmi":                  False,
    },
    # NO8DO Mango — Mango (西班牙, 卡车, 1800km, 10天)
    "s_mango": {
        "quality":              "High",
        "payment_term_weeks":   4,
        "trade_unit":           "IBC",
        "delivery_reliability_pct": 96.0,
        "delivery_window":      "2 days",
        "supplier_development": False,
        "vmi":                  False,
    },
    # AlL Vitamins — Vitamin C (法国, 卡车, 500km, 20天)
    "s_vitc": {
        "quality":              "High",
        "payment_term_weeks":   4,
        "trade_unit":           "Drum",
        "delivery_reliability_pct": 96.0,
        "delivery_window":      "1 day",
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
# 从 Decision.csv Round 3 实测获取（与当前 SUPPLIER_DECISIONS 对齐）
# 参考 CI = 当前参数配置下游戏实际显示的 Contract Index
SUPPLIER_REFERENCE_CI = {
    "s_pack":   0.993,    # Mono Packaging Materials, 基线: High/PT=4/Rel=96%/1day/Pallet
    "s_pet":    0.996,    # Platin PET,               基线: High/PT=4/Rel=96%/1day/Pallet
    "s_orange": 1.004,    # Miami Oranges,            基线: High/PT=4/Rel=98%/1day/Tank
    "s_mango":  1.0564,   # NO8DO Mango,              基线: High/PT=4/Rel=96%/2days/IBC
    "s_vitc":   1.031,    # AlL Vitamins,             基线: High/PT=4/Rel=96%/1day/Drum
}

# 各供应商参考参数配置（用于计算效应增量）
SUPPLIER_REFERENCE_PARAMS = {
    "s_pack":   {"quality": "High", "payment_term_weeks": 4,
                 "delivery_reliability_pct": 96.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Pallet"},
    "s_pet":    {"quality": "High", "payment_term_weeks": 4,
                 "delivery_reliability_pct": 96.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Pallet"},
    "s_orange": {"quality": "High", "payment_term_weeks": 4,
                 "delivery_reliability_pct": 98.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Tank"},
    "s_mango":  {"quality": "High", "payment_term_weeks": 4,
                 "delivery_reliability_pct": 96.0, "delivery_window": "2 days",
                 "vmi": False, "trade_unit": "IBC"},
    "s_vitc":   {"quality": "High", "payment_term_weeks": 4,
                 "delivery_reliability_pct": 96.0, "delivery_window": "1 day",
                 "vmi": False, "trade_unit": "Drum"},
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

# ── 运输费率（来自 Decision.csv Row 47-49，游戏实际使用的固定费率）──
# 格式: {supplier_id: {cost_per_shipment, cost_per_trade_unit, cost_per_full_load, full_load_units}}
_SUPPLIER_TRANSPORT = {
    "s_pack": {
        "cost_per_shipment":    100.0,   # €/订单
        "cost_per_trade_unit":   20.0,   # €/托盘
        "cost_per_full_load":   500.0,   # €/FTL (30托盘)
        "full_load_units":       30,     # 每FTL=30托盘
    },
    "s_pet": {
        "cost_per_shipment":    125.0,
        "cost_per_trade_unit":   25.0,   # €/托盘
        "cost_per_full_load":   625.0,   # €/FTL
        "full_load_units":       30,
    },
    "s_orange": {
        "cost_per_shipment":    125.0,
        "cost_per_trade_unit":   40.0,   # €/罐车分量（基本单位）
        "cost_per_full_load":  1000.0,   # €/罐车 (30,000L)
        "full_load_units":   30000,     # 每罐车=30,000L
    },
    "s_mango": {
        "cost_per_shipment":    100.0,
        "cost_per_trade_unit":   30.0,   # €/IBC
        "cost_per_full_load":   750.0,   # €/FTL
        "full_load_units":       30,     # 每FTL=30 IBC
    },
    "s_vitc": {
        "cost_per_shipment":    100.0,
        "cost_per_trade_unit":   24.0,   # €/Drum
        "cost_per_full_load":   600.0,   # €/FTL
        "full_load_units":       30,     # 每FTL=30 Drums (粗略)
    },
}


def calculate_inbound_transport(supplier_id: str, total_units: float,
                                num_orders: int = None) -> float:
    """计算单供应商 26 周的入库运输成本。

    使用游戏实际的固定费率（来自 Decision.csv），而非距离模型。

    游戏费率结构 (per Decision.csv Row 47-49):
      - cost_per_shipment: 每次下单固定费用
      - cost_per_trade_unit: 每托盘/Drum/IBC 的运输费
      - cost_per_full_load: 每 FTL/罐车 的整车运输费

    计费规则: 按整车费率计算（经济批量），不够一车按贸易单位费率。

    Args:
        supplier_id: 供应商 ID
        total_units: 总需求量（包装组件为 pieces，液体组件为 liters）
        num_orders: 下单次数（默认按 lot_size 估算）

    Returns:
        26 周运输总成本 (€)
    """
    rates = _SUPPLIER_TRANSPORT.get(supplier_id)
    if not rates:
        return 0.0

    s = SUPPLIER_MAP.get(supplier_id)
    if not s:
        return 0.0

    d = SUPPLIER_DECISIONS.get(supplier_id, {})
    trade_unit = d.get("trade_unit", "Pallet")
    comp = COMPONENT_MAP.get(s.component_id)

    # ── 1) 计算贸易单位数量 ──
    if trade_unit == "Tank":
        # 液体罐车：每车 30,000L，total_units 已是升数
        num_trade_units = total_units / 30000.0
        full_load_size = 30000.0
        use_full_load = True  # 罐车总是整车
    elif trade_unit == "IBC":
        # IBC: 每个 1,000L，total_units 已是升数
        num_trade_units = total_units / 1000.0
        full_load_size = rates.get("full_load_units", 30)
        use_full_load = True
    elif trade_unit == "Drum":
        # Drum: 每个 250L，total_units 已是升数
        num_trade_units = total_units / 250.0
        full_load_size = rates.get("full_load_units", 30)
        use_full_load = True
    else:  # Pallet
        # 包装材料：total_units 是 pieces，需按 pallet_content 换算托盘数
        pallet_content = comp.pallet_content if comp and comp.pallet_content else 1000
        num_trade_units = total_units / pallet_content
        full_load_size = rates.get("full_load_units", 30)
        use_full_load = True

    if num_trade_units <= 0:
        return 0.0

    # ── 2) 整车计费（经济批量）──
    if use_full_load and full_load_size > 0:
        num_full_loads = max(1, int(num_trade_units / full_load_size + 0.999))
        transport_cost = num_full_loads * rates["cost_per_full_load"]
    else:
        transport_cost = num_trade_units * rates["cost_per_trade_unit"]

    # ── 3) 每单固定费用 ──
    if num_orders is None:
        # 按 lot_size 估算下单次数: 26周 / lot_size_weeks
        from supplychain import SUPPLY_CHAIN_CONFIG
        lot_weeks = SUPPLY_CHAIN_CONFIG.get("lot_size_weeks", {}).get(s.component_id, 3)
        num_orders = max(1, round(26.0 / lot_weeks))
    shipment_cost = rates["cost_per_shipment"] * num_orders

    return transport_cost + shipment_cost


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
