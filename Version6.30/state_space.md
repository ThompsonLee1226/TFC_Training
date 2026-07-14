# TFC仿真 — 状态空间定义文档

> **版本**: v1.0 | **日期**: 2026-07-14
> **用途**: MARL Gymnasium 环境的 `observation_space` 设计参考
> **配套代码**: `state_space.py`（含 `StateSpaceConfig` 类和状态提取函数）

---

## 目录

1. [第一部分：状态变量总览表](#第一部分状态变量总览表)
2. [第二部分：按智能体分组的局部观测](#第二部分按智能体分组的局部观测)
3. [第三部分：全局状态（Centralized Critic）](#第三部分全局状态centralized-critic)
4. [第四部分：状态归一化建议](#第四部分状态归一化建议)
5. [第五部分：与动作空间的对应关系](#第五部分与动作空间的对应关系)
6. [附录：代码集成指南](#附录代码集成指南)

---

## 第一部分：状态变量总览表

### 1.1 组件库存状态（supplychain.py → InventoryState）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `comp_stock_pack_1l` | float | 标量 | [0, ∞) L | supplychain | 每周 | pack_1l 当前有效库存量 (L) |
| `comp_stock_pet` | float | 标量 | [0, ∞) pieces | supplychain | 每周 | PET 瓶当前有效库存量 (pieces) |
| `comp_stock_orange` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange 浓缩液当前有效库存量 (L) |
| `comp_stock_mango` | float | 标量 | [0, ∞) L | supplychain | 每周 | Mango 浓缩液当前有效库存量 (L) |
| `comp_stock_vitamin_c` | float | 标量 | [0, ∞) L | supplychain | 每周 | Vitamin C 当前有效库存量 (L) |
| `comp_on_order_pack_1l` | float | 标量 | [0, ∞) L | supplychain → pending_orders | 每周 | pack_1l 已下单未到达量 |
| `comp_on_order_pet` | float | 标量 | [0, ∞) pieces | supplychain → pending_orders | 每周 | PET 已下单未到达量 |
| `comp_on_order_orange` | float | 标量 | [0, ∞) L | supplychain → pending_orders | 每周 | Orange 已下单未到达量 |
| `comp_on_order_mango` | float | 标量 | [0, ∞) L | supplychain → pending_orders | 每周 | Mango 已下单未到达量 |
| `comp_on_order_vitamin_c` | float | 标量 | [0, ∞) L | supplychain → pending_orders | 每周 | Vitamin C 已下单未到达量 |
| `comp_batch_count` | int | 5维 | [0, ∞) | supplychain → InventoryState | 每周 | 各组件库存批次数（FIFO追踪用） |
| `comp_oldest_week` | int | 5维 | [0, 26] | supplychain → StockBatch | 每周 | 各组件最老批次的生产周（判断临期风险） |
| `comp_value_total` | float | 标量 | [0, ∞) € | supplychain → InventoryState.component_value() | 每周 | 组件库存总价值（成本计价） |

### 1.2 成品库存状态（supplychain.py → InventoryState）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `fg_stock_p_orange_1l` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange 1L 成品库存 (L) |
| `fg_stock_p_ocp_1l` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange/C-power 1L 成品库存 (L) |
| `fg_stock_p_om_1l` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange/Mango 1L 成品库存 (L) |
| `fg_stock_p_orange_pet` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange PET 成品库存 (L) |
| `fg_stock_p_ocp_pet` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange/C-power PET 成品库存 (L) |
| `fg_stock_p_om_pet` | float | 标量 | [0, ∞) L | supplychain | 每周 | Orange/Mango PET 成品库存 (L) |
| `fg_oldest_week` | int | 6维 | [0, 26] | supplychain → StockBatch | 每周 | 各成品最老批次生产周（判断临期风险） |
| `fg_value_total` | float | 标量 | [0, ∞) € | supplychain → InventoryState.fg_value() | 每周 | 成品库存总价值（成本计价） |
| `fg_shelf_life_remaining_min` | int | 6维 | [0, 20]周 | supplychain → StockBatch.expiry_week | 每周 | 各成品剩余保质期最小值 |

### 1.3 供应商状态（purchasing.py + entities.py）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `supplier_effective_price_{sid}` | float | 5维 | [0.02, 1.0] €/L | purchasing → get_effective_purchase_price() | 每轮（决策后） | 各供应商有效采购单价 = base_price × CI |
| `supplier_lead_time_{sid}` | int | 5维 | {10, 15, 20, 30}天 | entities → Supplier.lead_time_days | 静态（可能随决策变化） | 各供应商交货提前期 |
| `supplier_ci_{sid}` | float | 5维 | [0.85, 1.20] | purchasing → predict_supplier_ci() | 每轮 | 各供应商 Contract Index |
| `supplier_quality_{sid}` | categorical | 5维 | {High, Middle, Poor} | purchasing → SUPPLIER_DECISIONS | 每轮 | 各供应商原材料质量等级 |
| `supplier_reliability_{sid}` | float | 5维 | [85.0, 99.0]% | purchasing → SUPPLIER_DECISIONS | 每轮 | 各供应商承诺交货可靠性 |
| `supplier_delivery_window_{sid}` | categorical | 5维 | {4 hours, 1 day, 2 days, 1 week} | purchasing → SUPPLIER_DECISIONS | 每轮 | 各供应商交货窗口 |
| `supplier_payment_term_{sid}` | int | 5维 | [1, 8]周 | purchasing → SUPPLIER_DECISIONS | 每轮 | 各供应商付款周期 |
| `supplier_trade_unit_{sid}` | categorical | 5维 | {Pallet, FTL, Tank, IBC, Drum} | purchasing → SUPPLIER_DECISIONS | 每轮 | 各供应商贸易单位 |
| `supplier_vmi_{sid}` | bool | 5维 | {0, 1} | purchasing → SUPPLIER_DECISIONS | 每轮 | VMI 开关 |
| `supplier_development_{sid}` | bool | 5维 | {0, 1} | purchasing → SUPPLIER_DECISIONS | 每轮 | 供应商发展项目开关 |
| `supplier_free_capacity_{sid}` | float | 5维 | [0, 50]% | entities → Supplier.free_capacity_pct | 静态 | 各供应商剩余产能比例 |
| `supplier_distance_{sid}` | int | 5维 | {500, 1800, 7500} km | entities → Supplier.distance_km | 静态 | 各供应商到荷兰的距离 |
| `supplier_base_price_{sid}` | float | 5维 | [0.03, 0.90] € | entities → Supplier.base_price | 静态 | 各供应商基础采购价 |

### 1.4 客户状态（sales.py + entities.py）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `customer_ci_{cid}` | float | 3维 | [0.70, 1.07] | sales → predict_customer_ci() | 每轮 | 各客户 Contract Index |
| `customer_weekly_demand_{cid}` | float | 3维 | [0, 120000] L/周 | sales → weekly_demand_by_customer() | 每轮（促销变化时） | 各客户周需求总量 (L) |
| `customer_service_level_pct_{cid}` | float | 3维 | [90.0, 99.5]% | sales → CUSTOMER_DECISIONS | 每轮 | 各客户承诺服务水平 |
| `customer_shelf_life_pct_{cid}` | float | 3维 | [40.0, 85.0]% | sales → CUSTOMER_DECISIONS | 每轮 | 各客户要求保质期百分比 |
| `customer_payment_term_{cid}` | int | 3维 | [1, 8]周 | sales → CUSTOMER_DECISIONS | 每轮 | 各客户付款周期 |
| `customer_promo_pressure_{cid}` | categorical | 3维 | {None, Low, Middle, Heavy} | sales → CUSTOMER_DECISIONS | 每轮 | 各客户促销压力等级 |
| `customer_promo_horizon_{cid}` | categorical | 3维 | {Short, Middle, Long} | sales → CUSTOMER_DECISIONS | 每轮 | 各客户促销时间范围 |
| `customer_order_deadline_{cid}` | categorical | 3维 | {12:00, 14:00, 17:00, 20:00} | sales → CUSTOMER_DECISIONS | 每轮 | 各客户订单截止时间 |
| `customer_trade_unit_{cid}` | categorical | 3维 | {Box, Pallet layer, Pallet} | sales → CUSTOMER_DECISIONS | 每轮 | 各客户贸易单位 |
| `customer_vmi_{cid}` | bool | 3维 | {0, 1} | sales → CUSTOMER_DECISIONS | 每轮 | VMI 开关 |

### 1.5 销售运行时状态（sales.py → DailySalesSimulator & simulation.py）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `actual_service_level_{cid}` | float | 3维 | [0, 100]% | simulation → actual_sl | 每周累计 | 各客户实际服务水平（累计 fulfilled/demand） |
| `cumulative_shortfall_{cid}` | float | 3维 | [0, ∞) L | simulation → total_shortfall | 每周累计 | 各客户累计缺货量 (L) |
| `weekly_revenue_{cid}` | float | 3维 | [0, 200000] € | simulation → revenue_by_customer | 每周 | 各客户本周收入 |
| `total_revenue` | float | 标量 | [0, 4000000] € | simulation → total_revenue | 每周累计 | 累计总销售收入 |
| `bonus_penalty_total` | float | 标量 | [-50000, 20000] € | simulation → bonus_penalty_total | 每轮汇总 | 服务水平 bonus/penalty |
| `daily_service_level_avg` | float | 标量 | [0, 1] | sales → DailySalesResult | 每天 | 本周日均服务水平 |
| `demand_liters_weekly_total` | float | 标量 | [0, 150000] L | sales → WeeklySalesResult | 每周 | 本周总需求量 |
| `fulfilled_liters_weekly_total` | float | 标量 | [0, 150000] L | sales → WeeklySalesResult | 每周 | 本周总发货量 |

### 1.6 生产状态（operations.py → ProductionSimulator）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `mixer_utilization` | float | 标量 | [0, 1] | operations → mixing_hours / available_hours | 每周 | 混合器时间利用率 |
| `bottling_utilization` | float | 标量 | [0, 1.5] | operations → bottling_hours / available_hours | 每周 | 灌装线时间利用率（>1=加班） |
| `breakdown_hours_weekly` | float | 标量 | [0, 20] h | operations → DailyResult.breakdown_hours | 每周 | 本周故障停机总小时 |
| `changeover_hours_weekly` | float | 标量 | [0, 30] h | operations → DailyResult.changeover_hours | 每周 | 本周换型总小时 |
| `actual_production_liters` | float | 标量 | [0, 200000] L | operations → ProductionResult.actual_liters | 每周 | 本周实际产量 (L) |
| `planned_production_liters` | float | 标量 | [0, 200000] L | operations → ProductionResult.planned_liters | 每周 | 本周计划产量 (L) |
| `shortfall_liters_weekly` | float | 标量 | [0, 50000] L | operations → ProductionResult.shortfall_liters | 每周 | 本周产能缺口 (L) |
| `startup_loss_liters_weekly` | float | 标量 | [0, 5000] L | operations → ProductionResult.startup_loss_liters | 每周 | 本周启动产能损失 (L) |
| `overtime_hours_weekly` | float | 标量 | [0, 16] h | operations → max_overtime_hours | 每周 | 本周加班小时数 |
| `outsourced_liters_weekly` | float | 标量 | [0, 50000] L | operations → ProductionResult.outsourced_liters | 每周 | 本周外包生产量（仅当需求>168h/周上限） |
| `num_changeovers_weekly` | int | 标量 | [0, 30] | operations → DailyResult.num_changeovers | 每周 | 本周换型总次数 |
| `actual_by_product_{pid}` | float | 6维 | [0, 80000] L | operations → ProductionResult.actual_by_product | 每周 | 各产品本周实际产量 |

### 1.7 生产配置状态（operations.py → OPERATIONS_CONFIG）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `mixer_type` | categorical | 标量 | {Fruitmix MQ, MegaChurn 20, FMM 4000} | operations → mixing | 每轮 | 当前混合器型号 |
| `bottling_line_type` | categorical | 标量 | {Swiss Fill 2, TopSpeed 1, MultiFlex 1, Swiss Fill 1} | operations → bottling | 每轮 | 当前灌装线型号 |
| `shifts_per_week` | int | 标量 | [1, 5] | operations → bottling | 每轮 | 班次数 |
| `smed_enabled` | bool | 标量 | {0, 1} | operations → bottling | 每轮 | SMED（缩短换型50%） |
| `increase_speed` | bool | 标量 | {0, 1} | operations → bottling | 每轮 | 提速10% |
| `preventive_maintenance` | categorical | 标量 | {None, A little, A lot} | operations → bottling | 每轮 | 预防维护等级 |
| `solve_breakdowns_training` | bool | 标量 | {0, 1} | operations → bottling | 每轮 | 故障培训 |
| `max_overtime_hours` | int | 标量 | [0, 40] h | operations → bottling | 每轮 | 最大加班小时 |
| `inflate_pet_bottles` | bool | 标量 | {0, 1} | operations → bottling | 每轮 | PET吹瓶模块 |
| `raw_pallet_capacity` | int | 标量 | [0, 2000] 位 | operations → inbound | 每轮 | 原料仓库托盘位容量 |
| `raw_permanent_employees` | int | 标量 | [1, 10] 人 | operations → inbound | 每轮 | 原料仓库永久员工数 |
| `fg_pallet_capacity` | int | 标量 | [0, 3000] 位 | operations → outbound | 每轮 | 成品仓库托盘位容量 |
| `fg_permanent_employees` | int | 标量 | [1, 10] 人 | operations → outbound | 每轮 | 成品仓库永久员工数 |
| `fg_outsource_type` | categorical | 标量 | {None, Conventional, Automated, MCC} | operations → outbound | 每轮 | 成品仓库外包类型 |
| `inspection_enabled_{sid}` | bool | 5维 | {0, 1} | operations → inbound | 每轮 | 来料检验（per supplier） |

### 1.8 财务状态（finance.py → ProfitLoss + Investment）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `cum_revenue` | float | 标量 | [0, 4000000] € | finance → ProfitLoss.total_revenue | 每轮 | 累计销售收入（含bonus/penalty） |
| `cum_cogs` | float | 标量 | [0, 2500000] € | finance → ProfitLoss.cogs | 每轮 | 累计COGS（采购+生产） |
| `cum_gross_margin` | float | 标量 | [-500000, 2000000] € | finance → ProfitLoss.gross_margin | 每轮 | 累计毛利 |
| `cum_indirect_costs` | float | 标量 | [0, 2000000] € | finance → ProfitLoss.indirect_costs | 每轮 | 累计间接成本 |
| `cum_operating_profit` | float | 标量 | [-500000, 1000000] € | finance → ProfitLoss.operating_profit | 每轮 | 累计营业利润 |
| `current_roi` | float | 标量 | [-10, 30]% | finance → calculate_roi() | 每轮 | 当前 ROI |
| `inventory_value_components` | float | 标量 | [0, 500000] € | finance → Investment.inventory_components | 每轮 | 组件库存价值（投资项） |
| `inventory_value_fg` | float | 标量 | [0, 500000] € | finance → Investment.inventory_finished_goods | 每轮 | 成品库存价值（投资项） |
| `payment_terms_net` | float | 标量 | [-200000, 400000] € | finance → Investment.payment_terms_net | 每轮 | 应付-应收净额（投资项） |
| `total_investment` | float | 标量 | [3000000, 6000000] € | finance → Investment.total | 每轮 | 总投资额 |

### 1.9 库存成本中间状态（supplychain.py + simulation.py）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `warehouse_raw_space_cost` | float | 标量 | [0, 150000] € | supplychain → calculate_warehouse_costs | 每轮 | 原料仓库空间成本 |
| `warehouse_fg_space_cost` | float | 标量 | [0, 200000] € | supplychain → calculate_warehouse_costs | 每轮 | 成品仓库空间成本 |
| `warehouse_overflow_cost` | float | 标量 | [0, 100000] € | supplychain → calculate_warehouse_costs | 每轮 | 溢出仓库成本 |
| `stock_interest_cost` | float | 标量 | [0, 100000] € | supplychain → calculate_stock_interest | 每轮 | 库存资金利息 |
| `cum_obsoletes_value` | float | 标量 | [0, 200000] € | simulation → total_obsoletes | 每周累计 | 累计过期报废价值 |
| `avg_component_value` | float | 标量 | [0, 500000] € | simulation → avg_component_value | 每轮 | 组件平均库存价值 |
| `avg_fg_value` | float | 标量 | [0, 500000] € | simulation → avg_fg_value | 每轮 | 成品平均库存价值 |
| `distribution_cost` | float | 标量 | [0, 300000] € | supplychain → calculate_distribution_costs | 每轮 | 出库运输成本 |
| `inbound_transport_cost` | float | 标量 | [0, 100000] € | purchasing → calculate_inbound_transport | 每轮 | 入库运输成本 |

### 1.10 供应链配置状态（supplychain.py → SUPPLY_CHAIN_CONFIG）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `safety_stock_weeks_{comp_id}` | float | 5维 | [0.0, 6.0]周 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 各组件安全库存周数 |
| `lot_size_weeks_{comp_id}` | int | 5维 | [1, 8]周 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 各组件补货批量周数 |
| `fg_safety_stock_weeks_{pid}` | float | 6维 | [0.0, 6.0]周 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 各成品安全库存周数 |
| `fg_production_interval_{pid}` | int | 6维 | [1, 14]天 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 各成品生产间隔 |
| `frozen_period_weeks` | int | 标量 | [0, 6]周 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 生产计划冻结期 |
| `production_interval_weeks` | int | 标量 | [1, 4]周 | supplychain → SUPPLY_CHAIN_CONFIG | 每轮 | 生产计划间隔 |

### 1.11 仿真元状态（simulation.py + config.py）

| 变量名 | 数据类型 | 维度/形状 | 取值范围 | 来源模块 | 更新频率 | 描述 |
|--------|----------|-----------|----------|----------|----------|------|
| `current_week` | int | 标量 | [1, 26] | simulation → week loop | 每周 | 当前仿真周次 |
| `weeks_remaining` | int | 标量 | [0, 26] | 计算: 26 - week | 每周 | 剩余周数 |
| `round_progress` | float | 标量 | [0, 1] | 计算: week/26 | 每周 | 仿真进度比例 |
| `use_noise` | bool | 标量 | {0, 1} | config → USE_NOISE | 静态 | 噪声开关 |
| `random_seed` | int | 标量 | [0, 2^31] | config → RANDOM_SEED | 静态 | 随机种子 |

---

## 第二部分：按智能体分组的局部观测

### 2.1 Purchasing Agent 局部观测（65维）

Purchasing Agent 负责5个供应商的SLA参数决策和双源采购决策，其观测应聚焦于供应商状态和组件库存。

| 维度索引 | 变量名 | 维数 | 描述 |
|----------|--------|------|------|
| 0-4 | `supplier_effective_price_{sid}` | 5 | 各供应商有效采购价 (normalized) |
| 5-9 | `supplier_lead_time_days_{sid}` | 5 | 各供应商提前期 (normalized) |
| 10-14 | `supplier_ci_{sid}` | 5 | 各供应商 Contract Index (normalized) |
| 15-19 | `supplier_quality_encoded_{sid}` | 5 | 质量等级编码 (High=0, Middle=1, Poor=2) |
| 20-24 | `supplier_reliability_{sid}` | 5 | 交货可靠性 (normalized) |
| 25-29 | `comp_stock_{comp_id}` | 5 | 各组件当前库存量 (normalized) |
| 30-34 | `comp_on_order_{comp_id}` | 5 | 各组件在途量 (normalized) |
| 35-39 | `supplier_payment_term_{sid}` | 5 | 各供应商当前付款周期 (normalized) |
| 40-44 | `supplier_vmi_{sid}` | 5 | 各供应商 VMI 开关 (bool) |
| 45-49 | `supplier_development_{sid}` | 5 | 各供应商发展项目开关 (bool) |
| 50-54 | `cum_financial` | 5 | 累计财务指标 (revenue/margin/profit/indirect/ROI) |
| 55-59 | `safety_stock_weeks_{comp_id}` | 5 | 各组件安全库存周数 (normalized) |
| 60-64 | `lot_size_weeks_{comp_id}` | 5 | 各组件补货批量周数 (normalized) |

### 2.2 Sales Agent 局部观测（34维）

Sales Agent 负责3个客户的SLA参数决策，其观测应聚焦于客户状态和成品库存。

| 维度索引 | 变量名 | 维数 | 描述 |
|----------|--------|------|------|
| 0-2 | `customer_ci_{cid}` | 3 | 各客户 Contract Index (normalized) |
| 3-5 | `customer_weekly_demand_{cid}` | 3 | 各客户周需求 (normalized) |
| 6-8 | `customer_service_level_pct_{cid}` | 3 | 各客户承诺服务水平 (normalized) |
| 9-11 | `customer_shelf_life_pct_{cid}` | 3 | 各客户保质期要求 (normalized) |
| 12-14 | `customer_payment_term_{cid}` | 3 | 各客户付款周期 (normalized) |
| 15-17 | `customer_promo_encoded_{cid}` | 3 | 促销压力编码 |
| 18-23 | `fg_stock_{pid}` | 6 | 各成品当前库存量 (normalized) |
| 24-26 | `actual_service_level_{cid}` | 3 | 各客户实际服务水平 (normalized) |
| 27-29 | `cumulative_shortfall_{cid}` | 3 | 各客户累计缺货 (normalized) |
| 30-32 | `weekly_revenue_{cid}` | 3 | 各客户本周收入 (normalized) |
| 33 | `current_week` | 1 | 当前周次 (normalized) |

### 2.3 Operations Agent 局部观测（27维）

Operations Agent 负责生产设备选择、班次安排和仓库配置，其观测应聚焦于生产能力和需求。

| 维度索引 | 变量名 | 维数 | 描述 |
|----------|--------|------|------|
| 0 | `mixer_type_encoded` | 1 | 混合器型号编码 (Fruitmix=0, MegaChurn=1, FMM=2) |
| 1 | `bottling_line_encoded` | 1 | 灌装线型号编码 |
| 2 | `shifts_per_week` | 1 | 班次数 (normalized) |
| 3 | `smed_enabled` | 1 | SMED开关 (bool) |
| 4 | `increase_speed` | 1 | 提速开关 (bool) |
| 5 | `preventive_maintenance_encoded` | 1 | 维护等级编码 |
| 6 | `breakdown_training` | 1 | 故障培训 (bool) |
| 7 | `mixer_utilization` | 1 | 混合器利用率 (normalized) |
| 8 | `bottling_utilization` | 1 | 灌装线利用率 (normalized) |
| 9 | `breakdown_rate` | 1 | 故障率 (normalized) |
| 10 | `changeover_ratio` | 1 | 换型时间占比 (normalized) |
| 11 | `overtime_ratio` | 1 | 加班占比 (normalized) |
| 12 | `waste_rate` | 1 | 废品率 (normalized) |
| 13-18 | `product_weekly_demand_{pid}` | 6 | 各产品周需求 (normalized) |
| 19-23 | `comp_stock_{comp_id}` | 5 | 各组件库存 (normalized) |
| 24 | `current_week` | 1 | 当前周次 (normalized) |
| 25 | `weeks_remaining` | 1 | 剩余周数 (normalized) |
| 26 | `round_progress` | 1 | 进度比例 |

### 2.4 SupplyChain Agent 局部观测（42维）

SupplyChain Agent 负责安全库存、批量和生产间隔参数，其观测应聚焦于库存和仓储成本。

| 维度索引 | 变量名 | 维数 | 描述 |
|----------|--------|------|------|
| 0-4 | `comp_stock_{comp_id}` | 5 | 各组件库存量 (normalized) |
| 5-9 | `comp_on_order_{comp_id}` | 5 | 各组件在途量 (normalized) |
| 10-14 | `comp_oldest_week_{comp_id}` | 5 | 各组件最老批次周龄 (normalized) |
| 15-20 | `fg_stock_{pid}` | 6 | 各成品库存量 (normalized) |
| 21 | `warehouse_space_cost` | 1 | 仓储空间成本 (normalized) |
| 22 | `stock_interest_cost` | 1 | 库存利息 (normalized) |
| 23 | `cum_obsoletes_value` | 1 | 累计过期报废 (normalized) |
| 24 | `avg_component_value` | 1 | 组件平均库存价值 (normalized) |
| 25 | `avg_fg_value` | 1 | 成品平均库存价值 (normalized) |
| 26-30 | `safety_stock_weeks_{comp_id}` | 5 | 各组件安全库存周数 (normalized) |
| 31-35 | `lot_size_weeks_{comp_id}` | 5 | 各组件批量周数 (normalized) |
| 36-40 | `supplier_ci_{sid}` | 5 | 各供应商CI（影响采购价）(normalized) |
| 41 | `current_week` | 1 | 当前周次 (normalized) |

---

## 第三部分：全局状态（Centralized Critic）

### 3.1 扁平化向量结构

全局状态将所有子向量拼接为一个 **119维** 向量，用于 Centralized Critic（如MADDPG、QMIX中的全局价值函数）。

```
┌─────────────────────────────────────────────────────────────────────┐
│ 全局状态向量 (119维, float32)                                          │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────────┤
│ 组件库存  │ 成品库存  │ 组件在途  │ 供应商特征 │ 供应商决策 │  客户特征     │
│  5维     │  6维     │  5维     │  25维     │  15维     │   18维       │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ 销售运行时 │ 生产特征  │ 生产配置  │ 财务     │ 库存成本   │ 供应链配置    │
│  9维     │  6维     │  7维     │  5维     │  5维      │   10维       │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────────┤
│ 元信息 3维                                                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 详细维度映射

```python
# 索引映射表
STATE_INDEX_MAP = {
    "component_stock":        (0, 5),      # [0:5]
    "fg_stock":               (5, 11),     # [5:11]
    "component_on_order":     (11, 16),    # [11:16]
    "supplier_features":      (16, 41),    # [16:41]  — 5 suppliers × 5 features
    "supplier_decisions":     (41, 56),    # [41:56]  — 5 suppliers × 3 features
    "customer_features":      (56, 74),    # [56:74]  — 3 customers × 6 features
    "sales_runtime":          (74, 83),    # [74:83]  — 3 customers × 3 features
    "production_features":    (83, 89),    # [83:89]  — 6 features
    "production_config":      (89, 96),    # [89:96]  — 7 features
    "financial":              (96, 101),   # [96:101] — 5 features
    "inventory_cost":         (101, 106),  # [101:106]— 5 features
    "supplychain_config":     (106, 116),  # [106:116]— 10 features (5 SS + 5 lot)
    "meta":                   (116, 119),  # [116:119]— 3 features
}
```

### 3.3 精简版全局状态（60维）

如果119维过大，可用以下60维精简版（去掉静态配置维度，仅保留运行时状态）：

| 模块 | 维度 | 内容 |
|------|------|------|
| 组件库存 | 5 | 各组件当前库存量 |
| 成品库存 | 6 | 各成品当前库存量 |
| 组件在途 | 5 | 各组件在途量 |
| 供应商CI | 5 | 各供应商Contract Index |
| 供应商价格 | 5 | 各供应商有效采购价格 |
| 供应商质量 | 5 | 各供应商质量编码 |
| 客户CI | 3 | 各客户Contract Index |
| 客户需求 | 3 | 各客户周需求 |
| 客户实际SL | 3 | 各客户实际服务水平 |
| 生产利用率 | 2 | 混合器+灌装线利用率 |
| 故障率 | 1 | 故障停机比例 |
| 换型率 | 1 | 换型时间占比 |
| 财务累计 | 5 | revenue/gross_margin/operating_profit/indirect_costs/ROI |
| 库存成本 | 5 | space/interest/obsoletes/avg_comp/avg_fg |
| 元信息 | 3 | week/remaining/progress |
| 安全库存 | 5 | 各组件安全库存周数 |
| **总计** | **62** | |

---

## 第四部分：状态归一化建议

### 4.1 归一化方法选择原则

| 变量特征 | 推荐方法 | 目标范围 | 说明 |
|----------|----------|----------|------|
| 有明确上下界 | Min-Max | [-1, 1] | 如利用率、百分比、编码值 |
| 跨数量级大（库存、金额） | Log(1+x) → Min-Max | [-1, 1] | 如库存量、累计收入（从0到数百万） |
| 可能为负且无界 | Z-Score | [-1, 1] (clip ±3σ) | 如利润率、营业利润 |
| 离散/布尔 | 直接使用 | {0, 1} | 如开关变量 |
| 分类变量 | One-hot 或整数编码 | [0, N-1] | 如质量等级、设备型号 |
| 周期变量（如周次） | Min-Max | [-1, 1] | 有明确1-26范围 |

### 4.2 分模块归一化详表

#### 组件库存（Min-Max / Log）

| 变量 | 理论范围 | 实际99%范围 | 方法 | 归一化参数 |
|------|----------|-------------|------|------------|
| `comp_stock_pack_1l` | [0, 200,000] L | [0, 150,000] | Log→MinMax | log1p(x)/log1p(200000) |
| `comp_stock_pet` | [0, 200,000] pcs | [0, 150,000] | Log→MinMax | 同上 |
| `comp_stock_orange` | [0, 100,000] L | [0, 60,000] | Log→MinMax | log1p(x)/log1p(100000) |
| `comp_stock_mango` | [0, 50,000] L | [0, 30,000] | Log→MinMax | log1p(x)/log1p(50000) |
| `comp_stock_vitamin_c` | [0, 20,000] L | [0, 10,000] | Log→MinMax | log1p(x)/log1p(20000) |

#### 成品库存（Min-Max）

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `fg_stock_{pid}` | [0, 150,000] L | Min-Max | (x - 0) / 150000 → [-1, 1] |

#### 供应商状态

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `effective_price` | [0.02, 1.0] €/L | Min-Max | (x - 0.02) / 0.98 → [-1, 1] |
| `lead_time_days` | [5, 35]天 | Min-Max | (x - 5) / 30 → [-1, 1] |
| `contract_index` | [0.85, 1.20] | Min-Max | (x - 0.85) / 0.35 → [-1, 1] |
| `delivery_reliability` | [85, 99]% | Min-Max | (x - 85) / 14 → [-1, 1] |
| `quality` | {High, Middle, Poor} | 整数编码 | High=0, Middle=1, Poor=2 → [-1, 1] |

#### 客户状态

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `contract_index` | [0.70, 1.07] | Min-Max | (x - 0.70) / 0.37 → [-1, 1] |
| `weekly_demand` | [0, 120,000] L | Log→MinMax | log1p(x)/log1p(120000) → [-1, 1] |
| `service_level_pct` | [90, 99.5]% | Min-Max | (x - 90) / 9.5 → [-1, 1] |
| `shelf_life_pct` | [40, 85]% | Min-Max | (x - 40) / 45 → [-1, 1] |
| `payment_term` | [1, 8]周 | Min-Max | (x - 1) / 7 → [-1, 1] |

#### 生产特征

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `mixer_utilization` | [0, 1.0] | Min-Max | direct → [-1, 1] |
| `bottling_utilization` | [0, 1.5] | Min-Max | x / 1.5 → [-1, 1] |
| `breakdown_rate` | [0, 1.0] | Min-Max | direct → [-1, 1] |
| `changeover_ratio` | [0, 0.5] | Min-Max | x / 0.5 → [-1, 1] |
| `waste_rate` | [0, 0.15] | Min-Max | x / 0.15 → [-1, 1] |

#### 财务状态（混合方法）

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `cum_revenue` | [0, 4,000,000] | Log→MinMax | log1p(x)/log1p(4e6) → [-1, 1] |
| `cum_gross_margin` | [-500k, 2,000k] | Z-Score | μ≈500k, σ≈400k (clip ±3σ→[-1,1]) |
| `cum_operating_profit` | [-500k, 1,000k] | Z-Score | μ≈100k, σ≈250k |
| `cum_indirect_costs` | [0, 2,000,000] | Log→MinMax | log1p(x)/log1p(2e6) → [-1, 1] |
| `current_roi` | [-10, 30]% | Min-Max | (x + 10) / 40 → [-1, 1] |

#### 库存成本

| 变量 | 理论范围 | 方法 | 归一化参数 |
|------|----------|------|------------|
| `warehouse_space_cost` | [0, 500,000] | Log→MinMax | log1p(x)/log1p(500k) → [-1, 1] |
| `stock_interest_cost` | [0, 100,000] | Log→MinMax | log1p(x)/log1p(100k) → [-1, 1] |
| `obsoletes_value` | [0, 200,000] | Log→MinMax | log1p(x)/log1p(200k) → [-1, 1] |

### 4.3 归一化代码示例

```python
def normalize_global_state(raw: np.ndarray) -> np.ndarray:
    """对全局状态向量进行归一化。

    Args:
        raw: 原始状态向量 (119,)

    Returns:
        归一化后的状态向量 (119,)，范围 [-1, 1]
    """
    # 见 state_space.py 中的 normalize_value() 函数
    # 每个维度按 NORMALIZATION_CONFIG 中的规格逐维归一化
    ...
```

---

## 第五部分：与动作空间的对应关系

### 5.1 状态-动作关联图

```
┌──────────────────────────────────────────────────────────────────────┐
│                        ACTION → STATE 影响链                           │
│                                                                        │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│  │ Purchasing   │────▶│ supplier_ci      │────▶│ effective_price  │   │
│  │ Agent 动作    │     │ supplier_decisions│     │ financial        │   │
│  │              │     │ quality → 故障率  │     │ component_stock  │   │
│  └─────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                        │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│  │ Sales        │────▶│ customer_ci      │────▶│ revenue          │   │
│  │ Agent 动作    │     │ weekly_demand    │     │ service_level    │   │
│  │              │     │ customer_decisions│     │ fg_stock         │   │
│  └─────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                        │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│  │ Operations   │────▶│ production_config│────▶│ production_cost  │   │
│  │ Agent 动作    │     │ utilization      │     │ component_stock  │   │
│  │              │     │ breakdown_rate   │     │ fg_stock         │   │
│  └─────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                        │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│  │ SupplyChain  │────▶│ safety_stock     │────▶│ component_stock  │   │
│  │ Agent 动作    │     │ lot_size         │     │ inventory_cost   │   │
│  │              │     │ fg_safety_stock  │     │ financial        │   │
│  └─────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                        │
│  ═══════════════════════════════════════════════════════════════════   │
│  "只读" 状态（由环境动态决定，不受任何Agent直接控制）:                   │
│    • 故障事件 (breakdown_hours) — 由概率模型决定                        │
│    • 过期报废 (obsoletes) — 由批次expiry_week和当前周决定               │
│    • 日需求波动 (daily_demand_noise) — 由噪声模型决定                   │
│    • 启动产能损失 (startup_loss) — 由换型次数和灌装线公差决定           │
│    • 供应商实际发货可靠性 — 由supplier_reliability + 噪声决定            │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 详细影响矩阵

| 状态变量组 | Purchasing影响 | Sales影响 | Operations影响 | SupplyChain影响 | 环境决定 |
|------------|:---:|:---:|:---:|:---:|:---:|
| `component_stock` | 间接（价格→补货） | — | 直接（生产消耗） | 直接（安全库存→补货触发） | 部分 |
| `fg_stock` | — | 间接（需求→消耗） | 直接（决定产量） | 直接（安全库存→初始库存） | 部分 |
| `component_on_order` | — | — | — | 直接（批量→下单量） | 部分 |
| `supplier_features` | **直接**（CI/价格） | — | — | — | 部分 |
| `supplier_decisions` | **直接** | — | — | — | — |
| `customer_features` | — | **直接**（CI/需求） | — | — | 部分 |
| `sales_runtime` | — | **直接**（SL/收入） | 间接（产量→发货） | 间接（库存→发货） | 部分 |
| `production_features` | 间接（质量→故障） | — | **直接**（利用率） | — | 部分 |
| `production_config` | — | — | **直接** | — | — |
| `financial` | **直接**（采购成本） | **直接**（收入） | **直接**（生产成本） | 间接（库存成本） | — |
| `inventory_cost` | — | — | 间接（仓库配置） | **直接**（库存水平） | 部分 |
| `supplychain_config` | — | — | — | **直接** | — |
| `meta` | — | — | — | — | **完全** |

### 5.3 动作空间→状态空间详细映射

#### Purchasing Agent
```
动作: supplier_decisions.{sid}.quality → 影响: supplier_quality, breakdown_rate
动作: supplier_decisions.{sid}.payment_term_weeks → 影响: supplier_ci, payment_terms_net
动作: supplier_decisions.{sid}.delivery_reliability_pct → 影响: supplier_ci, delivery_reliability
动作: supplier_decisions.{sid}.delivery_window → 影响: supplier_ci
动作: supplier_decisions.{sid}.vmi → 影响: supplier_ci, project_costs
动作: dual_sourcing.{comp_id} → 影响: dual_sourcing_cost, project_costs
```

#### Sales Agent
```
动作: customer_decisions.{cid}.service_level_pct → 影响: customer_ci, bonus_penalty
动作: customer_decisions.{cid}.shelf_life_pct → 影响: customer_ci (≥90%锁CI)
动作: customer_decisions.{cid}.payment_term_weeks → 影响: customer_ci, payment_terms_net
动作: customer_decisions.{cid}.order_deadline → 影响: customer_ci, shortage分配
动作: customer_decisions.{cid}.promotional_pressure → 影响: weekly_demand (×1.0-1.095)
动作: customer_decisions.{cid}.vmi → 影响: vmi_cost, order_deadline→14:00
```

#### Operations Agent
```
动作: mixing.current_mixer → 影响: batch_min/max, run_time, clean_time, cost
动作: bottling.current_line → 影响: capacity/h, changeover_hours, tolerances
动作: bottling.shifts_per_week → 影响: daily_available_hours, labor_cost
动作: bottling.smed_action → 影响: changeover_hours (-30%)
动作: bottling.increase_speed → 影响: capacity_per_hour (+10%)
动作: bottling.preventive_maintenance → 影响: breakdown_prob (-30%/-50%)
动作: bottling.solve_breakdowns_training → 影响: breakdown_duration (-40%)
动作: bottling.max_overtime_hours → 影响: overtime_capacity, labor_cost (1.5×)
动作: outbound.outsource_type → 影响: warehouse_cost结构
```

#### SupplyChain Agent
```
动作: safety_stock_weeks.{comp_id} → 影响: comp补货触发点, avg_component_stock
动作: lot_size_weeks.{comp_id} → 影响: order_qty, ordering_frequency
动作: fg_safety_stock_weeks.{pid} → 影响: fg初始库存, avg_fg_stock
动作: fg_production_intervals_days.{pid} → 影响: 生产频率
动作: frozen_period_weeks → 影响: 生产灵活性, 组件库存约束时机
```

---

## 附录：代码集成指南

### A.1 在 simulation.py 中集成状态收集

在 `simulation.py` 的 `run()` 函数中，每周末添加：

```python
from state_space import StateCollector

collector = StateCollector()
states_history = []

for week in range(1, WEEKS_PER_ROUND + 1):
    # ... 现有仿真逻辑 ...

    # ── 状态收集 ──
    state = collector.collect(
        week=week,
        inv_state=inv_state,
        pending_orders=pending_orders,
        production_result=prod_result if week > 0 else None,
        weekly_sales=weekly_sales,
        cum_revenue=total_revenue,
        cum_gross_margin=...,
        cum_operating_profit=...,
        cum_indirect_costs=...,
        avg_component_value=...,
        avg_fg_value=...,
        cum_obsoletes=total_obsoletes,
    )
    states_history.append(state)

# 返回结果中包含完整状态历史
return SimulationResult(..., states_history=states_history)
```

### A.2 Gymnasium 环境集成

```python
import gymnasium as gym
from gymnasium import spaces
from state_space import StateSpaceConfig

cfg = StateSpaceConfig()

# 全局观测空间（Centralized Critic用）
global_observation_space = spaces.Box(
    low=-1.0, high=1.0,
    shape=(cfg.global_state_dim,),
    dtype=np.float32
)

# 局部观测空间（各Agent Policy用）
local_observation_spaces = {
    agent_id: spaces.Box(
        low=-1.0, high=1.0,
        shape=(info["dim"],),
        dtype=np.float32
    )
    for agent_id, info in cfg.LOCAL_OBSERVATION_CONFIG.items()
}
```

### A.3 关键文件索引

| 文件 | 用途 |
|------|------|
| `state_space.py` | StateSpaceConfig类 + 归一化 + 提取函数 |
| `decision.py` | 动作空间定义（DECISION_CONFIG） |
| `simulation.py` | 仿真引擎（状态收集集成点） |
| `supplychain.py` | InventoryState（库存状态来源） |
| `purchasing.py` | 供应商CI模型（供应商状态来源） |
| `sales.py` | 客户CI模型 + DailySalesSimulator（销售状态来源） |
| `operations.py` | ProductionSimulator（生产状态来源） |
| `finance.py` | ProfitLoss + Investment（财务状态来源） |
| `entities.py` | 静态实体数据（供应商、客户、产品规格） |
| `config.py` | 全局仿真参数（BASELINE、噪声参数） |

---

> **文档状态**: ✅ 完成
> **下一步**: 实现 `StateCollector.collect()` 方法，在 simulation.py 中集成状态收集循环
