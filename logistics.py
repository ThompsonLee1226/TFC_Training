"""
TFC 物流 — 运输成本 + 仓储成本
"""
from typing import Dict, Tuple
from entities import (
    SUPPLIER_MAP, CUSTOMER_MAP, WAREHOUSE,
    TransportMode, TradeUnit,
)


# 运输距离表 (km)
DISTANCES: Dict[str, float] = {
    "s_pack": 500.0,    # France → Netherlands
    "s_pet": 100.0,     # Netherlands local
    "s_orange": 7500.0, # US → Netherlands (boat)
    "s_mango": 1800.0,  # Spain → Netherlands
    "s_vitc": 80.0,     # Netherlands local
}

# 客户距离 (to DCs, approximate)
CUSTOMER_DISTANCES: Dict[str, float] = {
    "c_fg": 200.0,
    "c_land": 350.0,
    "c_dom": 150.0,
}

# 运输成本基准 (€/km/pallet for truck)
TRANSPORT_COST_PER_KM_PER_PALLET = 0.15
# Boat surcharge (cheaper per km but longer transit)
BOAT_COST_FACTOR = 0.3  # Boat is 30% of truck cost per km per pallet
# FTL discount
FTL_DISCOUNT = 0.7      # Full truck load = 70% of standard rate
# Express factor when distance > 600km/day
EXPRESS_FACTOR = 1.5    # 50% surcharge for express shipping


def calculate_inbound_transport_cost(
    supplier_id: str, component_id: str,
    total_liters: float, trade_unit: TradeUnit
) -> float:
    """计算入库运输成本（一轮26周）"""
    s = SUPPLIER_MAP.get(supplier_id)
    if not s:
        return 0.0

    distance = DISTANCES.get(supplier_id, 500.0)

    # 估算托盘数
    from entities import COMPONENT_MAP
    comp = COMPONENT_MAP.get(component_id)
    if not comp:
        return 0.0

    # 根据 trade unit 估算
    if trade_unit in (TradeUnit.TANK,):
        liters_per_shipment = 30000  # tank truck
    elif trade_unit in (TradeUnit.IBC,):
        liters_per_shipment = 1000
    elif trade_unit in (TradeUnit.FTL,):
        liters_per_shipment = 30 * 600  # 30 pallets × contents
        if comp.pallet_content:
            liters_per_shipment = 30 * comp.pallet_content
    else:  # Pallet
        liters_per_shipment = comp.pallet_content or 1000

    num_shipments = max(1, total_liters / liters_per_shipment)

    # Base cost per shipment
    pallets_per_shipment = liters_per_shipment / (comp.pallet_content or 1000) * 30

    if s.transport_mode == TransportMode.BOAT:
        cost_per_km_per_pallet = TRANSPORT_COST_PER_KM_PER_PALLET * BOAT_COST_FACTOR
    else:
        cost_per_km_per_pallet = TRANSPORT_COST_PER_KM_PER_PALLET

    # FTL discount
    if trade_unit in (TradeUnit.FTL, TradeUnit.TANK):
        cost_per_km_per_pallet *= FTL_DISCOUNT

    base_cost = distance * pallets_per_shipment * cost_per_km_per_pallet * num_shipments

    # Express factor if distance > 600km/day standard
    if distance > 600:
        base_cost *= EXPRESS_FACTOR

    return base_cost


def calculate_outbound_transport_cost(
    customer_id: str, total_pallets: int
) -> float:
    """计算出库运输成本（一轮26周）"""
    distance = CUSTOMER_DISTANCES.get(customer_id, 200.0)

    # 30 pallets per FTL
    num_ftl = max(1, total_pallets / 30)

    cost_per_km = TRANSPORT_COST_PER_KM_PER_PALLET * 30  # per truck-km
    base_cost = distance * cost_per_km * num_ftl

    if distance > 600:
        base_cost *= EXPRESS_FACTOR

    return base_cost


def calculate_warehouse_costs(
    avg_raw_pallets: float, avg_fg_pallets: float,
    avg_chilled_pallets: float, avg_tank_days: float,
    overflow_raw_pallets: float = 0, overflow_fg_pallets: float = 0,
) -> Dict[str, float]:
    """计算仓储成本（年化后按26周折算）"""
    wh = WAREHOUSE
    weeks_per_half_year = 26

    raw_space = avg_raw_pallets * wh.pallet_location_cost_annual * (weeks_per_half_year / 52)
    fg_space = avg_fg_pallets * wh.pallet_location_cost_annual * (weeks_per_half_year / 52)
    chilled_space = avg_chilled_pallets * wh.pallet_location_cost_annual * (weeks_per_half_year / 52)
    tank_yard = avg_tank_days * wh.tank_yard_cost_per_day_per_tank * weeks_per_half_year / 52

    overflow = (overflow_raw_pallets + overflow_fg_pallets) * wh.overflow_pallet_cost_annual * (weeks_per_half_year / 52)

    return {
        "raw_materials_warehouse": raw_space,
        "finished_goods_warehouse": fg_space,
        "chilled_warehouse": chilled_space,
        "tank_yard": tank_yard,
        "overflow": overflow,
        "total_space_cost": raw_space + fg_space + chilled_space + tank_yard + overflow,
    }
