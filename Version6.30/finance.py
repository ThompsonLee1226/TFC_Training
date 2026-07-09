"""
TFC 财务计算器 — 完整 P&L + Investment + ROI

基于 InfoCenter Finance 章节的公式实现。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math

WEEKS_PER_ROUND = 26  # 半年
INTEREST_RATE_ANNUAL = 0.15
INTEREST_RATE_WEEKLY = INTEREST_RATE_ANNUAL / 52


@dataclass
class ProfitLoss:
    """损益表"""
    # Revenue
    contracted_sales_revenue: float = 0.0
    bonus_or_penalty: float = 0.0  # positive = bonus

    # COGS
    purchase_costs: float = 0.0   # 含运输
    production_costs: float = 0.0

    # Indirect costs
    overhead_costs: float = 0.0     # 水电+管理
    stock_costs_interest: float = 0.0
    stock_costs_space: float = 0.0
    stock_costs_risk: float = 0.0   # 报废+损耗
    handling_costs: float = 0.0     # 入库+出库人力
    administration_costs: float = 0.0
    distribution_costs: float = 0.0
    contract_costs: float = 0.0     # 合同终止费用
    project_costs: float = 0.0      # 改进项目
    interest_costs_ar_ap: float = 0.0

    @property
    def total_revenue(self) -> float:
        return self.contracted_sales_revenue + self.bonus_or_penalty

    @property
    def cogs(self) -> float:
        return self.purchase_costs + self.production_costs

    @property
    def gross_margin(self) -> float:
        return self.total_revenue - self.cogs

    @property
    def stock_costs(self) -> float:
        return self.stock_costs_interest + self.stock_costs_space + self.stock_costs_risk

    @property
    def indirect_costs(self) -> float:
        return (
            self.overhead_costs + self.stock_costs + self.handling_costs +
            self.administration_costs + self.distribution_costs +
            self.contract_costs + self.project_costs + self.interest_costs_ar_ap
        )

    @property
    def operating_profit(self) -> float:
        return self.gross_margin - self.indirect_costs

    @property
    def profit_pct(self) -> float:
        """Profit as % of revenue"""
        if self.total_revenue == 0:
            return 0.0
        return self.operating_profit / self.total_revenue * 100


@dataclass
class Investment:
    """投资构成"""
    fixed_building: float = 2_500_000.0
    inventory_components: float = 0.0
    inventory_finished_goods: float = 0.0
    machinery: float = 802_500.0   # bottling lines + mixers
    payment_terms_net: float = 0.0  # AP - AR
    software: float = 0.0

    @property
    def total_inventory(self) -> float:
        return self.inventory_components + self.inventory_finished_goods

    @property
    def total(self) -> float:
        return (
            self.fixed_building + self.total_inventory +
            self.machinery + self.payment_terms_net + self.software
        )


def calculate_roi(pl: ProfitLoss, inv: Investment) -> float:
    """ROI = Operating Profit / Investment × 100%"""
    if inv.total == 0:
        return 0.0
    return pl.operating_profit / inv.total * 100


class FinanceCalculator:
    """财务计算器 — 从仿真结果汇总生成 P&L 和 Investment。

    注意：此类为参考实现，当前 simulation.py 直接构造 ProfitLoss / Investment 对象。
    保留此类作为备用接口（如需从外部数据直接生成财务报告）。
    """

    def __init__(self):
        self.pl = ProfitLoss()
        self.inv = Investment()

    def compute(self,
                # Revenue inputs
                product_sales: Dict[str, Dict[str, float]],  # {product: {customer: liters_sold}}
                product_prices: Dict[str, float],             # {product: effective_sales_price_per_liter}
                customer_contract_indices: Dict[str, float],
                # Purchasing inputs
                component_purchased_liters: Dict[str, float],
                component_purchase_prices: Dict[str, float],  # per liter
                inbound_transport_cost: float,
                # Production inputs
                total_production_cost: float,                 # full 26 weeks
                # Inventory averages (over 26 weeks)
                avg_component_stock_value: float,
                avg_finished_goods_stock_value: float,
                total_obsoletes_value: float,
                # Warehousing
                warehouse_space_cost: float,
                overflow_cost: float,
                # Handling
                handling_cost_inbound: float,
                handling_cost_outbound: float,
                inspection_cost: float,
                # Admin
                num_inbound_orders: int = 50,
                num_inbound_order_lines: int = 500,
                num_outbound_orders: int = 150,
                num_outbound_order_lines: int = 1000,
                # Distribution
                distribution_costs: float = 0.0,
                # Other
                overhead_energy: float = 0.0,
                overhead_water: float = 0.0,
                overhead_other: float = 0.0,
                contract_termination_cost: float = 0.0,
                project_smed: float = 0.0,
                project_breakdown_training: float = 0.0,
                payment_terms_ap: float = 0.0,   # Accounts Payable
                payment_terms_ar: float = 0.0,   # Accounts Receivable
                ) -> tuple[ProfitLoss, Investment, float]:

        pl = ProfitLoss()
        inv = Investment()

        # ── Revenue ──
        total_revenue = 0.0
        for product_id, customers in product_sales.items():
            price = product_prices.get(product_id, 0.0)
            for customer_id, liters in customers.items():
                ci = customer_contract_indices.get(customer_id, 1.0)
                total_revenue += price * liters * ci

        pl.contracted_sales_revenue = total_revenue

        # Bonus/Penalty (simplified: based on service level shortfall)
        # Already factored into realized revenue; here as placeholder

        # ── COGS ──
        # Purchase costs
        purchase_value = 0.0
        for comp_id, liters in component_purchased_liters.items():
            price = component_purchase_prices.get(comp_id, 0.0)
            purchase_value += liters * price
        pl.purchase_costs = purchase_value + inbound_transport_cost

        # Production costs
        pl.production_costs = total_production_cost

        # ── Indirect Costs ──

        # Overhead
        pl.overhead_costs = overhead_energy + overhead_water + overhead_other

        # Stock costs
        avg_stock_value = avg_component_stock_value + avg_finished_goods_stock_value
        pl.stock_costs_interest = avg_stock_value * INTEREST_RATE_ANNUAL * (WEEKS_PER_ROUND / 52)
        pl.stock_costs_space = warehouse_space_cost + overflow_cost
        pl.stock_costs_risk = total_obsoletes_value

        # Handling
        pl.handling_costs = handling_cost_inbound + handling_cost_outbound + inspection_cost

        # Administration
        pl.administration_costs = (
            num_inbound_orders * 50 + num_inbound_order_lines * 10 +
            num_outbound_orders * 25 + num_outbound_order_lines * 2 +
            5 * 40000 * (WEEKS_PER_ROUND / 52)  # supplier relationship EUR 40k/year/supplier × 5 suppliers
        )

        # Distribution
        pl.distribution_costs = distribution_costs

        # Contract
        pl.contract_costs = contract_termination_cost

        # Project
        pl.project_costs = project_smed + project_breakdown_training

        # Interest on AR/AP
        pl.interest_costs_ar_ap = (
            (payment_terms_ar - payment_terms_ap) * INTEREST_RATE_ANNUAL * (WEEKS_PER_ROUND / 52)
        )

        # ── Investment ──
        inv.fixed_building = 2_500_000.0
        inv.inventory_components = avg_component_stock_value
        inv.inventory_finished_goods = avg_finished_goods_stock_value
        inv.machinery = 802_500.0
        inv.payment_terms_net = payment_terms_ap - payment_terms_ar
        inv.software = 0.0

        roi = calculate_roi(pl, inv)

        return pl, inv, roi
