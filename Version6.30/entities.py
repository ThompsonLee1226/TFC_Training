"""
TFC 橙汁游戏 — 静态实体数据定义
从 game.thefreshconnection.eu/v9 Round 4 提取
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from enum import Enum


# ── 枚举 ──────────────────────────────────────────────

class Quality(Enum):
    HIGH = "High"
    MIDDLE = "Middle"
    POOR = "Poor"

class TransportMode(Enum):
    TRUCK = "Truck"
    BOAT = "Boat"

class TradeUnit(Enum):
    PALLET = "Pallet"
    PALLET_LAYER = "Pallet layer"
    FTL = "FTL"
    TANK = "Tank"
    IBC = "IBC"
    DRUM = "Drum"

class DeliveryWindow(Enum):
    FOUR_HOURS = "4 hours"
    ONE_DAY = "1 day"
    TWO_DAYS = "2 days"
    ONE_WEEK = "1 week"

class ServiceLevelType(Enum):
    ORDER_LINES = "Order lines"

class PromotionalPressure(Enum):
    LOW = "Low"
    MIDDLE = "Middle"
    HIGH = "High"

class PromotionHorizon(Enum):
    SHORT = "Short"
    MEDIUM = "Medium"
    LONG = "Long"


# ── 数据类 ────────────────────────────────────────────

@dataclass
class Supplier:
    """供应商"""
    id: str
    name: str
    component_id: str          # 供应的组件
    country: str
    distance_km: int           # 到荷兰的距离
    transport_mode: TransportMode
    lead_time_days: int
    free_capacity_pct: float   # 剩余产能 %
    certification: bool
    market_share_pct: float    # 全球市场份额 %
    # 当前合约参数
    contract_index: float      # Contract Index (乘数)
    quality: Quality
    payment_term_weeks: int
    trade_unit: TradeUnit
    delivery_reliability_pct: float  # 承诺的交货可靠性 %
    delivery_window: DeliveryWindow
    # 协作项目
    supplier_development: bool = False
    vmi: bool = False
    # 基础采购价 (来自组件)
    base_price: float = 0.0

    @property
    def effective_price(self) -> float:
        """实际采购价 = 基础价 × Contract Index"""
        return self.base_price * self.contract_index


@dataclass
class Customer:
    """客户"""
    id: str
    name: str
    contract_index: float
    service_level_type: ServiceLevelType
    service_level_pct: float
    shelf_life_pct: float       # 客户要求的保质期 %
    order_deadline: str         # 订单截止时间
    trade_unit: TradeUnit
    payment_term_weeks: int
    promotional_pressure: PromotionalPressure
    promotion_horizon: PromotionHorizon
    vmi: bool = False
    # 估算的周需求量 (升)
    weekly_demand_liters: float = 0.0


@dataclass
class Product:
    """成品"""
    id: str
    name: str
    shelf_life_weeks: int
    per_outer_box: int
    per_pallet_layer: int
    per_pallet: int
    liters_per_pack: float
    base_price: float  # €


@dataclass
class Component:
    """组件/原材料"""
    id: str
    name: str
    shelf_life_weeks: Optional[int]  # None = 无限
    pallet_layer_content: Optional[int]
    pallet_content: Optional[int]
    base_price: float  # €
    # 容器容量
    drum_liters: int = 250
    ibc_liters: int = 1000
    tank_liters: int = 30000


@dataclass
class MixerSpec:
    """混合器规格（来自游戏 Mixing 页面的 tooltip 数据）"""
    id: str
    name: str
    batch_min_liters: int        # 技术最小批量
    batch_max_liters: int        # 最大批量
    run_time_hours: float        # 每批次运行时间
    clean_time_hours: float      # 口味切换清洗时间
    cost_per_hour: float         # €/混合小时
    fixed_cost_annual: float     # €/年 (折旧+维护)
    investment: float            # € 设备购置投资


@dataclass
class BottlingLineSpec:
    """灌装线规格（来自游戏 Bottling 页面的 tooltip 数据）"""
    id: str
    name: str
    capacity_liters_per_hour: int  # 每小时灌装升数
    num_operators: int             # 操作员数量
    operator_cost_annual: float    # 操作员年薪 €
    flexible_labor_per_hour: float # 灵活工时成本 €/h
    fixed_cost_annual: float       # €/年 (折旧+维护)
    investment: float              # € 设备购置投资
    formula_changeover_hours: float  # 配方换型时间
    size_changeover_hours: float     # 尺寸换型时间
    tolerances: str                  # 包装材料公差: Narrow/Middle/Wide
    startup_productivity_loss_pct: float  # 启动产能损失 %


@dataclass
class FacilityConfig:
    """生产设施运行时参数（非规格，为通用配置）"""
    hours_per_shift: int = 8
    # 生产劳动力基准
    labor_cost_per_fte_annual: float = 40000.0  # €/年/人


@dataclass
class WarehouseConfig:
    """仓库配置"""
    # 原料仓库
    raw_materials_pallet_locations: int = 1000
    raw_materials_perm_employees: int = 5
    raw_materials_intake_days: int = 3
    # 成品仓库
    finished_goods_pallet_locations: int = 750
    finished_goods_perm_employees: int = 4
    # 冷藏成品仓库
    chilled_finished_goods_pallet_locations: int = 200
    # 罐区
    tank_yard_liters: int = 60000
    # 空间成本
    pallet_location_cost_annual: float = 200.0    # €/年/位
    tank_yard_cost_per_day_per_tank: float = 25.0  # €/天/tank (外包)
    # 溢出仓库成本
    overflow_pallet_cost_annual: float = 500.0    # €/年/位 (比正常贵)
    # 劳动力成本
    perm_employee_cost_annual: float = 40000.0    # €/年/人
    temp_employee_cost_annual: float = 60000.0    # €/年/人 (临时工更贵)
    # 检验成本
    inspection_cost_per_supplier_annual: float = 5000.0


# ── 实例化数据 ────────────────────────────────────────

# ── 组件 ──

COMPONENTS = [
    Component(id="pack_1l", name="Pack 1 liter", shelf_life_weeks=None,
              pallet_layer_content=None, pallet_content=17280, base_price=0.030),
    Component(id="pet", name="PET", shelf_life_weeks=None,
              pallet_layer_content=216, pallet_content=1080, base_price=0.030),
    Component(id="orange", name="Orange", shelf_life_weeks=52,
              pallet_layer_content=None, pallet_content=None, base_price=0.400),
    Component(id="mango", name="Mango", shelf_life_weeks=52,
              pallet_layer_content=None, pallet_content=None, base_price=0.900),
    Component(id="vitamin_c", name="Vitamin C", shelf_life_weeks=52,
              pallet_layer_content=None, pallet_content=None, base_price=0.150),
]

COMPONENT_MAP = {c.id: c for c in COMPONENTS}

# ── 供应商 ──

SUPPLIERS = [
    Supplier(id="s_pack", name="Mono Packaging Materials", component_id="pack_1l",
             country="France", distance_km=500, transport_mode=TransportMode.TRUCK,
             lead_time_days=15, free_capacity_pct=18.0, certification=True,
             market_share_pct=25.0, contract_index=0.9468, quality=Quality.HIGH,
             payment_term_weeks=7, trade_unit=TradeUnit.PALLET,
             delivery_reliability_pct=82.0, delivery_window=DeliveryWindow.ONE_DAY,
             base_price=0.030),
    Supplier(id="s_pet", name="Philip Jones Plastics", component_id="pet",
             country="Netherlands", distance_km=100, transport_mode=TransportMode.TRUCK,
             lead_time_days=5, free_capacity_pct=5.0, certification=True,
             market_share_pct=30.0, contract_index=1.0102, quality=Quality.MIDDLE,
             payment_term_weeks=5, trade_unit=TradeUnit.PALLET,
             delivery_reliability_pct=93.0, delivery_window=DeliveryWindow.ONE_DAY,
             base_price=0.030),
    Supplier(id="s_orange", name="Miami Oranges", component_id="orange",
             country="United States", distance_km=7500, transport_mode=TransportMode.BOAT,
             lead_time_days=30, free_capacity_pct=38.0, certification=True,
             market_share_pct=15.0, contract_index=1.0091, quality=Quality.HIGH,
             payment_term_weeks=8, trade_unit=TradeUnit.TANK,
             delivery_reliability_pct=98.0, delivery_window=DeliveryWindow.ONE_DAY,
             base_price=0.400),
    Supplier(id="s_mango", name="NO8DO Mango", component_id="mango",
             country="Spain", distance_km=1800, transport_mode=TransportMode.TRUCK,
             lead_time_days=10, free_capacity_pct=4.0, certification=True,
             market_share_pct=20.0, contract_index=1.0116, quality=Quality.HIGH,
             payment_term_weeks=7, trade_unit=TradeUnit.IBC,
             delivery_reliability_pct=84.0, delivery_window=DeliveryWindow.ONE_DAY,
             base_price=0.900),
    Supplier(id="s_vitc", name="SYI", component_id="vitamin_c",
             country="Netherlands", distance_km=80, transport_mode=TransportMode.TRUCK,
             lead_time_days=4, free_capacity_pct=29.0, certification=True,
             market_share_pct=10.0, contract_index=1.0518, quality=Quality.HIGH,
             payment_term_weeks=6, trade_unit=TradeUnit.IBC,
             delivery_reliability_pct=98.0, delivery_window=DeliveryWindow.FOUR_HOURS,
             base_price=0.150),
]

SUPPLIER_MAP = {s.id: s for s in SUPPLIERS}
SUPPLIER_BY_COMPONENT = {s.component_id: s for s in SUPPLIERS}

# ── 客户 ──

CUSTOMERS = [
    Customer(id="c_fg", name="Food & Groceries", contract_index=1.0085,
             service_level_type=ServiceLevelType.ORDER_LINES,
             service_level_pct=95.0, shelf_life_pct=75.0,
             order_deadline="20:00", trade_unit=TradeUnit.PALLET_LAYER,
             payment_term_weeks=4, promotional_pressure=PromotionalPressure.MIDDLE,
             promotion_horizon=PromotionHorizon.SHORT, vmi=False,
             weekly_demand_liters=50000.0),
    Customer(id="c_land", name="LAND Market", contract_index=0.9695,
             service_level_type=ServiceLevelType.ORDER_LINES,
             service_level_pct=96.0, shelf_life_pct=75.0,
             order_deadline="17:00", trade_unit=TradeUnit.PALLET_LAYER,
             payment_term_weeks=4, promotional_pressure=PromotionalPressure.MIDDLE,
             promotion_horizon=PromotionHorizon.SHORT, vmi=False,
             weekly_demand_liters=25000.0),
    Customer(id="c_dom", name="Dominick's", contract_index=1.0237,
             service_level_type=ServiceLevelType.ORDER_LINES,
             service_level_pct=96.0, shelf_life_pct=75.0,
             order_deadline="12:00", trade_unit=TradeUnit.PALLET,
             payment_term_weeks=4, promotional_pressure=PromotionalPressure.MIDDLE,
             promotion_horizon=PromotionHorizon.SHORT, vmi=False,
             weekly_demand_liters=28000.0),
]

CUSTOMER_MAP = {c.id: c for c in CUSTOMERS}

# ── 成品 ──

PRODUCTS = [
    Product(id="p_orange_1l", name="Fressie Orange 1 liter",
            shelf_life_weeks=20, per_outer_box=10, per_pallet_layer=120,
            per_pallet=600, liters_per_pack=1.00, base_price=0.45),
    Product(id="p_ocp_1l", name="Fressie Orange/C-power 1 liter",
            shelf_life_weeks=20, per_outer_box=10, per_pallet_layer=120,
            per_pallet=600, liters_per_pack=1.00, base_price=0.55),
    Product(id="p_om_1l", name="Fressie Orange/Mango 1 liter",
            shelf_life_weeks=20, per_outer_box=10, per_pallet_layer=120,
            per_pallet=600, liters_per_pack=1.00, base_price=0.48),
    Product(id="p_orange_pet", name="Fressie Orange PET",
            shelf_life_weeks=20, per_outer_box=24, per_pallet_layer=288,
            per_pallet=1440, liters_per_pack=0.30, base_price=0.22),
    Product(id="p_ocp_pet", name="Fressie Orange/C-power PET",
            shelf_life_weeks=20, per_outer_box=24, per_pallet_layer=288,
            per_pallet=1440, liters_per_pack=0.30, base_price=0.32),
    Product(id="p_om_pet", name="Fressie Orange/Mango PET",
            shelf_life_weeks=20, per_outer_box=24, per_pallet_layer=288,
            per_pallet=1440, liters_per_pack=0.30, base_price=0.25),
]

PRODUCT_MAP = {p.id: p for p in PRODUCTS}

# ── BOM 物料清单 (成品 → {组件: 用量升数}) ──

BOM: Dict[str, Dict[str, float]] = {
    "p_orange_1l":  {"pack_1l": 1.0, "orange": 0.200},
    "p_ocp_1l":    {"pack_1l": 1.0, "orange": 0.190, "vitamin_c": 0.010},
    "p_om_1l":     {"pack_1l": 1.0, "orange": 0.150, "mango": 0.050},
    "p_orange_pet": {"pet": 1.0, "orange": 0.060},
    "p_ocp_pet":   {"pet": 1.0, "orange": 0.057, "vitamin_c": 0.003},
    "p_om_pet":    {"pet": 1.0, "orange": 0.045, "mango": 0.015},
}

# ── 混合器规格（从游戏 Mixing 页面 tooltip 提取）──

MIXER_SPECS = {
    "Fruitmix MQ": MixerSpec(
        id="mixer_fruitmix", name="Fruitmix MQ",
        batch_min_liters=8000, batch_max_liters=12000,
        run_time_hours=2.0, clean_time_hours=2.0,
        cost_per_hour=135.0, fixed_cost_annual=62500.0,
        investment=312500.0,
    ),
    "MegaChurn 20": MixerSpec(
        id="mixer_megachurn", name="MegaChurn 20",
        batch_min_liters=15000, batch_max_liters=20000,
        run_time_hours=2.0, clean_time_hours=3.0,
        cost_per_hour=160.0, fixed_cost_annual=75000.0,
        investment=375000.0,
    ),
    "FMM 4000": MixerSpec(
        id="mixer_fmm4000", name="FMM 4000",
        batch_min_liters=3000, batch_max_liters=6000,
        run_time_hours=2.0, clean_time_hours=1.0,
        cost_per_hour=100.0, fixed_cost_annual=50000.0,
        investment=250000.0,
    ),
}

# ── 灌装线规格（从游戏 Bottling 页面 tooltip 提取）──

BOTTLING_LINE_SPECS = {
    "Swiss Fill 2": BottlingLineSpec(
        id="line_swissfill2", name="Swiss Fill 2",
        capacity_liters_per_hour=3100, num_operators=5,
        operator_cost_annual=40000.0, flexible_labor_per_hour=42.0,
        fixed_cost_annual=98000.0, investment=490000.0,
        formula_changeover_hours=2.0, size_changeover_hours=4.0,
        tolerances="Middle", startup_productivity_loss_pct=10.0,
    ),
    "TopSpeed 1": BottlingLineSpec(
        id="line_topspeed1", name="TopSpeed 1",
        capacity_liters_per_hour=3250, num_operators=4,
        operator_cost_annual=40000.0, flexible_labor_per_hour=42.0,
        fixed_cost_annual=114000.0, investment=570000.0,
        formula_changeover_hours=4.0, size_changeover_hours=6.0,
        tolerances="Narrow", startup_productivity_loss_pct=15.0,
    ),
    "MultiFlex 1": BottlingLineSpec(
        id="line_multiflex1", name="MultiFlex 1",
        capacity_liters_per_hour=2950, num_operators=6,
        operator_cost_annual=40000.0, flexible_labor_per_hour=42.0,
        fixed_cost_annual=85000.0, investment=425000.0,
        formula_changeover_hours=1.0, size_changeover_hours=2.0,
        tolerances="Wide", startup_productivity_loss_pct=8.0,
    ),
    "Swiss Fill 1": BottlingLineSpec(
        id="line_swissfill1", name="Swiss Fill 1",
        capacity_liters_per_hour=3100, num_operators=5,
        operator_cost_annual=40000.0, flexible_labor_per_hour=42.0,
        fixed_cost_annual=98000.0, investment=490000.0,
        formula_changeover_hours=2.0, size_changeover_hours=4.0,
        tolerances="Middle", startup_productivity_loss_pct=10.0,
    ),
}

# ── 设施通用配置 ──

FACILITY = FacilityConfig()
WAREHOUSE = WarehouseConfig()
