"""
TFC 橙汁游戏 — 统一决策变量管理
=================================
此文件集中管理所有仿真决策变量，作为 MARL (多智能体强化学习) Agent 的统一接口。

设计原则:
  - 所有决策变量集中在此文件的 DECISION_CONFIG 字典中
  - 每个变量附带元数据 (type, range, description) 方便 Agent 自省
  - RL Agent 训练时直接读写此字典即可操控全部仿真参数
  - 原始模块 (purchasing.py, sales.py, operations.py, supplychain.py)
    的独立决策字典仍可单独使用，但推荐通过此文件统一管理

决策模块概览:
  ┌──────────────────────────────────────────────────────────────────┐
  │ 1. purchasing    — 供应商决策                                    │
  │    ├─ supplier_decisions: 5 个供应商的 SLA 参数                   │
  │    └─ dual_sourcing: 双源采购开关 (per component)                 │
  │                                                                  │
  │ 2. sales         — 客户决策 + 需求数据                            │
  │    ├─ customer_decisions: 3 个客户的 SLA 参数                     │
  │    ├─ weekly_demand_pieces: 15 条产品-客户周需求                   │
  │    ├─ promo_settings: 促销压力配置                                │
  │    └─ shortage_settings: 短缺分配规则                             │
  │                                                                  │
  │ 3. operations    — 运营决策 (4 tabs)                              │
  │    ├─ inbound: 来料检验 + 原料仓库                                │
  │    ├─ mixing: 混合器选择 + 产品分配 + 排产顺序                    │
  │    ├─ bottling: 灌装线设置 + 维护 + 班次                          │
  │    └─ outbound: 成品仓库 + 外包选项                               │
  │                                                                  │
  │ 4. supply_chain  — 供应链参数                                    │
  │    ├─ safety_stock_weeks: 组件安全库存 (周)                       │
  │    ├─ lot_size_weeks: 组件补货批量 (周)                           │
  │    ├─ fg_safety_stock_weeks: 成品安全库存 (周)                    │
  │    ├─ fg_production_intervals_days: 成品生产间隔 (天)             │
  │    └─ frozen_period: 生产计划冻结期                               │
  │                                                                  │
  │ 5. global         — 全局仿真参数                                  │
  │    ├─ random_seed: 随机种子                                       │
  │    ├─ use_noise: 噪声开关                                         │
  │    └─ noise_params: 噪声参数                                      │
  └──────────────────────────────────────────────────────────────────┘

使用方法:
    from decision import DECISION_CONFIG, get_decision, set_decision, apply_decisions

    # 读取供应商 Pack 的质量等级
    quality = get_decision("purchasing.supplier_decisions.s_pack.quality")

    # RL Agent 修改决策
    set_decision("operations.bottling.shifts_per_week", 3)
    set_decision("supply_chain.safety_stock_weeks.orange", 2.0)

    # 应用决策到各原始模块
    apply_decisions()

    # 验证决策合法性
    from decision import validate_decisions
    errors = validate_decisions(DECISION_CONFIG)
    if errors:
        print("Invalid decisions:", errors)
"""

from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
# 决策变量合法取值范围（枚举 + 常量）
# ═══════════════════════════════════════════════════════════════════════════════

# ── 供应商相关 ──
QUALITY_LEVELS = ["High", "Middle", "Poor"]
TRADE_UNIT_SUPPLIER = ["Pallet", "FTL", "Tank", "IBC", "Drum"]
DELIVERY_WINDOWS = ["4 hours", "1 day", "2 days", "1 week"]
PAYMENT_TERM_WEEKS_RANGE = (1, 8)          # min, max
DELIVERY_RELIABILITY_RANGE = (85.0, 99.0)   # min%, max%

# ── 客户相关 ──
SERVICE_LEVEL_RANGE = (90.0, 99.5)          # min%, max%
SHELF_LIFE_RANGE = (40.0, 85.0)             # min%, max% (≥90% locks CI)
ORDER_DEADLINES = ["12:00", "14:00", "17:00", "20:00"]
TRADE_UNIT_CUSTOMER = ["Box", "Pallet layer", "Pallet"]
PROMO_PRESSURE_LEVELS = ["None", "Low", "Middle", "Heavy"]
PROMO_HORIZON_LEVELS = ["Short", "Middle", "Long"]

# ── 运营相关 ──
MIXER_NAMES = ["Fruitmix MQ", "MegaChurn 20", "FMM 4000"]
BOTTLING_LINE_NAMES = ["Swiss Fill 2", "TopSpeed 1", "MultiFlex 1", "Swiss Fill 1"]
PREVENTIVE_MAINTENANCE_LEVELS = ["None", "A little", "A lot"]
SHIFTS_RANGE = (1, 5)                       # min, max shifts per week
MAX_OVERTIME_RANGE = (0, 40)                # max overtime hours per week
OUTSOURCE_TYPES = ["None", "Conventional", "Automated", "MCC"]
MCC_TYPES = [None, "yoghurt", "ice_cream", "tissue"]
PRODUCT_IDS = [
    "p_orange_1l", "p_ocp_1l", "p_om_1l",
    "p_orange_pet", "p_ocp_pet", "p_om_pet",
]
COMPONENT_IDS = ["pack_1l", "pet", "orange", "mango", "vitamin_c"]
SUPPLIER_IDS = ["s_pack", "s_pet", "s_orange", "s_mango", "s_vitc"]
CUSTOMER_IDS = ["c_fg", "c_land", "c_dom"]

# ── 供应链相关 ──
SAFETY_STOCK_RANGE = (0.0, 6.0)             # min, max weeks
LOT_SIZE_RANGE = (1, 8)                     # min, max weeks
FROZEN_PERIOD_RANGE = (0, 6)                # min, max weeks
PRODUCTION_INTERVAL_RANGE = (1, 14)         # min, max days


# ═══════════════════════════════════════════════════════════════════════════════
# 统一决策字典 DECISION_CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

