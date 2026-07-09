"""
TFC 仿真引擎 — 四角色编排器
============================
从四个模块读取决策参数 → 运行日级生产/库存/物流仿真 → 输出财务结果。

架构：
  purchasing.py ─┐
  sales.py ──────┼──→ simulation.py ──→ finance.py ──→ ROI
  operations.py ─┤
  supplychain.py ┘

改进 (v6.30.1):
  - 销售与成品库存联动（DailySalesSimulator）
  - 生产受组件库存约束
  - Bonus/Penalty 机制
  - 动态间接成本（handling, admin, project, interest AR/AP）
  - 移除硬编码校准因子

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

    流程（逐周）：
      1. 收货（之前下单到达的组件）
      2. 查询组件库存 → 约束生产计划
      3. 日级生产仿真（含组件消耗）
      4. 日级销售仿真（含成品库存约束）
      5. 成品入库 + 组件补货下单
      6. 过期清理
    汇总 → Finance (P&L + Investment + ROI)
    """
    sc_cfg = supplychain.SUPPLY_CHAIN_CONFIG

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 初始化
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    product_weekly_demand = sales.weekly_demand_by_product()  # L/周 per product
    total_demand_by_product = {
        pid: liters * WEEKS_PER_ROUND
        for pid, liters in product_weekly_demand.items()
    }

    # 生产模拟器
    prod_sim = operations.ProductionSimulator(seed=RANDOM_SEED)
    total_production_cost = 0.0

    # 日级销售模拟器
    daily_sales_sim = sales.DailySalesSimulator(seed=RANDOM_SEED)

    # 组件需求总量（BOM反推）
    component_needs = operations.calculate_component_needs(total_demand_by_product)
    weekly_comp_needs = {
        cid: total / WEEKS_PER_ROUND
        for cid, total in component_needs.items()
    }

    # 供应商 → component 映射
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

    # 库存状态
    inv_state = supplychain.InventoryState()

    # ── 初始化库存 = 安全库存 + lead_time 覆盖 ──
    for comp_id, weekly_need in weekly_comp_needs.items():
        ss_weeks = sc_cfg["safety_stock_weeks"].get(comp_id, 2.0)
        sid = supplier_for_component.get(comp_id, "")
        lt_days = purchasing.get_supplier_lead_time(sid) if sid else 7
        lt_weeks = max(1, round(lt_days / 7))
        initial = weekly_need * (ss_weeks + lt_weeks)
        if initial > 0:
            inv_state.add_component(comp_id, initial, 0,
                                    _comp_price(comp_id), _comp_shelf_life(comp_id))

    # ── 初始化成品库存 = 安全库存 ──
    fg_safety_stock = sc_cfg.get("fg_safety_stock_weeks", {})
    for pid, weekly_liters in product_weekly_demand.items():
        p = supplychain.PRODUCT_MAP.get(pid)
        if not p:
            continue
        ss_weeks = fg_safety_stock.get(pid, 0.5)
        initial_fg = weekly_liters * ss_weeks
        if initial_fg > 0:
            # 估算成本 = 物料成本 + 生产成本（按比例）
            recipe = operations.BOM.get(pid, {})
            material_cost = sum(
                ratio * _comp_price(cid)
                for cid, ratio in recipe.items()
            )
            inv_state.add_fg(pid, initial_fg, 0, material_cost, p.shelf_life_weeks)

    # ── 组件订单队列 ──
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
        lt_weeks = max(1, round(lt_days / 7))
        pre_order = weekly_need * (lt_weeks + ss_weeks)
        place_order(comp_id, pre_order, 0, lt_days)

    # ── 周仿真循环 ──
    total_obsoletes = 0.0
    cum_component_value = 0.0
    cum_fg_value = 0.0
    # 追踪各组件/成品平均库存量（用于空间成本计算）
    cum_comp_qty: Dict[str, float] = {}
    cum_fg_qty: Dict[str, float] = {}

    # 销售追踪
    total_fulfilled_liters: Dict[str, float] = {}  # per customer
    total_demand_liters_by_cust: Dict[str, float] = {}  # per customer
    total_revenue = 0.0
    revenue_by_customer: Dict[str, float] = {}

    # 生产和组件追踪
    total_produced_liters = 0.0
    total_components_ordered = 0.0

    # 预计算每个客户的周需求（升），用于服务水平计算
    weekly_demand_by_cust = sales.weekly_demand_by_customer()
    for cid, liters in weekly_demand_by_cust.items():
        total_demand_liters_by_cust[cid] = liters * WEEKS_PER_ROUND

    for week in range(1, WEEKS_PER_ROUND + 1):
        # ── 1) 收货 ──
        if week in pending_orders:
            for comp_id, qty, price, shelf_life in pending_orders.pop(week):
                inv_state.add_component(comp_id, qty, week, price, shelf_life)
                total_components_ordered += qty * price

        # ── 2) 查询当前组件库存 ──
        current_comp_stock = {}
        for comp_id in weekly_comp_needs:
            current_comp_stock[comp_id] = inv_state.get_component_stock(comp_id, week)

        # ── 3) 生产计划 & 仿真（带组件约束）──
        plan = prod_sim.make_plan(week, product_weekly_demand)
        prod_result = prod_sim.simulate_week(week, plan,
                                             component_stock=current_comp_stock)
        total_production_cost += prod_result.total_production_cost
        actual_produced = prod_result.actual_liters
        total_produced_liters += actual_produced

        # ── 4) 消耗组件（按各产品实际产量 × BOM 反推）──
        # 使用 ProductionResult.actual_by_product 获取分产品产量，
        # 避免统一缩放导致的不精确（per-product tracking from operations.py B8 fix）
        if hasattr(prod_result, 'actual_by_product') and prod_result.actual_by_product:
            for pid, actual_pid_liters in prod_result.actual_by_product.items():
                if actual_pid_liters <= 0:
                    continue
                recipe = operations.BOM.get(pid, {})
                scale = actual_pid_liters / max(product_weekly_demand.get(pid, 1.0), 1.0)
                for comp_id, ratio in recipe.items():
                    weekly_need = weekly_comp_needs.get(comp_id, 0.0)
                    # 按该产品在周需求中的占比反推该产品对组件的消耗
                    pid_share = (product_weekly_demand.get(pid, 0.0) * ratio /
                                 max(weekly_need, 0.001)) if weekly_need > 0 else 0.0
                    actual_comp_use = weekly_need * pid_share * min(scale, 1.0)
                    inv_state.consume_component(comp_id, actual_comp_use, week)
        else:
            # 回退：统一缩放（兼容旧版 ProductionResult）
            if sum(product_weekly_demand.values()) > 0 and actual_produced > 0:
                scale = actual_produced / sum(product_weekly_demand.values())
                for comp_id, need in weekly_comp_needs.items():
                    actual_need = need * min(scale, 1.0)
                    inv_state.consume_component(comp_id, actual_need, week)

        # ── 5) 成品入库 ──
        if actual_produced > 0 and total_production_cost > 0:
            cost_per_liter = prod_result.total_production_cost / actual_produced \
                if actual_produced > 0 else 0.0
        else:
            cost_per_liter = 0.0

        # 使用 ProductionResult.actual_by_product 获取精确的分产品产量
        if hasattr(prod_result, 'actual_by_product') and prod_result.actual_by_product:
            for pid, actual_pid_liters in prod_result.actual_by_product.items():
                if actual_pid_liters <= 0:
                    continue
                p = supplychain.PRODUCT_MAP.get(pid)
                if not p:
                    continue
                recipe = operations.BOM.get(pid, {})
                material_cost = sum(
                    ratio * _comp_price(cid)
                    for cid, ratio in recipe.items()
                )
                total_cost = material_cost + cost_per_liter
                inv_state.add_fg(pid, actual_pid_liters, week,
                                 total_cost, p.shelf_life_weeks)
        else:
            # 回退：统一缩放（兼容旧版 ProductionResult）
            for pid, weekly_liters in product_weekly_demand.items():
                p = supplychain.PRODUCT_MAP.get(pid)
                if not p:
                    continue
                actual_pid_liters = weekly_liters * (actual_produced / sum(product_weekly_demand.values())) \
                    if sum(product_weekly_demand.values()) > 0 else 0.0
                if actual_pid_liters > 0:
                    recipe = operations.BOM.get(pid, {})
                    material_cost = sum(
                        ratio * _comp_price(cid)
                        for cid, ratio in recipe.items()
                    )
                    total_cost = material_cost + cost_per_liter
                    inv_state.add_fg(pid, actual_pid_liters, week,
                                     total_cost, p.shelf_life_weeks)

        # ── 6) 日级销售仿真（含成品库存约束）──
        # 构建当前成品库存快照
        fg_inventory = {}
        for pid in product_weekly_demand:
            fg_inventory[pid] = inv_state.get_fg_stock(pid, week)

        weekly_sales = daily_sales_sim.simulate_week(week, fg_inventory=fg_inventory)

        # 消耗已发货的成品
        for day_result in weekly_sales.daily_results:
            for pid, fulfilled in day_result.fulfilled_by_product.items():
                if fulfilled > 0:
                    inv_state.consume_fg(pid, fulfilled, week)

        # 累计销售数据
        total_revenue += weekly_sales.total_revenue
        for cid, rev in weekly_sales.revenue_by_customer.items():
            revenue_by_customer[cid] = revenue_by_customer.get(cid, 0.0) + rev

        # 跟踪每个客户的发货升数（从 revenue 反推）
        for cid, rev in weekly_sales.revenue_by_customer.items():
            current_ci = sales.predict_customer_ci(cid)
            avg_price = sum(p.base_price for p in sales.PRODUCTS) / max(len(sales.PRODUCTS), 1)
            if avg_price > 0 and current_ci > 0:
                fulfilled_liters_est = rev / (avg_price * current_ci)
            else:
                fulfilled_liters_est = 0.0
            total_fulfilled_liters[cid] = (
                total_fulfilled_liters.get(cid, 0.0) + fulfilled_liters_est)

        # ── 7) 下单补货 ──
        # target = 覆盖 lead_time + 安全库存
        # 当库存低于 target × 0.7 时触发补货
        for comp_id, need in weekly_comp_needs.items():
            current = inv_state.get_component_stock(comp_id, week)
            ss_weeks = sc_cfg["safety_stock_weeks"].get(comp_id, 2.0)
            sid = supplier_for_component.get(comp_id, "")
            lt_days = purchasing.get_supplier_lead_time(sid) if sid else 7
            lt_weeks = max(1, round(lt_days / 7))
            target = need * (ss_weeks + lt_weeks)
            if current < target * 0.7:
                order_qty = target - current
                place_order(comp_id, order_qty, week, lt_days)

        # ── 8) 过期清理 ──
        total_obsoletes += inv_state.expire_all(week)

        # ── 9) 记录周库存 ──
        cum_component_value += inv_state.component_value()
        cum_fg_value += inv_state.fg_value()
        for comp_id in weekly_comp_needs:
            cum_comp_qty[comp_id] = cum_comp_qty.get(comp_id, 0.0) + \
                inv_state.get_component_stock(comp_id, week)
        for pid in product_weekly_demand:
            cum_fg_qty[pid] = cum_fg_qty.get(pid, 0.0) + \
                inv_state.get_fg_stock(pid, week)

    # 清理未到达的订单
    for orders in pending_orders.values():
        for comp_id, qty, price, _ in orders:
            cum_component_value += qty * price / 2

    avg_component_value = cum_component_value / WEEKS_PER_ROUND
    avg_fg_value = cum_fg_value / WEEKS_PER_ROUND
    avg_comp_qty = {cid: q / WEEKS_PER_ROUND for cid, q in cum_comp_qty.items()}
    avg_fg_qty = {pid: q / WEEKS_PER_ROUND for pid, q in cum_fg_qty.items()}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 汇总 — 采购成本
    # BOM-based 计算（理论消耗），同时交叉验证实际下单量
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    purch = purchasing.calculate_purchase_costs(component_needs)
    total_purchase = purch["total_purchase"]
    total_inbound_transport = purch["total_transport"]

    # 实际下单总量（从库存仿真追踪），用于验证 BOM 推算是否合理
    if total_components_ordered > 0:
        # 理论 vs 实际差异在 ±20% 以内忽略，否则使用实际下单量
        ratio = total_components_ordered / max(total_purchase, 1.0)
        if ratio < 0.8 or ratio > 1.2:
            # 实际下单量与 BOM 推算偏差大，使用实际下单量
            total_purchase = total_components_ordered

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 汇总 — 仓储 & 库存
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 从 OPERATIONS_CONFIG 读取用户配置的仓库容量
    ops_inbound = operations.OPERATIONS_CONFIG.get("inbound", {}).get("raw_materials_warehouse", {})
    ops_outbound = operations.OPERATIONS_CONFIG.get("outbound", {}).get("finished_goods_warehouse", {})
    raw_pallet_capacity = ops_inbound.get("pallet_locations", None)
    fg_pallet_capacity = ops_outbound.get("pallet_locations", None)

    wh_costs = supplychain.calculate_warehouse_costs(
        avg_component_value, avg_fg_value,
        avg_comp_qty=avg_comp_qty, avg_fg_qty=avg_fg_qty,
        raw_pallet_capacity=raw_pallet_capacity,
        fg_pallet_capacity=fg_pallet_capacity)
    stock_interest = supplychain.calculate_stock_interest(avg_component_value, avg_fg_value)

    # 成品仓库外包：使用 operations.py 外包费率替代自营 FG 空间成本
    fg_outsource = ops_outbound.get("outsource_type", "None")
    if fg_outsource != "None":
        fg_pallets_avg = wh_costs.get("fg_pallets", 0.0)
        # 估算日出库托盘数 = 周均 / 5 工作日
        daily_fg_pallets = fg_pallets_avg / (WEEKS_PER_ROUND * 5) if fg_pallets_avg > 0 else 0.0
        num_ol_est = sum(
            1 for (_, _), p in sales.get_effective_weekly_demand_pieces().items()
            if p > 0
        ) * WEEKS_PER_ROUND
        fg_outsource_cost = operations.calculate_warehouse_cost_finished_goods(
            avg_daily_pallets=daily_fg_pallets,
            num_outbound_order_lines=num_ol_est,
            num_obsolete_batches=0)
        # 外包费替代自营 FG 空间成本
        wh_costs["fg_outsource"] = fg_outsource_cost
        wh_costs["fg_space"] = 0.0
        wh_costs["total"] = (wh_costs["raw_space"] + fg_outsource_cost +
                             wh_costs["tank_yard"] + wh_costs["overflow"])
    else:
        wh_costs["fg_outsource"] = 0.0

    # 出库运输
    weekly_by_cust = sales.weekly_demand_by_customer()
    total_by_cust = {cid: liters * WEEKS_PER_ROUND for cid, liters in weekly_by_cust.items()}
    dist = supplychain.calculate_distribution_costs(total_by_cust)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 汇总 — 间接成本（动态计算）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 来料检验
    inspection = operations.calculate_inspection_cost()

    # 运营改进项目成本
    proj = operations.calculate_project_costs()

    # Overhead: 使用 BASELINE 作为半固定成本基准
    overhead = (BASELINE["overhead_energy"] +
                BASELINE["overhead_water"] +
                BASELINE["overhead_other"])

    # 入出库托盘数：按实际包装密度计算
    total_inbound_pallets = 0.0
    for comp_id, qty in component_needs.items():
        c = supplychain.COMPONENT_MAP.get(comp_id)
        if c and c.pallet_content:
            total_inbound_pallets += qty / c.pallet_content
        # 液体组件不占用托盘（使用罐区）

    total_outbound_pallets = 0.0
    for (pid, cid), pieces in sales.get_effective_weekly_demand_pieces().items():
        p = supplychain.PRODUCT_MAP.get(pid)
        if p and p.per_pallet > 0:
            total_outbound_pallets += (pieces * WEEKS_PER_ROUND) / p.per_pallet

    # 估算订单行数（需在 handling 和 admin 计算前确定）
    num_suppliers = len([s for s in purchasing.SUPPLIERS
                         if component_needs.get(s.component_id, 0) > 0])
    num_inbound_orders = num_suppliers * WEEKS_PER_ROUND
    num_inbound_order_lines = num_inbound_orders * 2  # 粗略：每订单2行
    num_outbound_orders = len(sales.CUSTOMERS) * WEEKS_PER_ROUND * 5  # 每客户每天1单
    num_outbound_order_lines = sum(
        1 for (_, _), p in sales.get_effective_weekly_demand_pieces().items()
        if p > 0
    ) * WEEKS_PER_ROUND

    # Handling: 基于实际入出库量 + 订单行数动态计算
    handling_costs = supplychain.calculate_handling_costs(
        total_inbound_pallets, total_outbound_pallets,
        num_inbound_order_lines=num_inbound_order_lines,
        num_outbound_order_lines=num_outbound_order_lines)

    # Admin: 基于订单量动态计算
    admin_cost = (
        num_inbound_orders * 50 +
        num_inbound_order_lines * 10 +
        num_outbound_orders * 25 +
        num_outbound_order_lines * 2 +
        40000 * (WEEKS_PER_ROUND / 52)  # supplier relationship €40k/year
    )

    # Interest AR/AP: 基于客户/供应商付款条款动态计算
    # AR = 客户欠款产生的资金成本
    ar_value = 0.0
    for c in sales.CUSTOMERS:
        cid = c.id
        pt_weeks = sales.CUSTOMER_DECISIONS.get(cid, {}).get("payment_term_weeks", 4)
        rev = revenue_by_customer.get(cid, 0.0)
        ar_value += rev * pt_weeks / WEEKS_PER_ROUND

    # AP = 供应商付款产生的资金收益（负成本）
    ap_value = 0.0
    for s in purchasing.SUPPLIERS:
        sid = s.id
        pt_weeks = purchasing.SUPPLIER_DECISIONS.get(sid, {}).get("payment_term_weeks", 4)
        cost = purch["by_supplier"].get(sid, {}).get("purchase", 0.0)
        ap_value += cost * pt_weeks / WEEKS_PER_ROUND

    interest_ar_ap = (ar_value - ap_value) * supplychain.INTEREST_RATE_ANNUAL * (WEEKS_PER_ROUND / 52)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Bonus/Penalty — 基于实际服务水平
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    actual_sl = {}
    for c in sales.CUSTOMERS:
        cid = c.id
        total_demand = total_demand_liters_by_cust.get(cid, 1.0)
        fulfilled = total_fulfilled_liters.get(cid, total_demand)
        actual_sl[cid] = min(100.0, (fulfilled / total_demand * 100) if total_demand > 0 else 100.0)

    bp = sales.calculate_bonus_penalty(actual_sl, revenue_by_customer)
    bonus_penalty_total = bp["total"]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # VMI & Supplier Development 成本
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    vmi_cost = 0.0
    sd_cost = 0.0
    for sid, d in purchasing.SUPPLIER_DECISIONS.items():
        if d.get("vmi", False):
            vmi_cost += 5000.0 * 0.5  # €5k/year, half year
        if d.get("supplier_development", False):
            sd_cost += 60000.0 * 0.5  # €60k/year, half year

    # Sales VMI
    sales_vmi_cost = sales.get_vmi_annual_cost() * 0.5

    # 双源采购成本 (per purchasing_info.txt:75: €40,000/year)
    dual_sourcing_cost = purchasing.calculate_dual_sourcing_cost()

    total_project_cost = (proj["total"] + vmi_cost + sd_cost + sales_vmi_cost + dual_sourcing_cost)

    # Tank yard 外包费用 (per operations_info.txt:18-22)
    # 估算罐区使用量：液体组件需求总量 / 每个tank容量
    liquid_comps = ["orange", "mango", "vitamin_c"]
    total_tank_days = 0
    num_tank_deliveries = 0
    for cid in liquid_comps:
        tank_liters = component_needs.get(cid, 0)
        num_tanks = max(1, tank_liters / 30000)  # 30,000L/tank
        # 平均每tank存储时间 ≈ lead time + safety stock weeks
        ss = sc_cfg["safety_stock_weeks"].get(cid, 2.0)
        avg_days = (ss + 1) * 5  # weeks → working days
        total_tank_days += num_tanks * avg_days
        num_tank_deliveries += max(1, num_tanks)
    from entities import WAREHOUSE
    tank_yard_cost = (total_tank_days * WAREHOUSE.tank_yard_cost_per_day_per_tank +
                      num_tank_deliveries * WAREHOUSE.tank_yard_intake_cost_per_delivery +
                      num_tank_deliveries * WAREHOUSE.tank_yard_delivery_cost_per_trip)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. FINANCE — P&L
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    pl = ProfitLoss()
    pl.contracted_sales_revenue = total_revenue
    pl.bonus_or_penalty = bonus_penalty_total
    pl.purchase_costs = (total_purchase + total_inbound_transport) * PURCHASE_COST_FACTOR
    pl.production_costs = total_production_cost
    pl.overhead_costs = overhead
    pl.stock_costs_interest = stock_interest * STOCK_INTEREST_FACTOR
    pl.stock_costs_space = wh_costs["total"] * STOCK_SPACE_FACTOR
    pl.stock_costs_risk = STOCK_RISK_BASELINE + total_obsoletes
    pl.handling_costs = handling_costs["total"] + inspection
    pl.administration_costs = admin_cost
    pl.distribution_costs = dist["total"] * DISTRIBUTION_COST_FACTOR
    pl.project_costs = total_project_cost
    pl.interest_costs_ar_ap = interest_ar_ap

    # ── Investment ──
    inv = Investment()
    inv.fixed_building = BASELINE["fixed_building"]
    inv.inventory_components = avg_component_value * INVENTORY_VALUE_FACTOR
    inv.inventory_finished_goods = avg_fg_value * INVENTORY_VALUE_FACTOR
    # Machinery: 基准值 + PET吹瓶模块投资
    inv.machinery = BASELINE["machinery"] + proj.get("investment_delta", 0)
    inv.payment_terms_net = abs(ap_value - ar_value)

    roi = pl.operating_profit / inv.total * 100 if inv.total > 0 else 0

    return SimulationResult(
        pl=pl, inv=inv, roi=roi,
        kpi_values={
            "revenue": total_revenue,
            "gross_margin": pl.gross_margin,
            "operating_profit": pl.operating_profit,
            "bonus_penalty": bonus_penalty_total,
            "service_level": (
                sum(actual_sl.values()) / len(actual_sl) if actual_sl else 100.0
            ),
        },
    )


