"""
TFC 仿真引擎 — 基线标定 + 增量模型

策略：从已知 Round 3 实际财务数据标定基线参数，
决策变动通过相对效应模型传播到财务结果。
每次调用仿真运行一次，返回单次随机结果（含噪声）。
"""
import random
import math
from typing import Dict, List, Tuple
from dataclasses import dataclass, field

from entities import (
    SUPPLIERS, SUPPLIER_MAP, SUPPLIER_BY_COMPONENT,
    CUSTOMERS, CUSTOMER_MAP,
    PRODUCTS, PRODUCT_MAP, COMPONENTS, COMPONENT_MAP,
    BOM, FACILITY, WAREHOUSE,
)
from contracts import predict_supplier_contract_index, predict_customer_contract_index
from finance import FinanceCalculator, ProfitLoss, Investment
from decisions import RoundDecisions, ROUND3_DECISIONS


# ── Round 3 实际基线 ──
# 从 Finance 页面直接提取
BASELINE = {
    "revenue": 2_655_320.0,
    "purchase_costs": 815_273.0,
    "production_costs": 463_781.0,
    "overhead_energy": 142_354.0,
    "overhead_water": 39_807.0,
    "overhead_other": 146_923.0,
    "stock_interest": 16_669.0,
    "stock_space": 258_553.0,
    "stock_risk": 13_266.0,
    "handling_inbound": 103_390.0,
    "handling_outbound": 80_811.0,
    "admin_cost": 111_052.0,
    "distribution": 192_114.0,
    "project_cost": 14_000.0,
    "interest_ar_ap": 22_190.0,
    "fixed_building": 2_500_000.0,
    "inventory_components": 222_252.0,
    "machinery": 802_500.0,
    "payment_terms_net": 295_863.0,
    "operating_profit": 235_137.0,
    "roi": 6.15,
}


@dataclass
class SimulationResult:
    """单次仿真的结果"""
    round_number: int
    pl: ProfitLoss = field(default_factory=ProfitLoss)
    inv: Investment = field(default_factory=Investment)
    roi: float = 0.0
    kpi_values: Dict[str, float] = field(default_factory=dict)