DECISION_CONFIG: Dict[str, Any] = {

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  1. purchasing — 供应商决策                                                ║
    # ║     对应游戏 Purchasing 页面的每个供应商 SLA 设置                              ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    "purchasing": {

        # ── 供应商决策 (per supplier) ──
        # 每个供应商可调整 7 个 SLA 参数
        "supplier_decisions": {
            # Mono Packaging Materials — Pack 1 liter (法国, 卡车, 500km, 15天)
            "s_pack": {
                "quality": {
                    "value": "High",
                    "type": "categorical",
                    "options": QUALITY_LEVELS,
                    "description": "原材料质量等级。High=基准, Middle=+15%故障率, Poor=+30%故障率"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "付款周期(周)。越长CI越高，但影响现金流"
                },
                "trade_unit": {
                    "value": "Pallet",
                    "type": "categorical",
                    "options": TRADE_UNIT_SUPPLIER,
                    "description": "贸易单位。影响运输成本计算方式"
                },
                "delivery_reliability_pct": {
                    "value": 96.0,
                    "type": "float",
                    "range": DELIVERY_RELIABILITY_RANGE,
                    "description": "承诺交货可靠性(%)。越高CI越高"
                },
                "delivery_window": {
                    "value": "1 day",
                    "type": "categorical",
                    "options": DELIVERY_WINDOWS,
                    "description": "交货时间窗口。越窄CI越高"
                },
                "supplier_development": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商发展项目。实测对CI无影响，但改善长期关系"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商管理库存(VMI)。显著降低CI (-0.0112)，成本€5,000/年"
                },
            },
            # Platin PET — PET (法国, 卡车, 500km, 15天)
            "s_pet": {
                "quality": {
                    "value": "High",
                    "type": "categorical",
                    "options": QUALITY_LEVELS,
                    "description": "原材料质量等级"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "付款周期(周)"
                },
                "trade_unit": {
                    "value": "Pallet",
                    "type": "categorical",
                    "options": TRADE_UNIT_SUPPLIER,
                    "description": "贸易单位"
                },
                "delivery_reliability_pct": {
                    "value": 96.0,
                    "type": "float",
                    "range": DELIVERY_RELIABILITY_RANGE,
                    "description": "承诺交货可靠性(%)"
                },
                "delivery_window": {
                    "value": "1 day",
                    "type": "categorical",
                    "options": DELIVERY_WINDOWS,
                    "description": "交货时间窗口"
                },
                "supplier_development": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商发展项目"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
            # Miami Oranges — Orange (美国, 海运, 7500km, 30天)
            "s_orange": {
                "quality": {
                    "value": "High",
                    "type": "categorical",
                    "options": QUALITY_LEVELS,
                    "description": "原材料质量等级"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "付款周期(周)"
                },
                "trade_unit": {
                    "value": "Tank",
                    "type": "categorical",
                    "options": TRADE_UNIT_SUPPLIER,
                    "description": "贸易单位。Orange为液体，只能选Tank"
                },
                "delivery_reliability_pct": {
                    "value": 98.0,
                    "type": "float",
                    "range": DELIVERY_RELIABILITY_RANGE,
                    "description": "承诺交货可靠性(%)"
                },
                "delivery_window": {
                    "value": "1 day",
                    "type": "categorical",
                    "options": DELIVERY_WINDOWS,
                    "description": "交货时间窗口"
                },
                "supplier_development": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商发展项目"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
            # NO8DO Mango — Mango (西班牙, 卡车, 1800km, 10天)
            "s_mango": {
                "quality": {
                    "value": "High",
                    "type": "categorical",
                    "options": QUALITY_LEVELS,
                    "description": "原材料质量等级"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "付款周期(周)"
                },
                "trade_unit": {
                    "value": "IBC",
                    "type": "categorical",
                    "options": TRADE_UNIT_SUPPLIER,
                    "description": "贸易单位。Mango为液体，可选IBC或Tank"
                },
                "delivery_reliability_pct": {
                    "value": 96.0,
                    "type": "float",
                    "range": DELIVERY_RELIABILITY_RANGE,
                    "description": "承诺交货可靠性(%)"
                },
                "delivery_window": {
                    "value": "2 days",
                    "type": "categorical",
                    "options": DELIVERY_WINDOWS,
                    "description": "交货时间窗口"
                },
                "supplier_development": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商发展项目"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
            # AlL Vitamins — Vitamin C (法国, 卡车, 500km, 20天)
            "s_vitc": {
                "quality": {
                    "value": "High",
                    "type": "categorical",
                    "options": QUALITY_LEVELS,
                    "description": "原材料质量等级"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "付款周期(周)"
                },
                "trade_unit": {
                    "value": "Drum",
                    "type": "categorical",
                    "options": TRADE_UNIT_SUPPLIER,
                    "description": "贸易单位。Vitamin C为液体，可选Drum或IBC"
                },
                "delivery_reliability_pct": {
                    "value": 96.0,
                    "type": "float",
                    "range": DELIVERY_RELIABILITY_RANGE,
                    "description": "承诺交货可靠性(%)"
                },
                "delivery_window": {
                    "value": "1 day",
                    "type": "categorical",
                    "options": DELIVERY_WINDOWS,
                    "description": "交货时间窗口"
                },
                "supplier_development": {
                    "value": False,
                    "type": "bool",
                    "description": "供应商发展项目"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
        },

        # ── 双源采购 (per component) ──
        # 为组件启用双源采购需 €40,000/年/额外供应商
        "dual_sourcing": {
            "pack_1l": {
                "value": False,
                "type": "bool",
                "description": "Pack 1L 双源采购。开启额外花费€40,000/年"
            },
            "pet": {
                "value": False,
                "type": "bool",
                "description": "PET 双源采购"
            },
            "orange": {
                "value": False,
                "type": "bool",
                "description": "Orange 双源采购"
            },
            "mango": {
                "value": False,
                "type": "bool",
                "description": "Mango 双源采购"
            },
            "vitamin_c": {
                "value": False,
                "type": "bool",
                "description": "Vitamin C 双源采购"
            },
        },
    },

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  2. sales — 客户决策 + 需求数据                                         ║
    # ║     对应游戏 Sales 页面的客户 SLA 设置和需求管理                          ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    "sales": {

        # ── 客户决策 (per customer) ──
        # 每个客户可调整 8 个 SLA 参数
        "customer_decisions": {
            # Food & Groceries
            "c_fg": {
                "service_level_pct": {
                    "value": 95.0,
                    "type": "float",
                    "range": SERVICE_LEVEL_RANGE,
                    "description": "承诺服务水平(%)。低于承诺值触发Penalty (0.5% revenue/1% shortfall)"
                },
                "shelf_life_pct": {
                    "value": 75.0,
                    "type": "float",
                    "range": SHELF_LIFE_RANGE,
                    "description": "要求剩余保质期(%)。≥90%时CI锁定为基准值"
                },
                "order_deadline": {
                    "value": "14:00",
                    "type": "categorical",
                    "options": ORDER_DEADLINES,
                    "description": "订单截止时间。VMI开启时覆盖为14:00"
                },
                "trade_unit": {
                    "value": "Pallet layer",
                    "type": "categorical",
                    "options": TRADE_UNIT_CUSTOMER,
                    "description": "贸易单位。影响拣货效率"
                },
                "payment_term_weeks": {
                    "value": 3,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "客户付款周期(周)。越长CI越高"
                },
                "promotional_pressure": {
                    "value": "Middle",
                    "type": "categorical",
                    "options": PROMO_PRESSURE_LEVELS,
                    "description": "促销压力。增加需求: None=0%, Low=0.75%, Middle=1.75%, Heavy=4.75%"
                },
                "promotion_horizon": {
                    "value": "Short",
                    "type": "categorical",
                    "options": PROMO_HORIZON_LEVELS,
                    "description": "促销预知期。越长CI越低"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI (供应商管理库存)。成本€5,000/年，启用后order_deadline覆盖为14:00"
                },
            },
            # LAND Market
            "c_land": {
                "service_level_pct": {
                    "value": 95.0,
                    "type": "float",
                    "range": SERVICE_LEVEL_RANGE,
                    "description": "承诺服务水平(%)"
                },
                "shelf_life_pct": {
                    "value": 75.0,
                    "type": "float",
                    "range": SHELF_LIFE_RANGE,
                    "description": "要求剩余保质期(%)"
                },
                "order_deadline": {
                    "value": "14:00",
                    "type": "categorical",
                    "options": ORDER_DEADLINES,
                    "description": "订单截止时间"
                },
                "trade_unit": {
                    "value": "Pallet layer",
                    "type": "categorical",
                    "options": TRADE_UNIT_CUSTOMER,
                    "description": "贸易单位"
                },
                "payment_term_weeks": {
                    "value": 3,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "客户付款周期(周)"
                },
                "promotional_pressure": {
                    "value": "Middle",
                    "type": "categorical",
                    "options": PROMO_PRESSURE_LEVELS,
                    "description": "促销压力"
                },
                "promotion_horizon": {
                    "value": "Short",
                    "type": "categorical",
                    "options": PROMO_HORIZON_LEVELS,
                    "description": "促销预知期"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
            # Dominick's (仅 PET 产品)
            "c_dom": {
                "service_level_pct": {
                    "value": 95.0,
                    "type": "float",
                    "range": SERVICE_LEVEL_RANGE,
                    "description": "承诺服务水平(%)"
                },
                "shelf_life_pct": {
                    "value": 70.0,
                    "type": "float",
                    "range": SHELF_LIFE_RANGE,
                    "description": "要求剩余保质期(%)"
                },
                "order_deadline": {
                    "value": "14:00",
                    "type": "categorical",
                    "options": ORDER_DEADLINES,
                    "description": "订单截止时间"
                },
                "trade_unit": {
                    "value": "Pallet layer",
                    "type": "categorical",
                    "options": TRADE_UNIT_CUSTOMER,
                    "description": "贸易单位"
                },
                "payment_term_weeks": {
                    "value": 4,
                    "type": "int",
                    "range": PAYMENT_TERM_WEEKS_RANGE,
                    "description": "客户付款周期(周)"
                },
                "promotional_pressure": {
                    "value": "Heavy",
                    "type": "categorical",
                    "options": PROMO_PRESSURE_LEVELS,
                    "description": "促销压力"
                },
                "promotion_horizon": {
                    "value": "Short",
                    "type": "categorical",
                    "options": PROMO_HORIZON_LEVELS,
                    "description": "促销预知期"
                },
                "vmi": {
                    "value": False,
                    "type": "bool",
                    "description": "VMI"
                },
            },
        },

        # ── 周需求数据 (基准需求, pieces/周) ──
        # 来源: Sales → History → Round 3 → Customer Product report
        # 数据采集时促销压力为 Middle (所有客户)
        "weekly_demand_pieces": {
            "description": "基准周需求 pieces/周 (Round 3 数据, 促销压力=Middle)",
            "data": {
                # Food & Groceries
                ("p_orange_1l",  "c_fg"):   42637,
                ("p_ocp_1l",     "c_fg"):    7182,
                ("p_om_1l",      "c_fg"):   26777,
                ("p_orange_pet", "c_fg"):   35873,
                ("p_ocp_pet",    "c_fg"):    5412,
                ("p_om_pet",     "c_fg"):   15539,
                # LAND Market
                ("p_orange_1l",  "c_land"): 24756,
                ("p_ocp_1l",     "c_land"):  4179,
                ("p_om_1l",      "c_land"): 15385,
                ("p_orange_pet", "c_land"): 11935,
                ("p_ocp_pet",    "c_land"):  1818,
                ("p_om_pet",     "c_land"):  5132,
                # Dominick's (仅 PET 产品)
                ("p_orange_pet", "c_dom"):  70276,
                ("p_ocp_pet",    "c_dom"):  10512,
                ("p_om_pet",     "c_dom"):  30370,
            },
        },

        # ── 促销需求提升系数 ──
        # 促销压力增加客户需求量（相对于基准需求）
        "promo_settings": {
            "demand_uplift": {
                "description": "各促销压力等级对应的需求提升比例",
                "data": {
                    "Benchmark": 0.0,
                    "None":      0.0,
                    "Low":       0.0075,    # 0.5%-1.0% → 中值 0.75%
                    "Light":     0.0075,
                    "Middle":    0.0175,    # 1.5%-2.0% → 中值 1.75%
                    "Medium":    0.0175,
                    "High":      0.0475,    # 4.0%-5.5% → 中值 4.75%
                    "Heavy":     0.0475,
                },
            },
            "round3_promo_pressure": {
                "value": "Middle",
                "type": "categorical",
                "description": "WEEKLY_DEMAND_PIECES 数据采集时的促销状态，用于还原基准需求"
            },
            "value_for_money_customers": {
                "description": "Value for Money 客户ID集合（促销需求翻倍）",
                "data": set(),
            },
            "slowmover_combinations": {
                "description": "Slowmover 产品-客户组合集合（促销需求翻倍）",
                "data": set(),
            },
            "vmi_cost_annual": {
                "value": 5000.0,
                "type": "float",
                "description": "VMI 项目年费 (€/年)"
            },
        },

        # ── 短缺分配设置 ──
        "shortage_settings": {
            "rule": {
                "value": "proportional",
                "type": "categorical",
                "options": ["proportional", "fcfs", "priority"],
                "description": "短缺分配规则: proportional=等比分配, fcfs=先到先得, priority=按客户优先级"
            },
            "customer_priority": {
                "description": "客户优先级（仅 priority 规则生效，数值越小优先级越高）",
                "c_fg": {
                    "value": 1,
                    "type": "int",
                    "range": (1, 3),
                    "description": "Food & Groceries 优先级"
                },
                "c_dom": {
                    "value": 2,
                    "type": "int",
                    "range": (1, 3),
                    "description": "Dominick's 优先级"
                },
                "c_land": {
                    "value": 3,
                    "type": "int",
                    "range": (1, 3),
                    "description": "LAND Market 优先级"
                },
            },
        },

        # ── 日级需求设置 ──
        "daily_demand_settings": {
            "weights": {
                "value": [0.20, 0.20, 0.20, 0.20, 0.20],
                "type": "list[float]",
                "sum_to_one": True,
                "description": "每日需求权重（周一至周五），需归一化为 sum=1.0"
            },
            "noise_std": {
                "value": 0.05,
                "type": "float",
                "range": (0.0, 0.2),
                "description": "日需求随机波动标准差（相对值），仅 USE_NOISE=True 时生效"
            },
        },

        # ── Bonus/Penalty 参数 ──
        "bonus_penalty": {
            "penalty_factor": {
                "value": 0.5,
                "type": "float",
                "description": "每1%服务不足 → 0.5%收入扣减"
            },
            "bonus_factor": {
                "value": 0.2,
                "type": "float",
                "description": "每1%超额服务 → 0.2%收入奖励"
            },
        },
    },

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  3. operations — 运营决策 (4 tabs)                                      ║
    # ║     对应游戏 Operations 页面的 inbound / mixing / bottling / outbound    ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    "operations": {

        # ── Tab 1: inbound — 来料检验 + 原料仓库 ──
        "inbound": {
            # 来料检验 — 每个供应商一个开关，开启后 €5,000/年/供应商
            "raw_materials_inspection": {
                "NO8DO Mango": {
                    "value": True,
                    "type": "bool",
                    "description": "NO8DO Mango 来料检验。开启€5,000/年，检验增加2h/订单行入库时间"
                },
                "Mono Packaging Materials": {
                    "value": False,
                    "type": "bool",
                    "description": "Mono Packaging Materials 来料检验"
                },
                "Miami Oranges": {
                    "value": True,
                    "type": "bool",
                    "description": "Miami Oranges 来料检验"
                },
                "Platin PET": {
                    "value": True,
                    "type": "bool",
                    "description": "Platin PET 来料检验"
                },
                "AlL Vitamins": {
                    "value": True,
                    "type": "bool",
                    "description": "AlL Vitamins 来料检验"
                },
            },

            # 原料仓库设置
            "raw_materials_warehouse": {
                "pallet_locations": {
                    "value": 866,
                    "type": "int",
                    "range": (100, 5000),
                    "description": "托盘位数。每个托盘位€200/年"
                },
                "permanent_employees": {
                    "value": 4,
                    "type": "int",
                    "range": (1, 20),
                    "description": "永久员工数(FTE)。每人€40,000/年，40h/周"
                },
                "intake_time_days": {
                    "value": 4,
                    "type": "int",
                    "range": (1, 7),
                    "description": "入库时间(天)。降低峰值但不改变总工时"
                },
            },
        },

        # ── Tab 2: mixing — 混合器选择 + 产品分配 + 排产顺序 ──
        "mixing": {
            "current_mixer": {
                "value": "Fruitmix MQ",
                "type": "categorical",
                "options": MIXER_NAMES,
                "description": (
                    "当前选用混合器。Fruitmix MQ: 8k-12kL/batch, €135/h; "
                    "MegaChurn 20: 15k-20kL/batch, €160/h; "
                    "FMM 4000: 3k-6kL/batch, €100/h"
                ),
            },
            "product_to_mixer": {
                "description": "每个成品分配到哪个混合器",
                "p_orange_1l": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "Orange 1L 混合器分配"
                },
                "p_ocp_1l": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "OCP 1L 混合器分配"
                },
                "p_om_1l": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "OM 1L 混合器分配"
                },
                "p_orange_pet": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "Orange PET 混合器分配"
                },
                "p_ocp_pet": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "OCP PET 混合器分配"
                },
                "p_om_pet": {
                    "value": "Fruitmix MQ",
                    "type": "categorical",
                    "options": MIXER_NAMES,
                    "description": "OM PET 混合器分配"
                },
            },
            "production_sequence": {
                "value": [
                    "p_orange_1l", "p_orange_pet",   # 橙汁系列（同口味，仅尺寸换型）
                    "p_ocp_1l", "p_ocp_pet",          # 橙C系列
                    "p_om_1l", "p_om_pet",            # 橙芒系列
                ],
                "type": "list[str]",
                "description": (
                    "手动排产顺序。决定每天产品生产的先后顺序。"
                    "同口味产品排在一起可减少口味清洗换型（如 orange_1l → orange_pet 仅尺寸换型）"
                ),
            },
        },

        # ── Tab 3: bottling — 灌装线通用设置 + 产线设置 + 产品分配 ──
        "bottling": {
            # 通用设置
            "general_settings": {
                "preventive_maintenance": {
                    "value": "A little",
                    "type": "categorical",
                    "options": PREVENTIVE_MAINTENANCE_LEVELS,
                    "description": (
                        "预防维护。None: 无维护/30%故障率; "
                        "A little: 1h/周维护/故障率-30%; "
                        "A lot: 3h/周维护/故障率-50%"
                    ),
                },
                "solve_breakdowns_training": {
                    "value": "Yes",
                    "type": "categorical",
                    "options": ["No", "Yes"],
                    "description": "故障排除培训。Yes: 故障持续时间 -40%"
                },
                "inflate_pet_bottles": {
                    "value": False,
                    "type": "bool",
                    "description": "PET瓶现场吹瓶。开启: €140,000/年 + €700,000设备投资"
                },
            },

            # 产线设置
            "current_line": {
                "value": "Swiss Fill 2",
                "type": "categorical",
                "options": BOTTLING_LINE_NAMES,
                "description": (
                    "当前选用灌装线。Swiss Fill 2: 3100L/h, 5ops, tolerance=Middle; "
                    "TopSpeed 1: 3250L/h, 4ops, tolerance=Narrow; "
                    "MultiFlex 1: 2950L/h, 6ops, tolerance=Wide; "
                    "Swiss Fill 1: 3100L/h, 5ops, tolerance=Wide"
                ),
            },
            "shifts_per_week": {
                "value": 2,
                "type": "int",
                "range": SHIFTS_RANGE,
                "description": "每周班次数(1-5)。每班8小时，影响可用生产小时和人工成本"
            },
            "smed_action": {
                "value": True,
                "type": "bool",
                "description": "SMED快速换型。开启: 换型时间-30%，成本€20,000/年"
            },
            "increase_speed": {
                "value": False,
                "type": "bool",
                "description": "提升灌装速度。开启: 产能+10%，成本€30,000/年"
            },
            "max_overtime_hours": {
                "value": 16,
                "type": "int",
                "range": MAX_OVERTIME_RANGE,
                "description": "每周最大加班小时数。OT按1.5×variable cost计费，不收复固定成本"
            },

            # 产品到灌装线的分配
            "product_to_line": {
                "description": "每个成品分配到哪条灌装线",
                "p_orange_1l": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "Orange 1L 灌装线分配"
                },
                "p_ocp_1l": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "OCP 1L 灌装线分配"
                },
                "p_om_1l": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "OM 1L 灌装线分配"
                },
                "p_orange_pet": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "Orange PET 灌装线分配"
                },
                "p_ocp_pet": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "OCP PET 灌装线分配"
                },
                "p_om_pet": {
                    "value": "Swiss Fill 2",
                    "type": "categorical",
                    "options": BOTTLING_LINE_NAMES,
                    "description": "OM PET 灌装线分配"
                },
            },
        },

        # ── Tab 4: outbound — 成品仓库 + 外包选项 ──
        "outbound": {
            "finished_goods_warehouse": {
                "outsource_type": {
                    "value": "None",
                    "type": "categorical",
                    "options": OUTSOURCE_TYPES,
                    "description": (
                        "成品仓库外包类型。None=自营; Conventional=€1.30/托盘/天; "
                        "Automated=€1.50/托盘/天; MCC=€10,000/年+自动化费率"
                    ),
                },
                "mcc_type": {
                    "value": None,
                    "type": "categorical",
                    "options": MCC_TYPES,
                    "description": "MCC类型（仅 outsource_type=='MCC' 时生效）"
                },
                "pallet_locations": {
                    "value": 1350,
                    "type": "int",
                    "range": (100, 10000),
                    "description": "托盘位数。每个托盘位€200/年"
                },
                "permanent_employees": {
                    "value": 5,
                    "type": "int",
                    "range": (1, 30),
                    "description": "永久员工数(FTE)。每人€40,000/年，40h/周"
                },
            },
        },
    },

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  4. supply_chain — 供应链参数                                            ║
    # ║     对应游戏 Supply Chain 页面的库存策略设置                               ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    "supply_chain": {

        # ── 组件安全库存 (周) ──
        "safety_stock_weeks": {
            "pack_1l": {
                "value": 1.5,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Pack 1L 安全库存周数"
            },
            "pet": {
                "value": 2.1,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "PET 安全库存周数"
            },
            "orange": {
                "value": 1.5,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Orange 安全库存周数"
            },
            "mango": {
                "value": 2.0,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Mango 安全库存周数"
            },
            "vitamin_c": {
                "value": 2.8,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Vitamin C 安全库存周数"
            },
        },

        # ── 组件补货批量 (周) ──
        "lot_size_weeks": {
            "pack_1l": {
                "value": 3,
                "type": "int",
                "range": LOT_SIZE_RANGE,
                "description": "Pack 1L 补货批量(周数需求)。越大单次采购量越大，但库存成本也越高"
            },
            "pet": {
                "value": 3,
                "type": "int",
                "range": LOT_SIZE_RANGE,
                "description": "PET 补货批量(周数需求)"
            },
            "orange": {
                "value": 3,
                "type": "int",
                "range": LOT_SIZE_RANGE,
                "description": "Orange 补货批量(周数需求)"
            },
            "mango": {
                "value": 3,
                "type": "int",
                "range": LOT_SIZE_RANGE,
                "description": "Mango 补货批量(周数需求)"
            },
            "vitamin_c": {
                "value": 4,
                "type": "int",
                "range": LOT_SIZE_RANGE,
                "description": "Vitamin C 补货批量(周数需求)"
            },
        },

        # ── 生产计划冻结期 ──
        "frozen_period_weeks": {
            "value": 3,
            "type": "int",
            "range": FROZEN_PERIOD_RANGE,
            "description": "生产计划冻结期(周)。冻结期内计划锁定，跳过组件库存检查"
        },
        "production_interval_weeks": {
            "value": 1,
            "type": "int",
            "range": (1, 5),
            "description": "生产间隔(周)。即每几周排一次产"
        },

        # ── 成品安全库存 (周) ──
        "fg_safety_stock_weeks": {
            "p_orange_1l": {
                "value": 2.5,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Orange 1L 成品安全库存周数"
            },
            "p_ocp_1l": {
                "value": 2.8,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "OCP 1L 成品安全库存周数"
            },
            "p_om_1l": {
                "value": 2.0,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "OM 1L 成品安全库存周数"
            },
            "p_orange_pet": {
                "value": 2.5,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "Orange PET 成品安全库存周数"
            },
            "p_ocp_pet": {
                "value": 3.0,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "OCP PET 成品安全库存周数"
            },
            "p_om_pet": {
                "value": 3.0,
                "type": "float",
                "range": SAFETY_STOCK_RANGE,
                "description": "OM PET 成品安全库存周数"
            },
        },

        # ── 成品生产间隔 (天) ──
        "fg_production_intervals_days": {
            "p_orange_1l": {
                "value": 10,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "Orange 1L 生产间隔(天)。决定排产频率"
            },
            "p_ocp_1l": {
                "value": 10,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "OCP 1L 生产间隔(天)"
            },
            "p_om_1l": {
                "value": 10,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "OM 1L 生产间隔(天)"
            },
            "p_orange_pet": {
                "value": 9,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "Orange PET 生产间隔(天)"
            },
            "p_ocp_pet": {
                "value": 10,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "OCP PET 生产间隔(天)"
            },
            "p_om_pet": {
                "value": 9,
                "type": "int",
                "range": PRODUCTION_INTERVAL_RANGE,
                "description": "OM PET 生产间隔(天)"
            },
        },
    },

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  5. global — 全局仿真参数                                                ║
    # ║     控制仿真模式、噪声等顶层设置                                          ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    "global": {
        "random_seed": {
            "value": 42,
            "type": "int",
            "range": (0, 2**31 - 1),
            "description": "随机种子。固定后仿真可复现"
        },
        "weeks_per_round": {
            "value": 26,
            "type": "int",
            "description": "每轮周数（固定，不建议修改）"
        },
        "use_noise": {
            "value": True,
            "type": "bool",
            "description": "噪声开关。False=确定性仿真; True=蒙特卡洛仿真"
        },
        "noise_params": {
            "demand_noise_std": {
                "value": 0.08,
                "type": "float",
                "range": (0.0, 0.3),
                "description": "需求波动标准差 ±8%"
            },
            "production_noise_std": {
                "value": 0.03,
                "type": "float",
                "range": (0.0, 0.2),
                "description": "生产效率波动标准差 ±3%"
            },
            "cost_noise_std": {
                "value": 0.04,
                "type": "float",
                "range": (0.0, 0.2),
                "description": "成本波动标准差 ±4%"
            },
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷访问函数
# ═══════════════════════════════════════════════════════════════════════════════

def get_value(config_path: str):
    """按点号路径获取决策变量的 .value 字段。

    示例:
        get_value("purchasing.supplier_decisions.s_pack.quality")  # → "High"
        get_value("operations.bottling.shifts_per_week")            # → 2
        get_value("supply_chain.safety_stock_weeks.orange")         # → 1.5
    """
    keys = config_path.split(".")
    node = DECISION_CONFIG
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
            if node is None:
                return None
        else:
            return None
    # 如果叶子节点有 'value' 字段则返回 .value，否则返回节点本身
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def set_value(config_path: str, new_value) -> bool:
    """按点号路径设置决策变量的 .value 字段。

    返回 True 表示设置成功，False 表示路径无效。
    """
    keys = config_path.split(".")
    node = DECISION_CONFIG
    for k in keys[:-1]:
        if isinstance(node, dict):
            node = node.get(k)
            if node is None:
                return False
        else:
            return False
    last_key = keys[-1]
    if isinstance(node, dict) and last_key in node:
        target = node[last_key]
        if isinstance(target, dict) and "value" in target:
            target["value"] = new_value
            return True
    return False


def get_flat_decisions() -> Dict[str, Any]:
    """将所有决策变量展平为 {dotted_path: value} 字典。

    方便 RL Agent 作为观测/动作空间的参考。
    只包含有 .value 字段的叶子节点。
    """
    result = {}

    def _walk(node, prefix):
        if not isinstance(node, dict):
            return
        if "value" in node and "type" in node:
            result[prefix] = node["value"]
            return
        for key, child in node.items():
            # 跳过纯数据字典 (如 demand data, product_to_mixer.data)
            if key == "data":
                continue
            if key == "description":
                continue
            path = f"{prefix}.{key}" if prefix else key
            # 如果子节点是带有 "data" 键的字典，展开 data 内容
            if isinstance(child, dict) and "data" in child and isinstance(child["data"], dict):
                for dk, dv in child["data"].items():
                    result[f"{path}.{dk}"] = dv
            else:
                _walk(child, path)

    _walk(DECISION_CONFIG, "")
    return result


def get_decision_space_summary() -> Dict[str, Any]:
    """返回决策空间的结构化摘要，供 RL Agent 构建动作空间。

    返回值:
        {
            "total_continuous": int,       # 连续变量数量
            "total_categorical": int,      # 类别变量数量
            "total_bool": int,             # 布尔变量数量
            "variables": [
                {
                    "path": "purchasing.supplier_decisions.s_pack.quality",
                    "type": "categorical",
                    "options": ["High", "Middle", "Poor"],
                    "current_value": "High",
                },
                ...
            ],
        }
    """
    variables = []
    counts = {"continuous": 0, "categorical": 0, "bool": 0, "int": 0}

    def _walk(node, prefix):
        if not isinstance(node, dict):
            return
        if "value" in node and "type" in node:
            var = {
                "path": prefix,
                "type": node["type"],
                "current_value": node["value"],
            }
            if "options" in node:
                var["options"] = node["options"]
            if "range" in node:
                var["range"] = node["range"]
            if "description" in node:
                var["description"] = node["description"]

            vt = node["type"]
            if vt in ("float",):
                counts["continuous"] += 1
            elif vt in ("int",):
                counts["int"] += 1
            elif vt == "categorical":
                counts["categorical"] += 1
            elif vt == "bool":
                counts["bool"] += 1

            variables.append(var)
            return
        for key, child in node.items():
            if key in ("data", "description"):
                continue
            path = f"{prefix}.{key}" if prefix else key
            _walk(child, path)

    _walk(DECISION_CONFIG, "")
    return {
        "total_continuous": counts["continuous"],
        "total_int": counts["int"],
        "total_categorical": counts["categorical"],
        "total_bool": counts["bool"],
        "total": sum(counts.values()),
        "variables": variables,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 决策验证
# ═══════════════════════════════════════════════════════════════════════════════

def validate_decisions(config: Dict = None) -> List[str]:
    """验证决策配置的合法性。返回错误列表，空列表表示全部合法。

    检查项:
      - 类别变量的值是否在允许选项中
      - 数值变量是否在允许范围内
      - 布尔变量是否为 bool 类型
    """
    if config is None:
        config = DECISION_CONFIG

    errors = []

    def _validate(node, prefix):
        if not isinstance(node, dict):
            return
        if "value" in node and "type" in node:
            val = node["value"]
            vt = node["type"]

            if vt == "categorical" and "options" in node:
                if val not in node["options"]:
                    errors.append(
                        f"{prefix}: value '{val}' not in options {node['options']}"
                    )

            elif vt in ("float", "int") and "range" in node:
                lo, hi = node["range"]
                if not (lo <= val <= hi):
                    errors.append(
                        f"{prefix}: value {val} out of range [{lo}, {hi}]"
                    )

            elif vt == "bool":
                if not isinstance(val, bool):
                    errors.append(
                        f"{prefix}: expected bool, got {type(val).__name__}"
                    )

            elif vt.startswith("list["):
                if not isinstance(val, list):
                    errors.append(
                        f"{prefix}: expected list, got {type(val).__name__}"
                    )
                elif vt == "list[float]" and "sum_to_one" in node and node["sum_to_one"]:
                    total = sum(val)
                    if abs(total - 1.0) > 1e-6:
                        errors.append(
                            f"{prefix}: weights sum to {total:.6f}, expected 1.0"
                        )
            return

        for key, child in node.items():
            if key in ("data", "description"):
                continue
            path = f"{prefix}.{key}" if prefix else key
            _validate(child, path)

    _validate(config, "")
    return errors


# ═══════════════════════════════════════════════════════════════════════════════
# 与原始模块的同步函数
# ═══════════════════════════════════════════════════════════════════════════════

def sync_to_modules():
    """将 DECISION_CONFIG 的值同步到各原始模块的决策字典。

    调用此函数后再 import 并运行仿真，确保各模块使用统一决策。

    Returns:
        dict: {"ok": [成功同步的模块列表], "errors": [失败模块及错误信息]}
    """
    result = {"ok": [], "errors": []}

    # ── 同步 purchasing.py ──
    try:
        import purchasing
        for sid in SUPPLIER_IDS:
            src = DECISION_CONFIG["purchasing"]["supplier_decisions"][sid]
            purchasing.SUPPLIER_DECISIONS[sid] = {
                k: src[k]["value"] for k in src
            }
        for cid in COMPONENT_IDS:
            purchasing.DUAL_SOURCING[cid] = \
                DECISION_CONFIG["purchasing"]["dual_sourcing"][cid]["value"]
        result["ok"].append("purchasing")
    except Exception as e:
        result["errors"].append(f"purchasing: {e}")

    # ── 同步 sales.py ──
    try:
        import sales
        for cid in CUSTOMER_IDS:
            src = DECISION_CONFIG["sales"]["customer_decisions"][cid]
            sales.CUSTOMER_DECISIONS[cid] = {
                k: src[k]["value"] for k in src
            }
        sales.SHORTAGE_RULE = DECISION_CONFIG["sales"]["shortage_settings"]["rule"]["value"]
        sales.CUSTOMER_PRIORITY = {
            cid: DECISION_CONFIG["sales"]["shortage_settings"]["customer_priority"][cid]["value"]
            for cid in CUSTOMER_IDS
        }
        sales.DAILY_DEMAND_WEIGHTS = list(
            DECISION_CONFIG["sales"]["daily_demand_settings"]["weights"]["value"]
        )
        sales.DAILY_DEMAND_NOISE_STD = \
            DECISION_CONFIG["sales"]["daily_demand_settings"]["noise_std"]["value"]
        sales.VMI_COST_ANNUAL = \
            DECISION_CONFIG["sales"]["promo_settings"]["vmi_cost_annual"]["value"]
        sales.VALUE_FOR_MONEY_CUSTOMERS = \
            DECISION_CONFIG["sales"]["promo_settings"]["value_for_money_customers"]["data"]
        sales.SLOWMOVER_COMBINATIONS = \
            DECISION_CONFIG["sales"]["promo_settings"]["slowmover_combinations"]["data"]
        sales.PROMO_DEMAND_UPLIFT = dict(
            DECISION_CONFIG["sales"]["promo_settings"]["demand_uplift"]["data"]
        )
        sales.ROUND3_PROMO_PRESSURE = \
            DECISION_CONFIG["sales"]["promo_settings"]["round3_promo_pressure"]["value"]
        sales.WEEKLY_DEMAND_PIECES = dict(
            DECISION_CONFIG["sales"]["weekly_demand_pieces"]["data"]
        )
        result["ok"].append("sales")
    except Exception as e:
        result["errors"].append(f"sales: {e}")

    # ── 同步 operations.py ──
    try:
        import operations
        ops = DECISION_CONFIG["operations"]
        # inbound
        for name in ops["inbound"]["raw_materials_inspection"]:
            operations.OPERATIONS_CONFIG["inbound"]["raw_materials_inspection"][name] = \
                ops["inbound"]["raw_materials_inspection"][name]["value"]
        for k in ops["inbound"]["raw_materials_warehouse"]:
            operations.OPERATIONS_CONFIG["inbound"]["raw_materials_warehouse"][k] = \
                ops["inbound"]["raw_materials_warehouse"][k]["value"]
        # mixing
        operations.OPERATIONS_CONFIG["mixing"]["current_mixer"] = \
            ops["mixing"]["current_mixer"]["value"]
        operations.OPERATIONS_CONFIG["mixing"]["product_to_mixer"] = {
            pid: ops["mixing"]["product_to_mixer"][pid]["value"]
            for pid in PRODUCT_IDS
        }
        operations.OPERATIONS_CONFIG["mixing"]["production_sequence"] = list(
            ops["mixing"]["production_sequence"]["value"]
        )
        # bottling
        for k in ops["bottling"]["general_settings"]:
            operations.OPERATIONS_CONFIG["bottling"]["general_settings"][k] = \
                ops["bottling"]["general_settings"][k]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["current_line"] = \
            ops["bottling"]["current_line"]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["shifts_per_week"] = \
            ops["bottling"]["shifts_per_week"]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["smed_action"] = \
            ops["bottling"]["smed_action"]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["increase_speed"] = \
            ops["bottling"]["increase_speed"]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["max_overtime_hours"] = \
            ops["bottling"]["max_overtime_hours"]["value"]
        operations.OPERATIONS_CONFIG["bottling"]["product_to_line"] = {
            pid: ops["bottling"]["product_to_line"][pid]["value"]
            for pid in PRODUCT_IDS
        }
        # outbound
        for k in ops["outbound"]["finished_goods_warehouse"]:
            operations.OPERATIONS_CONFIG["outbound"]["finished_goods_warehouse"][k] = \
                ops["outbound"]["finished_goods_warehouse"][k]["value"]
        result["ok"].append("operations")
    except Exception as e:
        result["errors"].append(f"operations: {e}")

    # ── 同步 supplychain.py ──
    try:
        import supplychain
        sc = DECISION_CONFIG["supply_chain"]
        for cid in COMPONENT_IDS:
            supplychain.SUPPLY_CHAIN_CONFIG["safety_stock_weeks"][cid] = \
                sc["safety_stock_weeks"][cid]["value"]
            supplychain.SUPPLY_CHAIN_CONFIG["lot_size_weeks"][cid] = \
                sc["lot_size_weeks"][cid]["value"]
        supplychain.SUPPLY_CHAIN_CONFIG["frozen_period_weeks"] = \
            sc["frozen_period_weeks"]["value"]
        supplychain.SUPPLY_CHAIN_CONFIG["production_interval_weeks"] = \
            sc["production_interval_weeks"]["value"]
        for pid in PRODUCT_IDS:
            supplychain.SUPPLY_CHAIN_CONFIG["fg_safety_stock_weeks"][pid] = \
                sc["fg_safety_stock_weeks"][pid]["value"]
            supplychain.SUPPLY_CHAIN_CONFIG["fg_production_intervals_days"][pid] = \
                sc["fg_production_intervals_days"][pid]["value"]
        result["ok"].append("supplychain")
    except Exception as e:
        result["errors"].append(f"supplychain: {e}")

    # ── 同步 config.py ──
    try:
        import config
        g = DECISION_CONFIG["global"]
        config.RANDOM_SEED = g["random_seed"]["value"]
        config.WEEKS_PER_ROUND = g["weeks_per_round"]["value"]
        config.USE_NOISE = g["use_noise"]["value"]
        config.DEMAND_NOISE_STD = g["noise_params"]["demand_noise_std"]["value"]
        config.PRODUCTION_NOISE_STD = g["noise_params"]["production_noise_std"]["value"]
        config.COST_NOISE_STD = g["noise_params"]["cost_noise_std"]["value"]
        result["ok"].append("config")
    except Exception as e:
        result["errors"].append(f"config: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 别名函数（与文档中使用的名称保持一致，定义在 sync_to_modules 之后）
# ═══════════════════════════════════════════════════════════════════════════════

get_decision = get_value
set_decision = set_value
apply_decisions = sync_to_modules


# ═══════════════════════════════════════════════════════════════════════════════
# 模块自检
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("TFC Decision Configuration — 决策变量自检")
    print("=" * 70)

    # 1) 展平决策
    flat = get_flat_decisions()
    print(f"\n总决策变量数 (含数据): {len(flat)}")

    # 2) 决策空间摘要
    summary = get_decision_space_summary()
    print(f"\n决策空间摘要:")
    print(f"  连续变量 (float):   {summary['total_continuous']}")
    print(f"  整数变量 (int):      {summary['total_int']}")
    print(f"  类别变量 (categorical): {summary['total_categorical']}")
    print(f"  布尔变量 (bool):     {summary['total_bool']}")
    print(f"  总计:                {summary['total']}")

    # 3) 验证
    errors = validate_decisions()
    if errors:
        print(f"\n[FAIL] Validation failed ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"\n[PASS] All decision variables validated")

    # 4) 按模块展示变量列表
    print(f"\n{'─' * 70}")
    for module_name in ["purchasing", "sales", "operations", "supply_chain", "global"]:
        module_vars = [v for v in summary["variables"] if v["path"].startswith(module_name)]
        print(f"\n[{module_name}] ({len(module_vars)} variables):")
        for v in module_vars:
            print(f"   {v['path']:<65} = {str(v['current_value']):<20} [{v['type']}]")
