"""
TFC 仿真引擎 — 四角色编排器
============================
从四个模块读取决策参数 → 运行生产/库存/物流仿真 → 输出财务结果。

架构：
  purchasing.py ─┐
  sales.py ──────┼──→ simulation.py ──→ finance.py ──→ ROI
  operations.py ─┤
  supplychain.py ┘

用法：
  from simulation import run
  result = run()
"""
from typing import Dict
from dataclasses import dataclass, field

from config import (BASELINE, WEEKS_PER_ROUND, RANDOM_SEED,
                    PURCHASE_COST_FACTOR, STOCK_SPACE_FACTOR,
                    STOCK_INTEREST_FACTOR, STOCK_RISK_BASELINE,
                    DISTRIBUTION_COST_FACTOR, INVENTORY_VALUE_FACTOR)
from finance import ProfitLoss, Investment

import purchasing
import sales
import operations
import supplychain


@dataclass
class SimulationResult:
    """仿真结果"""
    pl: ProfitLoss = field(default_factory=ProfitLoss)
    inv: Investment = field(default_factory=Investment)
    roi: float = 0.0
    kpi_values: Dict[str, float] = field(default_factory=dict)


def run() -> SimulationResult:
    """
    执行一次仿真。

    流程：
      1. Sales     → 销售收入 + 客户 CI
      2. Operations → 生产计划 + 生产模拟 + 组件消耗
      3. Purchasing → 组件采购成本 + 入库运输
      4. SupplyChain → 库存 FIFO 追踪 + 仓储/人工/出库运输成本
      5. Finance   → P&L + Investment + ROI
    """
    sc_cfg = supplychain.SUPPLY_CHAIN_CONFIG
    ops_cfg = operations.OPERATIONS_CONFIG

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. SALES — 销售收入
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    rev = sales.calculate_revenue()
    total_revenue = rev["total_revenue"]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. OPERATIONS — 生产计划 & 模拟
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    product_weekly_demand = sales.weekly_demand_by_product()  # L/周 per product
    total_demand_by_product = {
        pid: liters * WEEKS_PER_ROUND
        for pid, liters in product_weekly_demand.items()
    }

    prod_sim = operations.ProductionSimulator(seed=RANDOM_SEED)
    total_production_cost = 0.0

    for week in range(1, WEEKS_PER_ROUND + 1):
        plan = prod_sim.make_plan(week, product_weekly_demand)
        result = prod_sim.simulate_week(
            week, plan,
            shifts_per_week=ops_cfg["production_shifts_per_week"],
            has_smed=ops_cfg["smed_training"],
            has_breakdown_training=ops_cfg["solve_breakdowns_training"],
        )
        total_production_cost += result.total_production_cost

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. PURCHASING — 组件需求 & 采购成本
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    component_needs = operations.calculate_component_needs(total_demand_by_product)
    purch = purchasing.calculate_purchase_costs(component_needs)
    total_purchase = purch["total_purchase"]
    total_inbound_transport = purch["total_transport"]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. SUPPLY CHAIN — 逐周库存仿真
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    inv_state = supplychain.InventoryState()

    # 每周组件/成品需求（均匀分配）
    weekly_comp_needs = {
        cid: total / WEEKS_PER_ROUND
        for cid, total in component_needs.items()
    }

    # 构建供应商 → component 映射
    supplier_for_component = {}
    for s in purchasing.SUPPLIERS:
        if hasattr(s, 'component_id'):
            supplier_for_component[s.component_id] = s.id

    def _comp_price(comp_id: str) -> float:
        sid = supplier_for_component.get(comp_id, "")
        return purchasing.get_effective_purchase_price(sid) if sid else 0.0

    def _comp_shelf_life(comp_id: str):
        c = supplychain.COMPONENT_MAP.get(comp_id)
        return c.shelf_life_weeks if c else None

    # ── 初始化库存 = 安全库存 + 1 周消耗（模拟在途+在库）──
    for comp_id, weekly_need in weekly_comp_needs.items():
        ss_weeks = sc_cfg["safety_stock_weeks"].get(comp_id, 2.0)
        initial = weekly_need * (ss_weeks + 1.0)
        if initial > 0:
            inv_state.add_component(comp_id, initial, 0,
                                    _comp_price(comp_id), _comp_shelf_life(comp_id))

    # ── 组件订单队列（按到达周）──
    # {arrival_week: [(comp_id, qty, price, shelf_life), ...]}
    pending_orders: dict = {}

    def place_order(comp_id: str, qty: float, current_week: int, lead_time_days: int):
        """下单，记录到达周"""
        lt_weeks = max(1, round(lead_time_days / 7))
        arrive = current_week + lt_weeks
        pending_orders.setdefault(arrive, []).append(
            (comp_id, qty, _comp_price(comp_id), _comp_shelf_life(comp_id))
        )

    # ── 首轮预下单（覆盖 lead time）──
    for comp_id, weekly_need in weekly_comp_needs.items():
        sid = supplier_for_component.get(comp_id, "")
        lt_days = purchasing.get_supplier_lead_time(sid) if sid else 7
        ss_weeks = sc_cfg["safety_stock_weeks"].get(comp_id, 2.0)
        # 预下 lead_time 内的需求量
        lt_weeks = max(1, round(lt_days / 7))
        pre_order = weekly_need * (lt_weeks + ss_weeks)
        place_order(comp_id, pre_order, 0, lt_days)

    total_obsoletes = 0.0
    cum_component_value = 0.0
    cum_fg_value = 0.0

    for week in range(1, WEEKS_PER_ROUND + 1):
        # ── 1) 收货（之前下单到达的）──
        if week in pending_orders:
            for comp_id, qty, price, shelf_life in pending_orders.pop(week):
                inv_state.add_component(comp_id, qty, week, price, shelf_life)

        # ── 2) 成品出库（发上周生产的货，第1周无库存）──
        for (pid, cid), pieces in sales.WEEKLY_DEMAND_PIECES.items():
            p = supplychain.PRODUCT_MAP.get(pid)
            if not p:
                continue
            liters = pieces * p.liters_per_pack
            inv_state.consume_fg(pid, liters, week)

        # ── 3) 消耗组件（用于本周生产）──
        for comp_id, need in weekly_comp_needs.items():
            inv_state.consume_component(comp_id, need, week)

        # ── 4) 成品入库（本周生产，下周发货）──
        total_all_weekly = sum(product_weekly_demand.values())
        cost_per_liter = (total_production_cost / (total_all_weekly * WEEKS_PER_ROUND)
                          if total_all_weekly > 0 else 0)
        for pid, weekly_liters in product_weekly_demand.items():
            p = supplychain.PRODUCT_MAP.get(pid)
            if not p:
                continue
            inv_state.add_fg(pid, weekly_liters, week, cost_per_liter, p.shelf_life_weeks)

        # ── 5) 下单补货（低于目标库存时触发）──
        for comp_id, need in weekly_comp_needs.items():
            current = inv_state.get_component_stock(comp_id, week)
            ss_weeks = sc_cfg["safety_stock_weeks"].get(comp_id, 2.0)
            target = need * (ss_weeks + 1.0)
            if current < target * 0.7:
                order_qty = target - current
                sid = supplier_for_component.get(comp_id, "")
                lt_days = purchasing.get_supplier_lead_time(sid) if sid else 7
                place_order(comp_id, order_qty, week, lt_days)

        # ── 6) 过期清理 ──
        total_obsoletes += inv_state.expire_all(week)

        # ── 7) 记录周库存 ──
        cum_component_value += inv_state.component_value()
        cum_fg_value += inv_state.fg_value()

    # 清理未到达的订单（仍计入平均值，代表在途库存）
    for orders in pending_orders.values():
        for comp_id, qty, price, _ in orders:
            cum_component_value += qty * price / 2  # 近似：在途 = 半程资金占用

    avg_component_value = cum_component_value / WEEKS_PER_ROUND
    avg_fg_value = cum_fg_value / WEEKS_PER_ROUND

    # 仓储 & 库存资金成本
    wh_costs = supplychain.calculate_warehouse_costs(avg_component_value, avg_fg_value)
    stock_interest = supplychain.calculate_stock_interest(avg_component_value, avg_fg_value)

    # 出库运输
    weekly_by_cust = sales.weekly_demand_by_customer()
    total_by_cust = {cid: liters * WEEKS_PER_ROUND for cid, liters in weekly_by_cust.items()}
    dist = supplychain.calculate_distribution_costs(total_by_cust)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. FINANCE — 间接成本 & 汇总
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    inspection = operations.calculate_inspection_cost()

    overhead = (BASELINE["overhead_energy"] +
                BASELINE["overhead_water"] +
                BASELINE["overhead_other"])

    handling = (BASELINE["handling_inbound"] +
                BASELINE["handling_outbound"] +
                inspection)

    admin = BASELINE["admin_cost"]

    project = BASELINE["project_cost"]
    if ops_cfg["smed_training"]:
        project += 6000

    interest_ar_ap = BASELINE["interest_ar_ap"]

    # ── P&L ──
    pl = ProfitLoss()
    pl.contracted_sales_revenue = total_revenue
    pl.bonus_or_penalty = 0.0
    pl.purchase_costs = (total_purchase + total_inbound_transport) * PURCHASE_COST_FACTOR
    pl.production_costs = total_production_cost
    pl.overhead_costs = overhead
    pl.stock_costs_interest = stock_interest * STOCK_INTEREST_FACTOR
    pl.stock_costs_space = wh_costs["total"] * STOCK_SPACE_FACTOR
    pl.stock_costs_risk = STOCK_RISK_BASELINE + total_obsoletes
    pl.handling_costs = handling
    pl.administration_costs = admin
    pl.distribution_costs = dist["total"] * DISTRIBUTION_COST_FACTOR
    pl.project_costs = project
    pl.interest_costs_ar_ap = interest_ar_ap

    # ── Investment ──
    inv = Investment()
    inv.fixed_building = BASELINE["fixed_building"]
    inv.inventory_components = avg_component_value * INVENTORY_VALUE_FACTOR
    inv.inventory_finished_goods = avg_fg_value * INVENTORY_VALUE_FACTOR
    inv.machinery = BASELINE["machinery"]
    inv.payment_terms_net = BASELINE["payment_terms_net"]

    roi = pl.operating_profit / inv.total * 100 if inv.total > 0 else 0

    return SimulationResult(
        pl=pl, inv=inv, roi=roi,
        kpi_values={
            "revenue": total_revenue,
            "gross_margin": pl.gross_margin,
            "operating_profit": pl.operating_profit,
        },
    )


def calibration_reports() -> str:
    """合并 CI 校准报告"""
    return purchasing.calibration_report() + "\n\n" + sales.calibration_report()
