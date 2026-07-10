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
    # 来源: Decision.csv Row 65-70
    "safety_stock_weeks": {
        "pack_1l":    1.5,
        "pet":        2.1,
        "orange":     1.5,
        "mango":      2.0,
        "vitamin_c":  2.8,
    },
    # ── 批次大小（周数）per component ──
    # 来源: Decision.csv Row 65-70
    "lot_size_weeks": {
        "pack_1l":    3,
        "pet":        3,
        "orange":     3,
        "mango":      3,
        "vitamin_c":  4,
    },
    # ── 生产计划冻结期（周）──
    # 来源: Decision.csv Row 72
    "frozen_period_weeks": 3,
    "production_interval_weeks": 1,
    # ── 成品安全库存（周数）──
    # 来源: Decision.csv Row 74-80
    "fg_safety_stock_weeks": {
        "p_orange_1l":  2.5,
        "p_ocp_1l":     2.8,
        "p_om_1l":      2.0,
        "p_orange_pet": 2.5,
        "p_ocp_pet":    3.0,
        "p_om_pet":     3.0,
    },
    # ── 成品生产间隔（天）──
    # 来源: Decision.csv Row 74-80
    "fg_production_intervals_days": {
        "p_orange_1l":  10,
        "p_ocp_1l":     10,
        "p_om_1l":      10,
        "p_orange_pet":  9,
        "p_ocp_pet":    10,
        "p_om_pet":      9,
    },
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
                      cost: float, shelf_life_weeks: Optional[int],
                      order_week: Optional[int] = None):
        """添加组件库存批次。

        Args:
            order_week: 下单周次。若提供且组件有保质期，则 expiry 从下单周起算
                        （per entity_info.txt:79-80 "The expiry countdown starts
                         from the supplier's order date"）。
                        若未提供则回退到旧行为（从收货周起算）。
        """
        if shelf_life_weeks and order_week is not None:
            expiry = order_week + shelf_life_weeks
        elif shelf_life_weeks:
            expiry = week + shelf_life_weeks
        else:
            expiry = None
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
    """出库运输成本（26 周）。

    费率已校准至游戏基线 (finance_info.txt 未给出具体单价，
    仅提及 shipment-size discount 和 express factor >600km)。
    隐含游戏费率 ≈ €2.93/truck-km → 使用 €0.098/pallet-km。
    """
    distances = {"c_fg": 200, "c_land": 350, "c_dom": 150}
    distance = distances.get(customer_id, 200)
    num_ftl = max(1, total_pallets / 30)
    # 校准后费率: €0.098/pallet-km × 30 pallets = €2.94/truck-km
    cost_per_km = 0.098 * 30  # per truck-km (calibrated to game baseline)
    base = distance * cost_per_km * num_ftl
    if distance > 600:
        base *= 1.5
    return base


def calculate_distribution_costs(demand_by_customer: Dict[str, float],
                                 demand_detail: Dict = None) -> Dict:
    """
    计算所有客户的出库运输成本。

    参数:
        demand_by_customer: {customer_id: total_liters_over_26_weeks}
        demand_detail: 可选，{(product_id, customer_id): weekly_pieces}
                      传入后按产品组合加权计算 avg_liters_per_pallet

    返回:
        {"total": float, "by_customer": {customer_id: float}}
    """
    from entities import PRODUCT_MAP

    # 按产品组合加权计算平均升/托盘
    if demand_detail:
        # 按客户汇总每种产品的总升数，计算加权平均 pallet 密度
        cust_liters: Dict[str, float] = {}
        cust_pallets: Dict[str, float] = {}
        for (pid, cid), pieces in demand_detail.items():
            p = PRODUCT_MAP.get(pid)
            if not p:
                continue
            liters = pieces * p.liters_per_pack
            pallets_from_pid = pieces / p.per_pallet if p.per_pallet > 0 else 0
            cust_liters[cid] = cust_liters.get(cid, 0.0) + liters
            cust_pallets[cid] = cust_pallets.get(cid, 0.0) + pallets_from_pid
        # 按客户计算加权平均
        avg_liters_map = {}
        for cid in cust_liters:
            if cust_pallets.get(cid, 0) > 0:
                avg_liters_map[cid] = cust_liters[cid] / cust_pallets[cid]
    else:
        avg_liters_map = {}

    total = 0.0
    by_customer = {}
    for cid, liters in demand_by_customer.items():
        # 按产品组合加权计算 avg_liters_per_pallet，回退到 600
        avg_liters_per_pallet = avg_liters_map.get(cid, 600.0)
        pallets = liters / avg_liters_per_pallet
        cost = calculate_outbound_transport(cid, pallets)
        total += cost
        by_customer[cid] = cost
    return {"total": total, "by_customer": by_customer}