class TFCSimulation:
    """TFC 仿真引擎 — 基线标定 + 增量扰动"""

    def __init__(self, decisions: RoundDecisions, base_seed: int = 42):
        self.decisions = decisions
        self.base_seed = base_seed

    def run_single_iteration(self, iteration: int) -> Tuple[ProfitLoss, Investment, float, Dict]:
        seed = self.base_seed * 1000 + iteration
        rng = random.Random(seed)
        dec = self.decisions

        # ── 计算相对决策变动 ──

        # Supplier CI changes
        supplier_ci_deltas = {}
        for s in SUPPLIERS:
            pd = next((d for d in dec.purchasing if d.supplier_id == s.id), None)
            if pd:
                new_ci = predict_supplier_contract_index(
                    quality=pd.quality.value,
                    delivery_window=pd.delivery_window.value,
                    delivery_reliability_pct=pd.delivery_reliability_pct,
                    payment_term_weeks=pd.payment_term_weeks,
                    trade_unit=pd.trade_unit.value,
                    vmi=pd.vmi,
                    supplier_development=pd.supplier_development,
                )
                supplier_ci_deltas[s.id] = new_ci / s.contract_index if s.contract_index else 1.0
            else:
                supplier_ci_deltas[s.id] = 1.0

        # Customer CI changes
        customer_ci_deltas = {}
        for c in CUSTOMERS:
            sd = next((d for d in dec.sales if d.customer_id == c.id), None)
            if sd:
                new_ci = predict_customer_contract_index(
                    service_level_pct=sd.service_level_pct,
                    shelf_life_pct=sd.shelf_life_pct,
                    payment_term_weeks=sd.payment_term_weeks,
                    trade_unit=sd.trade_unit.value,
                    promotional_pressure=sd.promotional_pressure.value,
                    promotion_horizon=sd.promotion_horizon.value,
                    vmi=sd.vmi,
                )
                customer_ci_deltas[c.id] = new_ci / c.contract_index if c.contract_index else 1.0
            else:
                customer_ci_deltas[c.id] = 1.0

        # Average CI deltas
        avg_supplier_ci_delta = sum(supplier_ci_deltas.values()) / len(supplier_ci_deltas)
        avg_customer_ci_delta = sum(customer_ci_deltas.values()) / len(customer_ci_deltas)

        # Safety stock delta
        avg_ss_weeks = sum(dec.supply_chain.safety_stock_weeks.values()) / len(dec.supply_chain.safety_stock_weeks)
        baseline_ss = 2.4  # average of Round 3: (2.5+2.7+1.0+2.3+3.5)/5
        ss_delta = avg_ss_weeks / baseline_ss

        # ── 蒙特卡洛噪声 ──
        demand_noise = rng.gauss(1.0, 0.08)     # 需求波动 ±8%
        production_noise = rng.gauss(1.0, 0.03)  # 生产效率 ±3%
        service_noise = rng.gauss(1.0, 0.02)     # 服务水平 ±2%
        cost_noise = rng.gauss(1.0, 0.04)        # 成本波动 ±4%

        # ── 从基线计算财务 ──

        # Revenue = baseline_revenue × customer_CI_delta × demand_noise
        revenue = BASELINE["revenue"] * avg_customer_ci_delta * demand_noise

        # Purchase costs: baseline × supplier_CI_delta × demand_noise × cost_noise
        # (higher CI = higher purchase cost; higher demand = more purchase)
        purchase = BASELINE["purchase_costs"] * avg_supplier_ci_delta * demand_noise * cost_noise

        # Production costs: baseline × demand_noise × production_noise
        production = BASELINE["production_costs"] * demand_noise * production_noise

        # Stock costs: baseline × ss_delta × demand_noise
        stock_interest = BASELINE["stock_interest"] * ss_delta * demand_noise * cost_noise
        stock_space = BASELINE["stock_space"] * ss_delta * demand_noise
        stock_risk = BASELINE["stock_risk"] * ss_delta * demand_noise

        # Overhead (semi-fixed, per round values)
        overhead = (BASELINE["overhead_energy"] + BASELINE["overhead_water"] +
                   BASELINE["overhead_other"]) * cost_noise

        # Handling: baseline × demand_noise
        handling = (BASELINE["handling_inbound"] + BASELINE["handling_outbound"]) * demand_noise * cost_noise

        # Inspection: per supplier, half-year (26/52)
        inspection_count = sum(1 for v in dec.operations.raw_materials_inspection.values() if v)
        inspection = inspection_count * WAREHOUSE.inspection_cost_per_supplier_annual * 0.5

        # Admin: semi-fixed
        admin = BASELINE["admin_cost"] * demand_noise

        # Distribution: baseline × demand_noise
        distribution = BASELINE["distribution"] * demand_noise

        # Projects
        project = BASELINE["project_cost"]
        if dec.operations.smed_training:
            project += 6_000  # SMED extra cost
        if dec.operations.solve_breakdowns_training:
            project += 0  # already in baseline

        # Interest on AR/AP
        interest_ar_ap = BASELINE["interest_ar_ap"] * demand_noise

        # ── 构建 P&L ──
        pl = ProfitLoss()
        pl.contracted_sales_revenue = revenue
        pl.bonus_or_penalty = 0.0
        pl.purchase_costs = purchase
        pl.production_costs = production
        pl.overhead_costs = overhead
        pl.stock_costs_interest = stock_interest
        pl.stock_costs_space = stock_space
        pl.stock_costs_risk = stock_risk
        pl.handling_costs = handling + inspection
        pl.administration_costs = admin
        pl.distribution_costs = distribution
        pl.project_costs = project
        pl.interest_costs_ar_ap = interest_ar_ap

        # ── 构建 Investment ──
        inv = Investment()
        inv.fixed_building = BASELINE["fixed_building"]
        inv.inventory_components = BASELINE["inventory_components"] * ss_delta * demand_noise
        inv.inventory_finished_goods = 0  # calc from CS difference
        inv.machinery = BASELINE["machinery"]
        inv.payment_terms_net = BASELINE["payment_terms_net"] * demand_noise

        roi = pl.operating_profit / inv.total * 100 if inv.total > 0 else 0

        kpis = {
            "revenue": revenue,
            "gross_margin": pl.gross_margin,
            "operating_profit": pl.operating_profit,
            "stock_interest": stock_interest,
        }

        return pl, inv, roi, kpis

    def run_round(self, iteration: int = 0) -> SimulationResult:
        """运行单次仿真，返回一次迭代的结果（已去除蒙特卡洛求平均）"""
        pl, inv, roi, kpis = self.run_single_iteration(iteration)

        return SimulationResult(
            round_number=self.decisions.round_number,
            pl=pl,
            inv=inv,
            roi=roi,
            kpi_values=kpis,
        )
