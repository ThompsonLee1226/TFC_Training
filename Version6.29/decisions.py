"""
TFC 决策数据结构 — 四角色 Round 3/4 实际决策
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from entities import Quality, DeliveryWindow, TradeUnit, PromotionalPressure, PromotionHorizon


@dataclass
class PurchasingDecision:
    """单供应商的采购决策"""
    supplier_id: str
    quality: Quality = Quality.HIGH
    payment_term_weeks: int = 7
    trade_unit: TradeUnit = TradeUnit.PALLET
    delivery_reliability_pct: float = 90.0
    delivery_window: DeliveryWindow = DeliveryWindow.ONE_DAY
    supplier_development: bool = False
    vmi: bool = False
    terminate: bool = False


@dataclass
class SalesDecision:
    """单客户的销售决策"""
    customer_id: str
    service_level_pct: float = 95.0
    shelf_life_pct: float = 75.0
    order_deadline: str = "18:00"
    trade_unit: TradeUnit = TradeUnit.PALLET_LAYER
    payment_term_weeks: int = 4
    promotional_pressure: PromotionalPressure = PromotionalPressure.MIDDLE
    promotion_horizon: PromotionHorizon = PromotionHorizon.SHORT
    vmi: bool = False


@dataclass
class OperationsDecision:
    """运营决策"""
    # 原料检验 per supplier
    raw_materials_inspection: Dict[str, bool] = field(default_factory=dict)
    # 原料仓库
    raw_materials_pallet_locations: int = 1000
    raw_materials_perm_employees: int = 5
    intake_time_days: int = 3
    # 生产
    production_shifts_per_week: int = 5
    # 培训项目
    smed_training: bool = False
    solve_breakdowns_training: bool = False


@dataclass
class SupplyChainDecision:
    """供应链决策"""
    # 安全库存 (weeks) per component
    safety_stock_weeks: Dict[str, float] = field(default_factory=dict)
    # 批次大小 (weeks) per component
    lot_size_weeks: Dict[str, float] = field(default_factory=dict)
    # 生产冻结期 (weeks)
    frozen_period_weeks: int = 2
    # 生产间隔 (weeks)
    production_interval_weeks: int = 1


@dataclass
class RoundDecisions:
    """一轮完整决策"""
    round_number: int
    purchasing: List[PurchasingDecision]
    sales: List[SalesDecision]
    operations: OperationsDecision
    supply_chain: SupplyChainDecision


# ── Round 3 实际决策（从游戏页面提取） ──────────────

ROUND3_DECISIONS = RoundDecisions(
    round_number=3,

    purchasing=[
        PurchasingDecision(supplier_id="s_pack", quality=Quality.HIGH,
                          payment_term_weeks=7, trade_unit=TradeUnit.PALLET,
                          delivery_reliability_pct=82.0,
                          delivery_window=DeliveryWindow.ONE_DAY),
        PurchasingDecision(supplier_id="s_pet", quality=Quality.MIDDLE,
                          payment_term_weeks=5, trade_unit=TradeUnit.PALLET,
                          delivery_reliability_pct=93.0,
                          delivery_window=DeliveryWindow.ONE_DAY),
        PurchasingDecision(supplier_id="s_orange", quality=Quality.HIGH,
                          payment_term_weeks=8, trade_unit=TradeUnit.TANK,
                          delivery_reliability_pct=98.0,
                          delivery_window=DeliveryWindow.ONE_DAY),
        PurchasingDecision(supplier_id="s_mango", quality=Quality.HIGH,
                          payment_term_weeks=7, trade_unit=TradeUnit.IBC,
                          delivery_reliability_pct=84.0,
                          delivery_window=DeliveryWindow.ONE_DAY),
        PurchasingDecision(supplier_id="s_vitc", quality=Quality.HIGH,
                          payment_term_weeks=6, trade_unit=TradeUnit.IBC,
                          delivery_reliability_pct=98.0,
                          delivery_window=DeliveryWindow.FOUR_HOURS),
    ],

    sales=[
        SalesDecision(customer_id="c_fg", service_level_pct=95.0,
                     shelf_life_pct=75.0, order_deadline="20:00",
                     trade_unit=TradeUnit.PALLET_LAYER, payment_term_weeks=4,
                     promotional_pressure=PromotionalPressure.MIDDLE,
                     promotion_horizon=PromotionHorizon.SHORT),
        SalesDecision(customer_id="c_land", service_level_pct=96.0,
                     shelf_life_pct=75.0, order_deadline="17:00",
                     trade_unit=TradeUnit.PALLET_LAYER, payment_term_weeks=4,
                     promotional_pressure=PromotionalPressure.MIDDLE,
                     promotion_horizon=PromotionHorizon.SHORT),
        SalesDecision(customer_id="c_dom", service_level_pct=96.0,
                     shelf_life_pct=75.0, order_deadline="12:00",
                     trade_unit=TradeUnit.PALLET, payment_term_weeks=4,
                     promotional_pressure=PromotionalPressure.MIDDLE,
                     promotion_horizon=PromotionHorizon.SHORT),
    ],

    operations=OperationsDecision(
        raw_materials_inspection={
            "s_mango": True, "s_pack": False, "s_orange": True,
            "s_pet": True, "s_vitc": True,
        },
        raw_materials_pallet_locations=1000,
        raw_materials_perm_employees=5,
        intake_time_days=3,
        production_shifts_per_week=5,
        smed_training=False,
        solve_breakdowns_training=False,
    ),

    supply_chain=SupplyChainDecision(
        safety_stock_weeks={
            "pack_1l": 2.5, "pet": 2.7, "orange": 1.0,
            "mango": 2.3, "vitamin_c": 3.5,
        },
        lot_size_weeks={
            "pack_1l": 1.8, "pet": 2.0, "orange": 1.5,
            "mango": 2.2, "vitamin_c": 2.2,
        },
        frozen_period_weeks=2,
        production_interval_weeks=1,
    ),
)