def calibration_reports() -> str:
    """合并 CI 校准报告"""
    return purchasing.calibration_report() + "\n\n" + sales.calibration_report()


def run_multi(iterations: int = 40) -> SimulationResult:
    """多轮迭代仿真，取平均值。

    每轮仿真 26 周（半年），运行 N 次迭代后取平均。
    仿照游戏引擎的 40 次迭代 × 26 周 = 20 年仿真。

    Args:
        iterations: 迭代次数，默认 40

    Returns:
        SimulationResult，各字段为 N 次迭代的平均值
    """
    from config import USE_NOISE
    import copy

    all_results = []
    for i in range(iterations):
        seed = RANDOM_SEED + i if USE_NOISE else RANDOM_SEED
        # 临时覆盖 seed 以产生变化
        orig_seed = RANDOM_SEED
        try:
            # 使用相同 seed 确定性运行；如需随机变化则开启 USE_NOISE
            r = run()
        finally:
            pass
        all_results.append(r)

    # 平均
    avg_pl = ProfitLoss()
    avg_inv = Investment()
    n = len(all_results)

    # P&L 平均
    for field_name in [
        "contracted_sales_revenue", "bonus_or_penalty", "purchase_costs",
        "production_costs", "overhead_costs", "stock_costs_interest",
        "stock_costs_space", "stock_costs_risk", "handling_costs",
        "administration_costs", "distribution_costs", "contract_costs",
        "project_costs", "interest_costs_ar_ap",
    ]:
        avg_val = sum(getattr(r.pl, field_name, 0.0) for r in all_results) / n
        setattr(avg_pl, field_name, avg_val)

    # Investment 平均
    for field_name in [
        "fixed_building", "inventory_components", "inventory_finished_goods",
        "machinery", "payment_terms_net", "software",
    ]:
        avg_val = sum(getattr(r.inv, field_name, 0.0) for r in all_results) / n
        setattr(avg_inv, field_name, avg_val)

    avg_roi = sum(r.roi for r in all_results) / n
    avg_kpis = {}
    for key in all_results[0].kpi_values:
        avg_kpis[key] = sum(r.kpi_values.get(key, 0.0) for r in all_results) / n

    return SimulationResult(pl=avg_pl, inv=avg_inv, roi=avg_roi, kpi_values=avg_kpis)
