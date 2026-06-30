"""
TFC 库存引擎 — FIFO保质期追踪 + 自动补货 + 库存成本
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import math


@dataclass
class StockBatch:
    """库存批次"""
    component_id: str
    quantity_liters: float
    production_week: int         # 哪个周生产的/到货的
    expiry_week: Optional[int]   # None = 无限保质期
    cost_per_liter: float = 0.0  # 采购单价
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
    component_on_order: Dict[str, List[dict]] = field(default_factory=dict)  # {arrival_week: qty}

    def get_component_stock(self, component_id: str, current_week: int) -> float:
        """获取某组件的可用库存（排除过期）"""
        batches = self.component_batches.get(component_id, [])
        return sum(b.quantity_liters for b in batches if not b.is_expired(current_week))

    def get_finished_goods_stock(self, product_id: str, current_week: int) -> float:
        """获取某成品的可用库存（升）"""
        batches = self.finished_goods_batches.get(product_id, [])
        return sum(b.quantity_liters for b in batches if not b.is_expired(current_week))

    def consume_component(self, component_id: str, qty_liters: float,
                          current_week: int) -> float:
        """FIFO 消耗组件，返回实际消耗量"""
        batches = self.component_batches.get(component_id, [])
        remaining = qty_liters
        consumed = 0.0

        # 过滤过期
        valid = [b for b in batches if not b.is_expired(current_week)]
        valid.sort(key=lambda b: b.production_week)  # FIFO

        for batch in valid:
            if remaining <= 0:
                break
            take = min(remaining, batch.quantity_liters)
            batch.quantity_liters -= take
            remaining -= take
            consumed += take

        # 清理空批次
        self.component_batches[component_id] = [b for b in batches if b.quantity_liters > 1e-9]

        return consumed

    def consume_finished_goods(self, product_id: str, qty_liters: float,
                               current_week: int) -> float:
        """FIFO 消耗成品"""
        batches = self.finished_goods_batches.get(product_id, [])
        remaining = qty_liters
        consumed = 0.0

        valid = [b for b in batches if not b.is_expired(current_week)]
        valid.sort(key=lambda b: b.production_week)

        for batch in valid:
            if remaining <= 0:
                break
            take = min(remaining, batch.quantity_liters)
            batch.quantity_liters -= take
            remaining -= take
            consumed += take

        self.finished_goods_batches[product_id] = [b for b in batches if b.quantity_liters > 1e-9]

        return consumed

    def add_component(self, component_id: str, qty_liters: float, current_week: int,
                      cost_per_liter: float, shelf_life_weeks: Optional[int]):
        """添加组件到库存"""
        expiry = (current_week + shelf_life_weeks) if shelf_life_weeks else None
        batch = StockBatch(
            component_id=component_id, quantity_liters=qty_liters,
            production_week=current_week, expiry_week=expiry,
            cost_per_liter=cost_per_liter,
        )
        if component_id not in self.component_batches:
            self.component_batches[component_id] = []
        self.component_batches[component_id].append(batch)

    def add_finished_good(self, product_id: str, qty_liters: float, current_week: int,
                          cost_per_liter: float, shelf_life_weeks: int):
        """添加工成品到库存"""
        expiry = current_week + shelf_life_weeks
        batch = StockBatch(
            component_id=product_id, quantity_liters=qty_liters,
            production_week=current_week, expiry_week=expiry,
            cost_per_liter=cost_per_liter, is_finished_good=True,
        )
        if product_id not in self.finished_goods_batches:
            self.finished_goods_batches[product_id] = []
        self.finished_goods_batches[product_id].append(batch)

    def expire_all(self, current_week: int) -> float:
        """清理所有过期库存，返回过期总价值"""
        total_loss = 0.0
        for comp_id in list(self.component_batches.keys()):
            batches = self.component_batches[comp_id]
            for b in batches:
                if b.is_expired(current_week):
                    total_loss += b.value
            self.component_batches[comp_id] = [b for b in batches if not b.is_expired(current_week)]

        for prod_id in list(self.finished_goods_batches.keys()):
            batches = self.finished_goods_batches[prod_id]
            for b in batches:
                if b.is_expired(current_week):
                    total_loss += b.value
            self.finished_goods_batches[prod_id] = [b for b in batches if not b.is_expired(current_week)]

        return total_loss

    def total_component_value(self) -> float:
        """组件库存总价值"""
        total = 0.0
        for batches in self.component_batches.values():
            total += sum(b.value for b in batches)
        return total

    def total_finished_goods_value(self) -> float:
        """成品库存总价值 (COGS)"""
        total = 0.0
        for batches in self.finished_goods_batches.values():
            total += sum(b.value for b in batches)
        return total

    def total_pallets(self, include_raw: bool = True, include_fg: bool = True) -> float:
        """估算总托盘数"""
        total = 0.0
        from entities import COMPONENT_MAP, PRODUCT_MAP
        if include_raw:
            for comp_id, batches in self.component_batches.items():
                comp = COMPONENT_MAP.get(comp_id)
                if comp and comp.pallet_content:
                    liters = sum(b.quantity_liters for b in batches)
                    total += liters / comp.pallet_content  # simplified
        if include_fg:
            for prod_id, batches in self.finished_goods_batches.items():
                prod = PRODUCT_MAP.get(prod_id)
                if prod:
                    liters = sum(b.quantity_liters for b in batches)
                    total += liters / prod.liters_per_pack / prod.per_pallet
        return total
