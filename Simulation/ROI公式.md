# TFC ROI 完整公式

## 总公式

```
ROI = Operating_Profit / Total_Investment × 100%
```

文件位置: `finance.py` L96-100

---

## 一、损益表 (P&L) — `finance.py` L15-71

### 1. Revenue（收入）

```
Contracted_Sales_Revenue = Σ [ shipped_qty(liters) × base_sales_price(€/L) × Customer_CI ]

  shipped_qty         → 来自 sales.py WEEKLY_DEMAND_PIECES × liters_per_pack × 26周
  base_sales_price    → entities.py Product.base_price (L293-308)
  Customer_CI         → sales.py predict_customer_ci() (L370-435)
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Row 23: CI per customer | `sales.py` L23-56 CUSTOMER_DECISIONS | 客户 CI 目标值 |
| Row 24: Service level type | `sales.py` decision | 影响 CI 公式 |
| Row 25: Service level (%) | `sales.py` service_level_pct | 影响 CI: 每+1% → CI +0.002 |
| Row 26: Shelf life (%) | `sales.py` shelf_life_pct | 影响 CI |
| Row 27: Order deadline | `sales.py` order_deadline | 影响 CI |
| Row 28: Trade unit | `sales.py` trade_unit | 影响 CI |
| Row 29: Payment term (weeks) | `sales.py` payment_term_weeks | 影响 CI |
| Row 30: Promotional pressure | `sales.py` promotional_pressure | 影响需求乘数 |
| Row 31: Promotion horizon | `sales.py` promotion_horizon | 影响 CI |
| Rows 33-39: Weekly demand | `sales.py` WEEKLY_DEMAND_PIECES (L66-85) | 各产品-客户周需求(pieces) |

```
Bonus_or_Penalty = Σ f(Actual_SL%, Promised_SL%) × Revenue_per_customer

  Actual_SL%  = shipped_liters / total_demand_liters × 100
  Promised_SL% = CUSTOMER_DECISIONS[cid].service_level_pct  (Decision.csv Row 25)
  Penalty: SL每低于承诺1% → 扣约 revenue×3%
```

**Total_Revenue = Contracted_Sales_Revenue + Bonus_or_Penalty**

### 2. COGS（销售成本）

```
Purchase_Costs = Σ [ component_qty(liters) × base_price(€/L) × Supplier_CI ]
               + Σ Inbound_Transport_Cost

  component_qty       → BOM 反推 (entities.py L312-319) × 26周需求
  base_price          → entities.py Component.base_price (L204-212)
  Supplier_CI         → purchasing.py predict_supplier_ci() (L175-210)
  Inbound_Transport   → purchasing.py calculate_inbound_transport() (L265-312)
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Row 3: Quality | `purchasing.py` SUPPLIER_DECISIONS | 影响 CI: Middle=-0.002, Poor=-0.004 |
| Row 9: Payment term (weeks) | `purchasing.py` payment_term_weeks | 影响 CI: 1周=-0.0072...8周=+0.0020 |
| Row 10: Trade unit | `purchasing.py` trade_unit | 影响 CI + 运输成本公式 |
| Row 11: Agreed delivery reliability | `purchasing.py` delivery_reliability_pct | 影响 CI: 86%=+0.005...99%=+0.060 |
| Row 12: Delivery window | `purchasing.py` delivery_window | 影响 CI: 4h=+0.002...1w=-0.004 |
| Row 48: Transport costs Pallet/Drum/IBC | `purchasing.py` _TRANSPORT_COST_PER_KM_PALLET=0.15 | 托盘运费基准 |
| Row 49: Transport costs FTL/Tank | `purchasing.py` rate_per_km=0.78 | 罐车运费 |

```
Production_Costs = Mixer_Fixed + Mixer_Variable + Line_Fixed + Operators + Flexible_Labor

  Mixer_Fixed   = mixer.fixed_cost_annual × 0.5  (€31,250)
  Mixer_Variable = total_mixing_hours × mixer.cost_per_hour  (€135/h)
  Line_Fixed    = line.fixed_cost_annual × 0.5  (€49,000)
  Operators     = line.num_operators × shifts × €40,000 × 0.5
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Row 60: Line settings | `operations.py` current_line (L99) | 选择灌装线型号 |
| Row 61: Number of shifts | `operations.py` shifts_per_week (L101) | 1-5班 |
| Row 62: SMED action | `operations.py` smed_action (L103) | 缩短换型30%, €20,000/年 |
| Row 63: Increase speed | `operations.py` increase_speed (L105) | 提速10%, €30,000/年 |
| Mixer choice | `operations.py` current_mixer (L59) | Fruitmix MQ / MegaChurn 20 / FMM 4000 |

**COGS = Purchase_Costs + Production_Costs**
**Gross_Margin = Total_Revenue - COGS**

### 3. Indirect Costs（间接成本）

```
Overhead = Energy + Water + Other        (≈321,000 基准值)
  → config.py BASELINE (L38-40), 半固定

Stock_Interest = Avg_Stock_Value × 15% × 26/52
  Avg_Stock_Value = Avg_Component_Stock + Avg_Finished_Goods_Stock
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Rows 65-70: Safety stock (weeks) | `supplychain.py` safety_stock_weeks (L26-31) | 安全库存周数 → 库存水平 |
| Rows 65-70: Lot size (weeks) | `supplychain.py` lot_size_weeks (L35-40) | 批量 → 库存波动 |