def calculate_warehouse_costs(avg_raw_value: float, avg_fg_value: float,
                              avg_tank_days: float = 0,
                              avg_comp_qty: Dict[str, float] = None,
                              avg_fg_qty: Dict[str, float] = None,
                              raw_pallet_capacity: int = None,
                              fg_pallet_capacity: int = None) -> Dict[str, float]:
    """仓储成本（26 周），基于实际托盘/罐区占用计算。

    空间成本按配置的托盘位数量（容量）计费，非实际占用。
    per operations_info.txt: "Each additional pallet location costs €200"
    "you will always pay the fixed rate for each pallet location every year"

    Args:
        avg_raw_value: 组件平均库存价值（备用，用于回退估算）
        avg_fg_value: 成品平均库存价值（备用）
        avg_tank_days: 罐区平均每日使用量
        avg_comp_qty: {comp_id: avg_quantity} 各组件平均库存量（pieces for 包装, L for 液体）
        avg_fg_qty: {pid: avg_liters} 各成品平均库存升数
        raw_pallet_capacity: 原料仓库配置托盘位数（None=使用默认值）
        fg_pallet_capacity: 成品仓库配置托盘位数（None=使用默认值）
    """
    wh = WAREHOUSE
    half = WEEKS_PER_ROUND / 52
    half_year_days = WEEKS_PER_ROUND * 5  # 130 working days

    # 使用传入的容量配置，否则回退到默认值
    raw_capacity = raw_pallet_capacity if raw_pallet_capacity is not None else wh.raw_materials_pallet_locations
    fg_capacity = fg_pallet_capacity if fg_pallet_capacity is not None else wh.finished_goods_pallet_locations

    raw_pallets = 0.0
    fg_pallets = 0.0
    tank_liters = 0.0

    # ── 组件托盘/罐区 ──
    if avg_comp_qty:
        for comp_id, avg_qty in avg_comp_qty.items():
            c = COMPONENT_MAP.get(comp_id)
            if c and c.pallet_content:
                # 包装组件：按实际 pallet_content 换算
                raw_pallets += avg_qty / c.pallet_content
            else:
                # 液体组件 → 罐区
                tank_liters += avg_qty
    else:
        # 回退：粗略估算
        raw_pallets = avg_raw_value / 0.30 / 600

    # ── 成品托盘 ──
    if avg_fg_qty:
        for pid, avg_liters in avg_fg_qty.items():
            p = PRODUCT_MAP.get(pid)
            if p and p.per_pallet > 0:
                pieces = avg_liters / p.liters_per_pack
                fg_pallets += pieces / p.per_pallet
    else:
        fg_pallets = avg_fg_value / 0.50 / 600

    # ── 空间成本 ──
    # 固定费用按容量（托盘位）收取，与实际占用无关
    # per ops_info: "you will always pay the fixed rate for each pallet location every year"
    raw_space = raw_capacity * wh.pallet_location_cost_annual * half
    fg_space = fg_capacity * wh.pallet_location_cost_annual * half

    # 罐区成本由 operations.calculate_warehouse_cost_raw_materials 统一计算
    # (含 €25/天 + €10 intake + €100 delivery，更完整)

    # 溢出仓库（超出配置托盘位时触发，€3/托盘/天）
    overflow_raw = max(0.0, raw_pallets - raw_capacity)
    overflow_fg = max(0.0, fg_pallets - fg_capacity)
    overflow_cost = (overflow_raw + overflow_fg) * wh.overflow_pallet_cost_per_day * half_year_days

    return {
        "raw_space": raw_space,
        "fg_space": fg_space,
        "overflow": overflow_cost,
        "total": raw_space + fg_space + overflow_cost,
        "raw_pallets": raw_pallets,
        "fg_pallets": fg_pallets,
    }


def calculate_stock_interest(avg_component_value: float, avg_fg_value: float) -> float:
    """库存资金占用利息（26 周）"""
    return (avg_component_value + avg_fg_value) * INTEREST_RATE_ANNUAL * (WEEKS_PER_ROUND / 52)
