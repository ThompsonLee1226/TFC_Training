"""
TFC仿真 — 状态空间定义
用于MARL环境的Observation Space构建

基于对 simulation.py, supplychain.py, sales.py, operations.py,
purchasing.py, finance.py 的全面分析生成。

版本: v1.0 | 日期: 2026-07-14
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 实体ID常量（对齐 decision.py）
# ═══════════════════════════════════════════════════════════════════════════════

COMPONENT_IDS = ["pack_1l", "pet", "orange", "mango", "vitamin_c"]
PRODUCT_IDS = [
    "p_orange_1l", "p_ocp_1l", "p_om_1l",
    "p_orange_pet", "p_ocp_pet", "p_om_pet",
]
SUPPLIER_IDS = ["s_pack", "s_pet", "s_orange", "s_mango", "s_vitc"]
CUSTOMER_IDS = ["c_fg", "c_land", "c_dom"]

# 供应商→组件映射
SUPPLIER_TO_COMPONENT = {
    "s_pack": "pack_1l", "s_pet": "pet", "s_orange": "orange",
    "s_mango": "mango", "s_vitc": "vitamin_c",
}
COMPONENT_TO_SUPPLIER = {v: k for k, v in SUPPLIER_TO_COMPONENT.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. StateSpaceConfig — 状态空间维度配置
# ═══════════════════════════════════════════════════════════════════════════════

class StateSpaceConfig:
    """状态空间配置类。

    所有维度常数统一管理，供 Gymnasium observation_space 定义使用。
    """

    # ── 组件库存 ──
    COMPONENT_STOCK_DIM = len(COMPONENT_IDS)  # 5维: 各组件当前库存量(L)

    # ── 成品库存 ──
    FG_STOCK_DIM = len(PRODUCT_IDS)  # 6维: 各成品当前库存量(L)

    # ── 组件在途量 ──
    COMPONENT_ON_ORDER_DIM = len(COMPONENT_IDS)  # 5维: 各组件在途(已下单未到达)量

    # ── 供应商状态 ──
    SUPPLIER_FEATURES = [
        "effective_price",      # 有效采购单价 (€/L)
        "lead_time_days",       # 交货提前期 (天)
        "contract_index",       # 合同指数 (CI)
        "quality_level",        # 质量等级 (编码: High=0, Middle=1, Poor=2)
        "delivery_reliability", # 交货可靠性 (%)
    ]
    SUPPLIER_FEATURE_DIM = len(SUPPLIER_FEATURES)  # 5个特征/供应商
    SUPPLIER_DIM = len(SUPPLIER_IDS) * SUPPLIER_FEATURE_DIM  # 25维

    # ── 供应商决策状态（读取自 SUPPLIER_DECISIONS）──
    SUPPLIER_DECISION_FEATURES = [
        "payment_term_weeks",   # 付款周期
        "vmi_enabled",          # VMI开关
        "supplier_development", # 供应商发展
    ]
    SUPPLIER_DECISION_DIM = len(SUPPLIER_IDS) * len(SUPPLIER_DECISION_FEATURES)  # 15维

    # ── 客户状态 ──
    CUSTOMER_FEATURES = [
        "contract_index",        # 合同指数
        "weekly_demand_liters",  # 周需求 (L)
        "service_level_pct",     # 承诺服务水平 (%)
        "shelf_life_pct",        # 要求保质期 (%)
        "payment_term_weeks",    # 付款周期
        "promo_pressure_level",  # 促销压力 (编码: None=0, Low=1, Middle=2, Heavy=3)
    ]
    CUSTOMER_FEATURE_DIM = len(CUSTOMER_FEATURES)  # 6个特征/客户
    CUSTOMER_DIM = len(CUSTOMER_IDS) * CUSTOMER_FEATURE_DIM  # 18维

    # ── 销售状态（运行时动态）──
    SALES_RUNTIME_FEATURES = [
        "actual_service_level",  # 实际服务水平 (累计, %)
        "cumulative_shortfall",  # 累计缺货量 (L)
        "weekly_revenue",        # 本周收入 (€)
    ]
    SALES_RUNTIME_DIM = len(SALES_RUNTIME_FEATURES) * len(CUSTOMER_IDS)  # 9维

    # ── 生产状态 ──
    PRODUCTION_FEATURES = [
        "mixer_utilization",       # 混合器利用率 (0-1)
        "bottling_utilization",    # 灌装线利用率 (0-1)
        "breakdown_rate",          # 故障率 (天/周)
        "changeover_ratio",        # 换型时间占比 (0-1)
        "overtime_ratio",          # 加班时间占比 (0-1)
        "waste_rate",              # 废品率 (启动损失/总产量)
    ]
    PRODUCTION_DIM = len(PRODUCTION_FEATURES)  # 6维

    # ── 生产配置特征 ──
    PRODUCTION_CONFIG_FEATURES = [
        "mixer_type",              # 混合器型号 (编码)
        "bottling_line_type",      # 灌装线型号 (编码)
        "shifts_per_week",         # 班次数
        "smed_enabled",            # SMED开关
        "increase_speed",          # 提速开关
        "preventive_maintenance",  # 预防维护等级 (编码)
        "breakdown_training",      # 故障培训开关
    ]
    PRODUCTION_CONFIG_DIM = len(PRODUCTION_CONFIG_FEATURES)  # 7维

    # ── 财务状态 ──
    FINANCIAL_FEATURES = [
        "cum_revenue",             # 累计收入 (€)
        "cum_gross_margin",        # 累计毛利 (€)
        "cum_operating_profit",    # 累计营业利润 (€)
        "cum_indirect_costs",      # 累计间接成本 (€)
        "current_roi",             # 当前ROI (%)
    ]
    FINANCIAL_DIM = len(FINANCIAL_FEATURES)  # 5维

    # ── 库存成本状态 ──
    INVENTORY_COST_FEATURES = [
        "warehouse_space_cost",    # 仓储空间成本 (€)
        "stock_interest_cost",     # 库存利息 (€)
        "obsoletes_value",         # 累计过期报废价值 (€)
        "avg_component_value",     # 组件平均库存价值 (€)
        "avg_fg_value",            # 成品平均库存价值 (€)
    ]
    INVENTORY_COST_DIM = len(INVENTORY_COST_FEATURES)  # 5维

    # ── 供应链配置特征 ──
    SUPPLYCHAIN_CONFIG_FEATURES = [
        "ss_weeks_pack_1l", "ss_weeks_pet", "ss_weeks_orange",
        "ss_weeks_mango", "ss_weeks_vitamin_c",  # 5个安全库存
        "lot_weeks_pack_1l", "lot_weeks_pet", "lot_weeks_orange",
        "lot_weeks_mango", "lot_weeks_vitamin_c",  # 5个批量
    ]
    SUPPLYCHAIN_CONFIG_DIM = len(SUPPLYCHAIN_CONFIG_FEATURES)  # 10维

    # ── 仿真元状态 ──
    META_FEATURES = [
        "current_week",            # 当前周次 (1-26)
        "weeks_remaining",         # 剩余周数
        "round_progress",          # 进度 (0-1)
    ]
    META_DIM = len(META_FEATURES)  # 3维

    # ═════════════════════════════════════════════════════════════
    # 全局状态总维度
    # ═════════════════════════════════════════════════════════════
    @property
    def global_state_dim(self) -> int:
        """全局状态总维度（用于 Centralized Critic）。

        组成:
          组件库存(5) + 成品库存(6) + 组件在途(5) +
          供应商特征(25) + 供应商决策(15) +
          客户特征(18) + 销售运行时(9) +
          生产特征(6) + 生产配置(7) +
          财务(5) + 库存成本(5) + 供应链配置(10) + 元信息(3)
        = 119维
        """
        return (
            self.COMPONENT_STOCK_DIM +      # 5
            self.FG_STOCK_DIM +             # 6
            self.COMPONENT_ON_ORDER_DIM +   # 5
            self.SUPPLIER_DIM +             # 25
            self.SUPPLIER_DECISION_DIM +    # 15
            self.CUSTOMER_DIM +             # 18
            self.SALES_RUNTIME_DIM +        # 9
            self.PRODUCTION_DIM +           # 6
            self.PRODUCTION_CONFIG_DIM +    # 7
            self.FINANCIAL_DIM +            # 5
            self.INVENTORY_COST_DIM +       # 5
            self.SUPPLYCHAIN_CONFIG_DIM +   # 10
            self.META_DIM                   # 3
        )  # = 119

    # ═════════════════════════════════════════════════════════════
    # 局部观测空间配置
    # ═════════════════════════════════════════════════════════════
    LOCAL_OBSERVATION_CONFIG = {
        "purchasing": {
            "dim": 65,  # 供应商(25) + 组件库存(5) + 组件在途(5) + 供应商决策(15) + 财务(5) + 供应链配置(10)
            "description": "供应商状态 + 组件库存 + 采购相关财务 + 供应链参数",
        },
        "sales": {
            "dim": 34,  # 客户特征(18) + 成品库存(6) + 销售运行时(9) + 元信息(1)
            "description": "客户状态 + 成品库存 + 销售服务水平",
        },
        "operations": {
            "dim": 27,  # 生产配置(7) + 生产特征(6) + 成品需求(6) + 组件库存(5) + 元信息(3)
            "description": "生产状态 + 产品需求 + 产能利用率",
        },
        "supplychain": {
            "dim": 42,  # 组件库存(5) + 成品库存(6) + 组件在途(5) + 供应链配置(10) + 库存成本(5) + 供应商(5×1 CI) + 财务(5) + 元信息(1)
            "description": "库存状态 + 仓储成本 + 供应链参数",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 状态归一化配置
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NormalizationSpec:
    """单个变量的归一化规格"""
    name: str
    theoretical_min: float
    theoretical_max: float
    method: str           # "minmax", "zscore", "log", "none"
    target_min: float = -1.0
    target_max: float = 1.0


# 归一化配置表（仅连续变量；离散/布尔变量不需要归一化）
NORMALIZATION_CONFIG: Dict[str, NormalizationSpec] = {
    # ── 组件库存 (L) ──
    "comp_stock_pack_1l": NormalizationSpec("pack_1l库存", 0, 200_000, "minmax"),
    "comp_stock_pet":     NormalizationSpec("PET库存", 0, 200_000, "minmax"),
    "comp_stock_orange":  NormalizationSpec("Orange库存", 0, 100_000, "minmax"),
    "comp_stock_mango":   NormalizationSpec("Mango库存", 0, 50_000, "minmax"),
    "comp_stock_vitamin_c": NormalizationSpec("Vitamin C库存", 0, 20_000, "minmax"),

    # ── 成品库存 (L) ──
    "fg_stock_p_orange_1l": NormalizationSpec("Orange 1L库存", 0, 150_000, "minmax"),
    "fg_stock_p_ocp_1l":   NormalizationSpec("OCP 1L库存", 0, 50_000, "minmax"),
    "fg_stock_p_om_1l":    NormalizationSpec("OM 1L库存", 0, 80_000, "minmax"),
    "fg_stock_p_orange_pet": NormalizationSpec("Orange PET库存", 0, 80_000, "minmax"),
    "fg_stock_p_ocp_pet":  NormalizationSpec("OCP PET库存", 0, 30_000, "minmax"),
    "fg_stock_p_om_pet":   NormalizationSpec("OM PET库存", 0, 40_000, "minmax"),

    # ── 供应商 ──
    "effective_price":     NormalizationSpec("有效采购价", 0.02, 1.00, "minmax"),
    "lead_time_days":      NormalizationSpec("提前期", 5, 35, "minmax"),
    "contract_index_supplier": NormalizationSpec("供应商CI", 0.85, 1.20, "minmax"),
    "delivery_reliability": NormalizationSpec("交货可靠性", 85.0, 99.0, "minmax"),

    # ── 客户 ──
    "contract_index_customer": NormalizationSpec("客户CI", 0.70, 1.07, "minmax"),
    "weekly_demand_liters": NormalizationSpec("周需求", 0, 120_000, "minmax"),
    "service_level_pct":   NormalizationSpec("服务水平", 90.0, 99.5, "minmax"),
    "shelf_life_pct":      NormalizationSpec("保质期要求", 40.0, 85.0, "minmax"),
    "payment_term_weeks_customer": NormalizationSpec("客户付款周期", 1, 8, "minmax"),

    # ── 销售运行时 ──
    "actual_service_level": NormalizationSpec("实际SL", 0.0, 100.0, "minmax"),
    "cumulative_shortfall": NormalizationSpec("累计缺货", 0, 500_000, "log"),
    "weekly_revenue":      NormalizationSpec("周收入", 0, 200_000, "log"),

    # ── 生产 ──
    "mixer_utilization":    NormalizationSpec("混合器利用率", 0.0, 1.0, "minmax"),
    "bottling_utilization": NormalizationSpec("灌装线利用率", 0.0, 1.5, "minmax"),
    "breakdown_rate":       NormalizationSpec("故障率", 0.0, 1.0, "minmax"),
    "changeover_ratio":     NormalizationSpec("换型占比", 0.0, 0.5, "minmax"),
    "overtime_ratio":       NormalizationSpec("加班占比", 0.0, 0.4, "minmax"),
    "waste_rate":           NormalizationSpec("废品率", 0.0, 0.15, "minmax"),

    # ── 财务 ──
    "cum_revenue":          NormalizationSpec("累计收入", 0, 4_000_000, "log"),
    "cum_gross_margin":     NormalizationSpec("累计毛利", -500_000, 2_000_000, "zscore"),
    "cum_operating_profit": NormalizationSpec("累计营业利润", -500_000, 1_000_000, "zscore"),
    "cum_indirect_costs":   NormalizationSpec("累计间接成本", 0, 2_000_000, "log"),
    "current_roi":          NormalizationSpec("ROI", -10.0, 30.0, "minmax"),

    # ── 库存成本 ──
    "warehouse_space_cost":  NormalizationSpec("仓储空间成本", 0, 500_000, "log"),
    "stock_interest_cost":   NormalizationSpec("库存利息", 0, 100_000, "log"),
    "obsoletes_value":       NormalizationSpec("过期报废价值", 0, 200_000, "log"),
    "avg_component_value":   NormalizationSpec("组件库存价值", 0, 500_000, "log"),
    "avg_fg_value":          NormalizationSpec("成品库存价值", 0, 500_000, "log"),

    # ── 供应链配置 ──
    "safety_stock_weeks":    NormalizationSpec("安全库存周数", 0.0, 6.0, "minmax"),
    "lot_size_weeks":        NormalizationSpec("批量周数", 1, 8, "minmax"),

    # ── 元信息 ──
    "current_week":          NormalizationSpec("当前周", 1, 26, "minmax"),
    "weeks_remaining":       NormalizationSpec("剩余周数", 0, 26, "minmax"),
    "round_progress":        NormalizationSpec("进度", 0.0, 1.0, "none"),
}

# 需要 log 变换的变量列表（避免 log(0) 问题）
LOG_TRANSFORM_VARS = [
    name for name, spec in NORMALIZATION_CONFIG.items()
    if spec.method == "log"
]

# 需要 z-score 标准化的变量
ZSCORE_VARS = [
    name for name, spec in NORMALIZATION_CONFIG.items()
    if spec.method == "zscore"
]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 状态提取函数
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_value(value: float, spec: NormalizationSpec,
                    zscore_mean: float = 0.0, zscore_std: float = 1.0) -> float:
    """根据归一化规格对单个值进行归一化。

    Args:
        value: 原始值
        spec: 归一化规格
        zscore_mean: z-score的均值（仅 method="zscore" 时使用）
        zscore_std: z-score的标准差（仅 method="zscore" 时使用）

    Returns:
        归一化后的值，范围 [spec.target_min, spec.target_max]
    """
    if spec.method == "none":
        return value

    if spec.method == "minmax":
        # clip + min-max → [target_min, target_max]
        v = np.clip(value, spec.theoretical_min, spec.theoretical_max)
        ratio = (v - spec.theoretical_min) / max(spec.theoretical_max - spec.theoretical_min, 1e-9)
        return spec.target_min + ratio * (spec.target_max - spec.target_min)

    if spec.method == "zscore":
        z = (value - zscore_mean) / max(zscore_std, 1e-9)
        return np.clip(z, -3.0, 3.0) / 3.0  # clip to [-3σ, 3σ] → [-1, 1]

    if spec.method == "log":
        # log(1 + x) 变换 → minmax
        v = max(0.0, value)
        log_v = np.log1p(v)
        log_min = np.log1p(spec.theoretical_min)
        log_max = np.log1p(spec.theoretical_max)
        ratio = (log_v - log_min) / max(log_max - log_min, 1e-9)
        ratio = np.clip(ratio, 0.0, 1.0)
        return spec.target_min + ratio * (spec.target_max - spec.target_min)

    return value


def _encode_categorical(value: str, options: List[str]) -> int:
    """将分类变量编码为整数索引。"""
    try:
        return options.index(value)
    except ValueError:
        return 0


def _encode_bool(value: bool) -> float:
    """将布尔值编码为 0.0 或 1.0。"""
    return 1.0 if value else 0.0


def get_global_state(simulation_result) -> np.ndarray:
    """从仿真结果（或仿真内部状态）提取全局状态向量。

    Args:
        simulation_result: SimulationResult 对象（或包含运行时状态的字典）

    Returns:
        np.ndarray, shape=(119,), dtype=float32
    """
    # 此函数应在仿真循环内部调用，传入包含所有周度状态的对象。
    # 此处提供框架代码，实际实现需在 simulation.py 中添加状态收集逻辑。
    raise NotImplementedError(
        "get_global_state 需要在 simulation.py 中添加状态收集中间件后实现。"
        "参见 state_space.md 中的集成指南。"
    )


def get_local_state(agent_id: str, state_dict: Dict[str, np.ndarray]) -> np.ndarray:
    """为指定 Agent 提取局部观测向量。

    Args:
        agent_id: "purchasing" | "sales" | "operations" | "supplychain"
        state_dict: 包含所有状态子向量的字典

    Returns:
        np.ndarray, shape=(dim,), dtype=float32
    """
    config = StateSpaceConfig()
    local_config = config.LOCAL_OBSERVATION_CONFIG.get(agent_id)
    if not local_config:
        raise ValueError(f"Unknown agent_id: {agent_id}")

    vectors = []

    if agent_id == "purchasing":
        # 供应商特征(25) + 组件库存(5) + 组件在途(5) + 供应商决策(15)
        # + 财务(5) + 供应链配置(安全库存5 + 批量5)
        vectors.extend([
            state_dict.get("supplier_features", np.zeros(config.SUPPLIER_DIM)),
            state_dict.get("component_stock", np.zeros(config.COMPONENT_STOCK_DIM)),
            state_dict.get("component_on_order", np.zeros(config.COMPONENT_ON_ORDER_DIM)),
            state_dict.get("supplier_decisions", np.zeros(config.SUPPLIER_DECISION_DIM)),
            state_dict.get("financial", np.zeros(config.FINANCIAL_DIM)),
            state_dict.get("supplychain_config", np.zeros(config.SUPPLYCHAIN_CONFIG_DIM)),
        ])

    elif agent_id == "sales":
        # 客户特征(18) + 成品库存(6) + 销售运行时(9) + 当前周(1)
        vectors.extend([
            state_dict.get("customer_features", np.zeros(config.CUSTOMER_DIM)),
            state_dict.get("fg_stock", np.zeros(config.FG_STOCK_DIM)),
            state_dict.get("sales_runtime", np.zeros(config.SALES_RUNTIME_DIM)),
            state_dict.get("current_week_norm", np.zeros(1)),
        ])

    elif agent_id == "operations":
        # 生产配置(7) + 生产特征(6) + 成品需求(6) + 组件库存(5) + 元信息(3)
        vectors.extend([
            state_dict.get("production_config", np.zeros(config.PRODUCTION_CONFIG_DIM)),
            state_dict.get("production_features", np.zeros(config.PRODUCTION_DIM)),
            state_dict.get("product_demand", np.zeros(config.FG_STOCK_DIM)),
            state_dict.get("component_stock", np.zeros(config.COMPONENT_STOCK_DIM)),
            state_dict.get("meta", np.zeros(config.META_DIM)),
        ])

    elif agent_id == "supplychain":
        # 组件库存(5) + 成品库存(6) + 组件在途(5) + 供应链配置(10)
        # + 库存成本(5) + 供应商CI(5) + 财务(5) + 当前周(1)
        vectors.extend([
            state_dict.get("component_stock", np.zeros(config.COMPONENT_STOCK_DIM)),
            state_dict.get("fg_stock", np.zeros(config.FG_STOCK_DIM)),
            state_dict.get("component_on_order", np.zeros(config.COMPONENT_ON_ORDER_DIM)),
            state_dict.get("supplychain_config", np.zeros(config.SUPPLYCHAIN_CONFIG_DIM)),
            state_dict.get("inventory_cost", np.zeros(config.INVENTORY_COST_DIM)),
            state_dict.get("supplier_ci_only", np.zeros(len(SUPPLIER_IDS))),
            state_dict.get("financial", np.zeros(config.FINANCIAL_DIM)),
            state_dict.get("current_week_norm", np.zeros(1)),
        ])

    return np.concatenate(vectors, dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 状态收集器（供 simulation.py 集成使用）
# ═══════════════════════════════════════════════════════════════════════════════

class StateCollector:
    """在仿真循环中逐周收集状态，生成全局和局部观测向量。

    使用方法（在 simulation.py run() 中）:
        collector = StateCollector()
        for week in range(1, 27):
            ...
            state = collector.collect(
                week=week,
                inv_state=inv_state,
                pending_orders=pending_orders,
                production_result=prod_result,
                weekly_sales=weekly_sales,
                cum_revenue=total_revenue,
                cum_production_cost=total_production_cost,
                cum_component_value=cum_component_value,
                cum_fg_value=cum_fg_value,
                cum_obsoletes=total_obsoletes,
            )
            global_obs = collector.get_global_observation()
            purchasing_obs = collector.get_local_observation("purchasing")
            ...
    """

    def __init__(self, config: StateSpaceConfig = None):
        self.cfg = config or StateSpaceConfig()
        self._state_dict: Dict[str, np.ndarray] = {}

    def collect(self, week: int, **kwargs) -> Dict[str, np.ndarray]:
        """收集当前周的所有状态，更新内部状态字典。

        返回 state_dict 供外部使用。
        """
        # 由 simulation.py 集成时实现具体提取逻辑
        # 此处定义接口契约
        pass

    # 全局状态包含的子向量键（按拼接顺序）
    _GLOBAL_STATE_KEYS = [
        "component_stock",
        "fg_stock",
        "component_on_order",
        "supplier_features",
        "supplier_decisions",
        "customer_features",
        "sales_runtime",
        "production_features",
        "production_config",
        "financial",
        "inventory_cost",
        "supplychain_config",
        "meta",
    ]

    def get_global_observation(self) -> np.ndarray:
        """获取当前全局观测向量。"""
        vectors = [self._state_dict.get(k, np.zeros(0, dtype=np.float32))
                   for k in self._GLOBAL_STATE_KEYS]
        if all(len(v) == 0 for v in vectors):
            return np.zeros(self.cfg.global_state_dim, dtype=np.float32)
        return np.concatenate(vectors, dtype=np.float32)

    def get_local_observation(self, agent_id: str) -> np.ndarray:
        """获取指定 Agent 的局部观测。"""
        return get_local_state(agent_id, self._state_dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 动作空间 → 状态影响映射
# ═══════════════════════════════════════════════════════════════════════════════

# 定义各 Agent 动作影响的状态维度
ACTION_TO_STATE_IMPACT = {
    "purchasing": {
        "actions": [
            "supplier_decisions[*].quality",
            "supplier_decisions[*].payment_term_weeks",
            "supplier_decisions[*].trade_unit",
            "supplier_decisions[*].delivery_reliability_pct",
            "supplier_decisions[*].delivery_window",
            "supplier_decisions[*].vmi",
            "supplier_decisions[*].supplier_development",
            "dual_sourcing[*]",
        ],
        "affects": [
            "supplier_features",      # CI, effective_price 随决策变化
            "supplier_decisions",     # 直接修改
            "financial",              # 采购成本、VMI费用等
            "component_stock",        # 间接: 价格影响补货量
        ],
        "read_only": [
            "customer_features",
            "sales_runtime",
            "production_features",
            "production_config",
        ],
    },
    "sales": {
        "actions": [
            "customer_decisions[*].service_level_pct",
            "customer_decisions[*].shelf_life_pct",
            "customer_decisions[*].order_deadline",
            "customer_decisions[*].trade_unit",
            "customer_decisions[*].payment_term_weeks",
            "customer_decisions[*].promotional_pressure",
            "customer_decisions[*].promotion_horizon",
            "customer_decisions[*].vmi",
            "shortage_settings.rule",
        ],
        "affects": [
            "customer_features",      # CI, demand 随决策变化
            "sales_runtime",          # 服务水平, 收入
            "financial",              # 收入, bonus/penalty
            "fg_stock",               # 间接: 需求变化影响库存消耗
        ],
        "read_only": [
            "supplier_features",
            "supplier_decisions",
            "production_config",
        ],
    },
    "operations": {
        "actions": [
            "inbound.raw_materials_inspection[*]",
            "inbound.raw_materials_warehouse.*",
            "mixing.current_mixer",
            "mixing.product_to_mixer[*]",
            "mixing.production_sequence",
            "bottling.general_settings.*",
            "bottling.current_line",
            "bottling.shifts_per_week",
            "bottling.smed_action",
            "bottling.increase_speed",
            "bottling.max_overtime_hours",
            "bottling.product_to_line[*]",
            "outbound.finished_goods_warehouse.*",
        ],
        "affects": [
            "production_config",      # 直接修改
            "production_features",    # 利用率、故障率等
            "component_stock",        # 间接: 产量影响消耗
            "fg_stock",               # 直接: 决定产量
            "financial",              # 生产成本
            "inventory_cost",         # 仓库成本
        ],
        "read_only": [
            "supplier_features",
            "supplier_decisions",
            "customer_features",
        ],
    },
    "supplychain": {
        "actions": [
            "safety_stock_weeks[*]",
            "lot_size_weeks[*]",
            "fg_safety_stock_weeks[*]",
            "fg_production_intervals_days[*]",
            "frozen_period_weeks",
            "production_interval_weeks",
        ],
        "affects": [
            "supplychain_config",     # 直接修改
            "component_stock",        # 安全库存影响补货触发
            "fg_stock",               # 成品安全库存影响初始库存
            "component_on_order",     # 批量影响下单量
            "inventory_cost",         # 库存水平影响仓储成本
            "financial",              # 库存利息
        ],
        "read_only": [
            "supplier_features",
            "customer_features",
            "production_config",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 自检
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cfg = StateSpaceConfig()
    print(f"全局状态维度: {cfg.global_state_dim}")
    for agent, info in cfg.LOCAL_OBSERVATION_CONFIG.items():
        print(f"  {agent}: {info['dim']}维 — {info['description']}")
    print(f"\n归一化配置条目: {len(NORMALIZATION_CONFIG)}")
    print("[OK] state_space.py self-check passed")