```
Stock_Space = Raw_Material_Pallet_Spaces(€200/位/年) × 0.5
            + Finished_Goods_Pallet_Spaces(€200/位/年) × 0.5
            + Overflow(€3/托盘/天)
            + Tank_Yard(€25/罐/天 + €10/次入库 + €100/次运输)
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Row 56 col A: RM pallet locations | `operations.py` raw_materials_warehouse.pallet_locations (L46) | 866 位 |
| Row 56 col C: FG pallet locations | `operations.py` finished_goods_warehouse.pallet_locations (L136) | 1350 位 |

```
Stock_Risk = Obsoletes(过期报废) + Waste(启动废品) + Scrap

Handling = Inbound_Permanent(€40,000/年/人×0.5×FTE)
         + Inbound_Flexible(€42/h)
         + Outbound_Permanent(€40,000/年/人×0.5×FTE)
         + Outbound_Flexible(€42/h)
         + Inspection(€5,000/年/供应商×0.5)
```

| Decision.csv 参数 | Python 位置 | 说明 |
|-------------------|-------------|------|
| Row 57 col A: RM permanent employees | `operations.py` raw_materials_warehouse.permanent_employees (L47) | 4 FTE |
| Row 57 col C: FG permanent employees | `operations.py` finished_goods_warehouse.permanent_employees (L138) | 5 FTE |
| Row 58: Intake time (days) | `operations.py` intake_time_days (L48) | 4天 |

```
Administration = Inbound_Orders × €50 + Inbound_Lines × €10
               + Outbound_Orders × €25 + Outbound_Lines × €2
               + N_Suppliers × €40,000/年 × 0.5

Distribution = Σ(outbound_pallets × distance × 0.15 × 30 / trucks_per_FTL)
              × discount(订单行合并折扣)

Project = SMED(€20,000/年×0.5, Row 62=True)
        + Breakdown_Training(€400/人×N_operators, 如果Row 62=True)
        + VMI(€5,000/年×0.5, per supplier with VMI=True)
        + Supplier_Development(€60,000/年×0.5, per supplier with SD=True)
        + Dual_Sourcing(€40,000/年×0.5, per secondary supplier)
        + PET_Inflate(€140,000/年×0.5 + €700,000投资)
        + Optimize_Speed(€30,000/年×0.5, Row 63=True)

Interest_AR_AP = (AR - AP) × 15% × 26/52
  AR = Σ(customer_revenue × payment_term_weeks / 26)  ← Row 29
  AP = Σ(supplier_cost × payment_term_weeks / 26)      ← Row 9
```

**Indirect_Costs = Overhead + Stock_Interest + Stock_Space + Stock_Risk
                 + Handling + Administration + Distribution + Project + Interest_AR_AP**

**Operating_Profit = Gross_Margin - Indirect_Costs**

---

## 二、投资表 (Investment) — `finance.py` L74-93

```
Fixed_Building      = 2,500,000  (固定不变)

Inventory_Components  = 26周平均组件库存价值
  (库存水平取决于 safety_stock_weeks + lot_size_weeks → Row 65-70)

Inventory_FG         = 26周平均成品库存价值
  (库存水平取决于 fg_safety_stock_weeks + production_interval → Row 74-80)

Machinery            = 802,500  (基准)
                     + PET吹瓶投资(€700,000, 如果 inflate_pet=True)

Payment_Terms_Net    = AP - AR
  AP = Σ(supplier_purchase_cost × payment_term_weeks / 26)    ← Row 9
  AR = Σ(customer_revenue × payment_term_weeks / 26)          ← Row 29

Software             = 0  (当前无软件投资)

Total_Investment = Fixed + Inventory_Components + Inventory_FG
                 + Machinery + Payment_Terms_Net + Software
```

| Decision.csv 参数 | 影响 Investment 的哪部分 |
|-------------------|------------------------|
| Row 9: Supplier Payment term | Payment_Terms_Net (AP端) |
| Row 29: Customer Payment term | Payment_Terms_Net (AR端) |
| Rows 65-70: Safety stock + Lot size | Inventory_Components |
| Rows 74-80: FG safety stock + Interval | Inventory_FG |

---

## 三、ROI

```
ROI = Operating_Profit / Total_Investment × 100%
    = 155,411 / 3,888,477 × 100%
    = 4.0%  (FinanceReport.csv Row 2 验证值)
```

### 从 Decision.csv 到 ROI 的完整链路

```
Decision.csv
  │
  ├─→ Purchasing (Rows 2-12): Supplier SLA → CI → Purchase Costs ─┐
  ├─→ Sales (Rows 16-39): Customer SLA + Demand → Revenue ────────┤
  ├─→ Operations (Rows 55-63): Line/WH settings → Production/     │
  │     Handling/Space costs ─────────────────────────────────────┤
  └─→ Supply Chain (Rows 65-80): Stock params → Stock costs ──────┤
                                                                   │
                                                    ┌──────────────┘
                                                    ▼
                                              simulation.py run()
                                              (26周逐周仿真)
                                                    │
                                                    ▼
                                              finance.py
                                              ProfitLoss + Investment
                                                    │
                                                    ▼
                                              ROI = OP / Inv × 100%
```
