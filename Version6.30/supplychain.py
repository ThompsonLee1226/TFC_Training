"""
Supply Chain 模块 — 对应游戏 Supply Chain 页面
==============================================
包含：供应链决策参数、FIFO 库存引擎、运输/仓储成本。

使用方法：修改 SUPPLY_CHAIN_CONFIG 字典中的参数，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from entities import (
    COMPONENT_MAP, PRODUCT_MAP, CUSTOMER_MAP,
    WAREHOUSE, TradeUnit,
)
from config import WEEKS_PER_ROUND


# ═══════════════════════════════════════════════════════════════
# 供应链决策参数（对应 Supply Chain 页面设置）
# ═══════════════════════════════════════════════════════════════

SUPPLY_CHAIN_CONFIG = {
    # ── 安全库存（周数）per component ──
    "safety_stock_weeks": {
        "pack_1l":    2.5,
        "pet":        2.7,
        "orange":     1.0,
        "mango":      2.3,
        "vitamin_c":  3.5,
    },
    # ── 批次大小（周数）per component ──
    "lot_size_weeks": {
        "pack_1l":    1.8,
        "pet":        2.0,
        "orange":     1.5,
        "mango":      2.2,
        "vitamin_c":  2.2,
    },
    # ── 生产计划冻结期（周）──
    "frozen_period_weeks": 2,
    "production_interval_weeks": 1,
}


# ═══════════════════════════════════════════════════════════════
# FIFO 库存引擎
# ═══════════════════════════════════════════════════════════════

INTEREST_RATE_ANNUAL = 0.15


@dataclass
class StockBatch:
    """库存批次"""
    component_id: str
    quantity_liters: float
    production_week: int
    expiry_week: Optional[int] = None
    cost_per_liter: float = 0.0
    is_finished_good: bool = False

    def is_expired(self, current_week: int) -> bool:
        if self.expiry_week is None:
            return False
        return current_week >= self.expiry_week

    @property
    def value(self) -> float:
        return self.quantity_liters * self.cost_per_liter


@dataclass
class InventoryState:
    """库存状态"""
    component_batches: Dict[str, List[StockBatch]] = field(default_factory=dict)
    finished_goods_batches: Dict[str, List[StockBatch]] = field(default_factory=dict)
    component_on_order: Dict[str, List[dict]] = field(default_factory=dict)

    def _valid(self, batches: List[StockBatch], week: int) -> List[StockBatch]:
        return sorted(
            [b for b in batches if not b.is_expired(week)],
            key=lambda b: b.production_week,  # FIFO
        )

    def _cleanup(self, comp_id: str, batches: List[StockBatch]):
        self.component_batches[comp_id] = [b for b in batches if b.quantity_liters > 1e-9]

    def _cleanup_fg(self, prod_id: str, batches: List[StockBatch]):
        self.finished_goods_batches[prod_id] = [b for b in batches if b.quantity_liters > 1e-9]

    def get_component_stock(self, comp_id: str, week: int) -> float:
        return sum(b.quantity_liters for b in self._valid(
            self.component_batches.get(comp_id, []), week))

    def get_fg_stock(self, prod_id: str, week: int) -> float:
        return sum(b.quantity_liters for b in self._valid(
            self.finished_goods_batches.get(prod_id, []), week))

    def consume_component(self, comp_id: str, qty: float, week: int) -> float:
        """FIFO 消耗组件，返回实际消耗量"""
        batches = self.component_batches.get(comp_id, [])
        consumed = 0.0
        remaining = qty
        for b in self._valid(batches, week):
            if remaining <= 0:
                break
            take = min(remaining, b.quantity_liters)
            b.quantity_liters -= take
            remaining -= take
            consumed += take
        self._cleanup(comp_id, batches)
        return consumed

    def consume_fg(self, prod_id: str, qty: float, week: int) -> float:
        """FIFO 消耗成品"""
        batches = self.finished_goods_batches.get(prod_id, [])
        consumed = 0.0
        remaining = qty
        for b in self._valid(batches, week):
            if remaining <= 0:
                break
            take = min(remaining, b.quantity_liters)
            b.quantity_liters -= take
            remaining -= take
            consumed += take
        self._cleanup_fg(prod_id, batches)
        return consumed

    def add_component(self, comp_id: str, qty: float, week: int,
                      cost: float, shelf_life_weeks: Optional[int]):
        expiry = (week + shelf_life_weeks) if shelf_life_weeks else None
        batch = StockBatch(comp_id, qty, week, expiry, cost)
        self.component_batches.setdefault(comp_id, []).append(batch)

    def add_fg(self, prod_id: str, qty: float, week: int,
               cost: float, shelf_life_weeks: int):
        expiry = week + shelf_life_weeks
        batch = StockBatch(prod_id, qty, week, expiry, cost, is_finished_good=True)
        self.finished_goods_batches.setdefault(prod_id, []).append(batch)

    def expire_all(self, week: int) -> float:
        """清理过期库存，返回报废总价值"""
        loss = 0.0
        for batches in self.component_batches.values():
            for b in batches:
                if b.is_expired(week):
                    loss += b.value
        for batches in self.finished_goods_batches.values():
            for b in batches:
                if b.is_expired(week):
                    loss += b.value
        return loss

    def component_value(self) -> float:
        return sum(sum(b.value for b in batches)
                   for batches in self.component_batches.values())

    def fg_value(self) -> float:
        return sum(sum(b.value for b in batches)
                   for batches in self.finished_goods_batches.values())


# ═══════════════════════════════════════════════════════════════
# 运输与仓储成本
# ═══════════════════════════════════════════════════════════════

def calculate_outbound_transport(customer_id: str, total_pallets: float) -> float:
    """出库运输成本（26 周）"""
    distances = {"c_fg": 200, "c_land": 350, "c_dom": 150}
    distance = distances.get(customer_id, 200)
    num_ftl = max(1, total_pallets / 30)
    cost_per_km = 0.15 * 30  # per truck-km
    base = distance * cost_per_km * num_ftl
    if distance > 600:
        base *= 1.5
    return base


def calculate_distribution_costs(demand_by_customer: Dict[str, float]) -> Dict:
    """
    计算所有客户的出库运输成本。

    参数:
        demand_by_customer: {customer_id: total_liters_over_26_weeks}

    返回:
        {"total": float, "by_customer": {customer_id: float}}
    """
    total = 0.0
    by_customer = {}
    for cid, liters in demand_by_customer.items():
        # 估算托盘数 = 总升 / (每托盘平均升数)
        avg_liters_per_pallet = 600  # rough average across all products
        pallets = liters / avg_liters_per_pallet
        cost = calculate_outbound_transport(cid, pallets)
        total += cost
        by_customer[cid] = cost
    return {"total": total, "by_customer": by_customer}


def calculate_warehouse_costs(avg_raw_value: float, avg_fg_value: float,
                              avg_tank_days: float = 0) -> Dict[str, float]:
    """仓储成本（26 周，从库存价值反推空间占用）"""
    wh = WAREHOUSE
    half = WEEKS_PER_ROUND / 52

    # 粗略估算托盘数：库存价值 / 单位成本 / 每托盘容量
    raw_pallets = avg_raw_value / 0.30 / 600  # rough
    fg_pallets = avg_fg_value / 0.50 / 600

    raw_space = raw_pallets * wh.pallet_location_cost_annual * half
    fg_space = fg_pallets * wh.pallet_location_cost_annual * half
    tank = avg_tank_days * wh.tank_yard_cost_per_day_per_tank * half

    return {
        "raw_space": raw_space,
        "fg_space": fg_space,
        "tank_yard": tank,
        "total": raw_space + fg_space + tank,
    }


def calculate_handling_costs(inbound_pallets: float, outbound_pallets: float) -> Dict[str, float]:
    """人工搬运成本"""
    wh = WAREHOUSE
    half = WEEKS_PER_ROUND / 52
    inbound_labor = inbound_pallets * 0.5 * 20 * half  # rough: 0.5h/pallet × EUR 20/h
    outbound_labor = outbound_pallets * 0.3 * 20 * half
    return {
        "inbound": inbound_labor,
        "outbound": outbound_labor,
        "total": inbound_labor + outbound_labor,
    }


def calculate_stock_interest(avg_component_value: float, avg_fg_value: float) -> float:
    """库存资金占用利息（26 周）"""
    return (avg_component_value + avg_fg_value) * INTEREST_RATE_ANNUAL * (WEEKS_PER_ROUND / 52)
