"""
MARL 观测构建器 — 仿真状态 → 观测向量
======================================
基于 state_space.py 的 StateSpaceConfig 和 NORMALIZATION_CONFIG，
从决策配置和仿真结果中提取、归一化、拼接观测向量。

支持的观测类型:
  - 全局观测 (Global): 用于 Centralized Critic，~119 维
  - 局部观测 (Local):  每个 Agent 独立观测，维度各异

轮级 step 的观测来源:
  - 决策配置状态:  从 decision.DECISION_CONFIG 读取（CI、价格、库存策略等）
  - 仿真结果状态:  从 simulation.SimulationResult 读取（财务指标）

用法:
  from marl.env.observation_builder import ObservationBuilder

  builder = ObservationBuilder()
  obs_space = builder.build_global_observation_space()  # → Box(119,)
  obs = builder.build_global_obs(config_state, result)    # → np.ndarray(119,)
  obs_local = builder.build_local_obs("purchasing", config_state, result)
"""

import sys
import os
from typing import Dict, Optional
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    import gymnasium as gym
except ImportError:
    gym = None

# 复用 state_space 的配置
from state_space import (
    StateSpaceConfig,
    NORMALIZATION_CONFIG,
    normalize_value,
    COMPONENT_IDS,
    PRODUCT_IDS,
    SUPPLIER_IDS,
    CUSTOMER_IDS,
    SUPPLIER_TO_COMPONENT,
    COMPONENT_TO_SUPPLIER,
)

# 常量
_COMP_ID_LIST = COMPONENT_IDS   # ["pack_1l", "pet", "orange", "mango", "vitamin_c"]
_PROD_ID_LIST = PRODUCT_IDS     # 6 products
_SUPP_ID_LIST = SUPPLIER_IDS    # 5 suppliers
_CUST_ID_LIST = CUSTOMER_IDS    # 3 customers

# 供应商→组件映射
_SUPP_TO_COMP = SUPPLIER_TO_COMPONENT  # {"s_pack": "pack_1l", ...}


# ═══════════════════════════════════════════════════════════════════════════════
# ObservationBuilder
# ═══════════════════════════════════════════════════════════════════════════════

class ObservationBuilder:
    """从仿真状态构建归一化观测向量。

    轮级 step 下，观测由两部分组成:
      1. 决策配置快照 (config state)
      2. 仿真结果快照 (result state)
    """

    def __init__(self):
        self.cfg = StateSpaceConfig()

    # ── 空间定义 ──
    def build_global_observation_space(self) -> "gym.spaces.Box":
        """构建全局观测空间 (Box, shape=(119,), low=-1, high=1)。"""
        if gym is None:
            raise ImportError("gymnasium required. pip install gymnasium")
        return gym.spaces.Box(
            low=-1.0, high=1.0,
            shape=(self.cfg.global_state_dim,),
            dtype=np.float32,
        )

    def build_local_observation_space(self, agent_id: str) -> "gym.spaces.Box":
        """构建指定 Agent 的局部观测空间。"""
        if gym is None:
            raise ImportError("gymnasium required.")
        dim = self.cfg.LOCAL_OBSERVATION_CONFIG[agent_id]["dim"]
        return gym.spaces.Box(
            low=-1.0, high=1.0,
            shape=(dim,),
            dtype=np.float32,
        )

    def build_local_observation_spaces(self) -> Dict[str, "gym.spaces.Box"]:
        """构建所有 Agent 的局部观测空间字典。"""
        return {
            aid: self.build_local_observation_space(aid)
            for aid in self.cfg.LOCAL_OBSERVATION_CONFIG
        }

    # ── 全局观测 ──
    def build_global_obs(
        self,
        config_state: Optional[Dict[str, np.ndarray]] = None,
        result_state: Optional[Dict[str, np.ndarray]] = None,
    ) -> np.ndarray:
        """构建全局观测向量 (119 维)。

        Args:
            config_state: 从 DECISION_CONFIG 提取的配置状态，含:
                supplier_features, supplier_decisions, customer_features,
                production_config, supplychain_config
            result_state: 从 SimulationResult 提取的结果状态，含:
                financial, inventory_cost, sales_runtime,
                component_stock_value, fg_stock_value, meta

        Returns:
            np.ndarray, shape=(119,), dtype=float32, 归一化到 [-1, 1]
        """
        if config_state is None:
            config_state = {}
        if result_state is None:
            result_state = {}

        parts = [
            # ── 配置状态 ──
            config_state.get("supplier_features",
                             np.zeros(self.cfg.SUPPLIER_DIM, dtype=np.float32)),
            config_state.get("supplier_decisions",
                             np.zeros(self.cfg.SUPPLIER_DECISION_DIM, dtype=np.float32)),
            config_state.get("customer_features",
                             np.zeros(self.cfg.CUSTOMER_DIM, dtype=np.float32)),
            config_state.get("production_config",
                             np.zeros(self.cfg.PRODUCTION_CONFIG_DIM, dtype=np.float32)),
            config_state.get("supplychain_config",
                             np.zeros(self.cfg.SUPPLYCHAIN_CONFIG_DIM, dtype=np.float32)),

            # ── 结果状态 ──
            result_state.get("component_stock_value",
                             np.zeros(self.cfg.COMPONENT_STOCK_DIM, dtype=np.float32)),
            result_state.get("fg_stock_value",
                             np.zeros(self.cfg.FG_STOCK_DIM, dtype=np.float32)),
            result_state.get("component_on_order",
                             np.zeros(self.cfg.COMPONENT_ON_ORDER_DIM, dtype=np.float32)),
            result_state.get("sales_runtime",
                             np.zeros(self.cfg.SALES_RUNTIME_DIM, dtype=np.float32)),
            result_state.get("production_features",
                             np.zeros(self.cfg.PRODUCTION_DIM, dtype=np.float32)),
            result_state.get("financial",
                             np.zeros(self.cfg.FINANCIAL_DIM, dtype=np.float32)),
            result_state.get("inventory_cost",
                             np.zeros(self.cfg.INVENTORY_COST_DIM, dtype=np.float32)),
            result_state.get("meta",
                             np.zeros(self.cfg.META_DIM, dtype=np.float32)),
        ]

        obs = np.concatenate(parts).astype(np.float32)
        # clip 到 [-1, 1]
        return np.clip(obs, -1.0, 1.0)

    # ── 局部观测 ──
    def build_local_obs(
        self, agent_id: str,
        config_state: Optional[Dict[str, np.ndarray]] = None,
        result_state: Optional[Dict[str, np.ndarray]] = None,
    ) -> np.ndarray:
        """构建指定 Agent 的局部观测向量。

        Agent 局部观测组成 (per state_space.py LOCAL_OBSERVATION_CONFIG):
          purchasing:   supplier_features(25) + component_stock(5) +
                        component_on_order(5) + supplier_decisions(15) +
                        financial(5) + supplychain_config(10) = 65
          sales:        customer_features(18) + fg_stock(6) +
                        sales_runtime(9) + meta[0:1] = 34
          operations:   production_config(7) + production_features(6) +
                        product_demand(6) + component_stock(5) +
                        meta(3) = 27
          supplychain:  component_stock(5) + fg_stock(6) +
                        component_on_order(5) + supplychain_config(10) +
                        inventory_cost(5) + supplier_ci_only(5) +
                        financial(5) + meta[0:1] = 42
        """
        if config_state is None:
            config_state = {}
        if result_state is None:
            result_state = {}

        # 公共子向量
        comp_stock = config_state.get("component_stock_value",
                                       result_state.get("component_stock_value",
                                       np.zeros(self.cfg.COMPONENT_STOCK_DIM, dtype=np.float32)))
        fg_stock = config_state.get("fg_stock_value",
                                     result_state.get("fg_stock_value",
                                     np.zeros(self.cfg.FG_STOCK_DIM, dtype=np.float32)))
        comp_on_order = result_state.get("component_on_order",
                                         np.zeros(self.cfg.COMPONENT_ON_ORDER_DIM, dtype=np.float32))
        supplier_feat = config_state.get("supplier_features",
                                         np.zeros(self.cfg.SUPPLIER_DIM, dtype=np.float32))
        supplier_dec = config_state.get("supplier_decisions",
                                        np.zeros(self.cfg.SUPPLIER_DECISION_DIM, dtype=np.float32))
        customer_feat = config_state.get("customer_features",
                                         np.zeros(self.cfg.CUSTOMER_DIM, dtype=np.float32))
        sales_rt = result_state.get("sales_runtime",
                                    np.zeros(self.cfg.SALES_RUNTIME_DIM, dtype=np.float32))
        prod_feat = result_state.get("production_features",
                                     np.zeros(self.cfg.PRODUCTION_DIM, dtype=np.float32))
        prod_cfg = config_state.get("production_config",
                                    np.zeros(self.cfg.PRODUCTION_CONFIG_DIM, dtype=np.float32))
        financial = result_state.get("financial",
                                     np.zeros(self.cfg.FINANCIAL_DIM, dtype=np.float32))
        inv_cost = result_state.get("inventory_cost",
                                    np.zeros(self.cfg.INVENTORY_COST_DIM, dtype=np.float32))
        sc_cfg = config_state.get("supplychain_config",
                                  np.zeros(self.cfg.SUPPLYCHAIN_CONFIG_DIM, dtype=np.float32))
        meta = result_state.get("meta", np.zeros(self.cfg.META_DIM, dtype=np.float32))
        supplier_ci = config_state.get("supplier_ci_only",
                                       np.zeros(len(_SUPP_ID_LIST), dtype=np.float32))

        # 构建需求向量 (6 products — 标准化后的周需求)
        product_demand = result_state.get("product_demand",
                                          np.zeros(self.cfg.FG_STOCK_DIM, dtype=np.float32))

        if agent_id == "purchasing":
            parts = [supplier_feat, comp_stock, comp_on_order, supplier_dec,
                     financial, sc_cfg]

        elif agent_id == "sales":
            parts = [customer_feat, fg_stock, sales_rt, meta[0:1]]

        elif agent_id == "operations":
            parts = [prod_cfg, prod_feat, product_demand, comp_stock, meta]

        elif agent_id == "supplychain":
            parts = [comp_stock, fg_stock, comp_on_order, sc_cfg,
                     inv_cost, supplier_ci, financial, meta[0:1]]

        else:
            raise ValueError(f"Unknown agent_id: {agent_id}")

        obs = np.concatenate(parts).astype(np.float32)
        return np.clip(obs, -1.0, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 状态提取函数 — 从 DECISION_CONFIG 和 SimulationResult 构建子向量
# ═══════════════════════════════════════════════════════════════════════════════

def extract_config_state() -> Dict[str, np.ndarray]:
    """从当前 decision.DECISION_CONFIG 提取所有配置相关的状态子向量。

    Returns:
        {
            "supplier_features":  np.ndarray(25,),  # 5 suppliers × 5 features
            "supplier_decisions": np.ndarray(15,),  # 5 suppliers × 3 decisions
            "customer_features":  np.ndarray(18,),  # 3 customers × 6 features
            "production_config":  np.ndarray(7,),
            "supplychain_config": np.ndarray(10,),
            "supplier_ci_only":   np.ndarray(5,),   # 仅供应商CI
        }
    """
    # 延迟导入以避免循环依赖
    from decision import get_value as _get
    import purchasing as _purch
    import sales as _sales

    # ── 供应商特征 (5 suppliers × 5 features = 25) ──
    # features: effective_price, lead_time_days, contract_index, quality_level, delivery_reliability
    supplier_features = np.zeros(5 * 5, dtype=np.float32)
    for i, sid in enumerate(_SUPP_ID_LIST):
        base = i * 5
        # effective_price
        raw_price = _purch.get_effective_purchase_price(sid)
        supplier_features[base + 0] = normalize_value(
            raw_price, NORMALIZATION_CONFIG["effective_price"])
        # lead_time_days
        raw_lt = _purch.get_supplier_lead_time(sid)
        supplier_features[base + 1] = normalize_value(
            raw_lt, NORMALIZATION_CONFIG["lead_time_days"])
        # contract_index
        raw_ci = _purch.predict_supplier_ci(sid)
        supplier_features[base + 2] = normalize_value(
            raw_ci, NORMALIZATION_CONFIG["contract_index_supplier"])
        # quality_level (categorical → one-hot-ish: 0.0=High, 0.5=Middle, 1.0=Poor)
        quality = _get(f"purchasing.supplier_decisions.{sid}.quality") or "High"
        quality_map = {"High": -1.0, "Middle": 0.0, "Poor": 1.0}
        supplier_features[base + 3] = quality_map.get(quality, -1.0)
        # delivery_reliability
        raw_rel = _get(f"purchasing.supplier_decisions.{sid}.delivery_reliability_pct") or 96.0
        supplier_features[base + 4] = normalize_value(
            raw_rel, NORMALIZATION_CONFIG["delivery_reliability"])

    # ── 供应商决策状态 (5 suppliers × 3 features = 15) ──
    # features: payment_term_weeks, vmi_enabled, supplier_development
    supplier_decisions = np.zeros(5 * 3, dtype=np.float32)
    for i, sid in enumerate(_SUPP_ID_LIST):
        base = i * 3
        pt = _get(f"purchasing.supplier_decisions.{sid}.payment_term_weeks") or 4
        supplier_decisions[base + 0] = normalize_value(
            pt, NORMALIZATION_CONFIG["payment_term_weeks_customer"])  # reusing 1-8 range
        vmi = _get(f"purchasing.supplier_decisions.{sid}.vmi") or False
        supplier_decisions[base + 1] = 1.0 if vmi else -1.0
        sd = _get(f"purchasing.supplier_decisions.{sid}.supplier_development") or False
        supplier_decisions[base + 2] = 1.0 if sd else -1.0

    # ── 客户特征 (3 customers × 6 features = 18) ──
    # features: contract_index, weekly_demand_liters, service_level_pct,
    #           shelf_life_pct, payment_term_weeks, promo_pressure_level
    customer_features = np.zeros(3 * 6, dtype=np.float32)
    for i, cid in enumerate(_CUST_ID_LIST):
        base = i * 6
        # contract_index
        raw_ci = _sales.predict_customer_ci(cid)
        customer_features[base + 0] = normalize_value(
            raw_ci, NORMALIZATION_CONFIG["contract_index_customer"])
        # weekly_demand_liters (sum across products for this customer)
        weekly_demand = _sales.weekly_demand_by_customer().get(cid, 0.0)
        customer_features[base + 1] = normalize_value(
            weekly_demand, NORMALIZATION_CONFIG["weekly_demand_liters"])
        # service_level_pct
        sl = _get(f"sales.customer_decisions.{cid}.service_level_pct") or 95.0
        customer_features[base + 2] = normalize_value(
            sl, NORMALIZATION_CONFIG["service_level_pct"])
        # shelf_life_pct
        slf = _get(f"sales.customer_decisions.{cid}.shelf_life_pct") or 75.0
        customer_features[base + 3] = normalize_value(
            slf, NORMALIZATION_CONFIG["shelf_life_pct"])
        # payment_term_weeks
        pt = _get(f"sales.customer_decisions.{cid}.payment_term_weeks") or 4
        customer_features[base + 4] = normalize_value(
            pt, NORMALIZATION_CONFIG["payment_term_weeks_customer"])
        # promo_pressure_level (None=0, Low=1, Middle=2, Heavy=3 → map to [-1, 1])
        promo_map = {"None": -1.0, "Low": -0.33, "Middle": 0.33, "Heavy": 1.0}
        promo = _get(f"sales.customer_decisions.{cid}.promotional_pressure") or "Middle"
        customer_features[base + 5] = promo_map.get(promo, 0.0)

    # ── 生产配置 (7) ──
    # features: mixer_type, bottling_line_type, shifts_per_week, smed_enabled,
    #           increase_speed, preventive_maintenance, breakdown_training
    production_config = np.zeros(7, dtype=np.float32)
    mixer_map = {"Fruitmix MQ": -1.0, "MegaChurn 20": 0.0, "FMM 4000": 1.0}
    mixer = _get("operations.mixing.current_mixer") or "Fruitmix MQ"
    production_config[0] = mixer_map.get(mixer, -1.0)

    line_map = {"Swiss Fill 2": -1.0, "TopSpeed 1": -0.33,
                "MultiFlex 1": 0.33, "Swiss Fill 1": 1.0}
    line = _get("operations.bottling.current_line") or "Swiss Fill 2"
    production_config[1] = line_map.get(line, -1.0)

    shifts = _get("operations.bottling.shifts_per_week") or 2
    production_config[2] = normalize_value(shifts, NormalizationSpec(
        "shifts", 1, 5, "minmax"))

    smed = _get("operations.bottling.smed_action") or False
    production_config[3] = 1.0 if smed else -1.0

    speed = _get("operations.bottling.increase_speed") or False
    production_config[4] = 1.0 if speed else -1.0

    maint_map = {"None": -1.0, "A little": 0.0, "A lot": 1.0}
    maint = _get("operations.bottling.general_settings.preventive_maintenance") or "A little"
    production_config[5] = maint_map.get(maint, 0.0)

    train = _get("operations.bottling.general_settings.solve_breakdowns_training") or "Yes"
    production_config[6] = 1.0 if train == "Yes" else -1.0

    # ── 供应链配置 (10) ──
    # features: 5 safety_stock_weeks + 5 lot_size_weeks (简化，不含 fg params)
    supplychain_config = np.zeros(10, dtype=np.float32)
    for j, cid in enumerate(_COMP_ID_LIST):
        ss = _get(f"supply_chain.safety_stock_weeks.{cid}") or 1.5
        supplychain_config[j] = normalize_value(
            ss, NORMALIZATION_CONFIG["safety_stock_weeks"])
    for j, cid in enumerate(_COMP_ID_LIST):
        lot = _get(f"supply_chain.lot_size_weeks.{cid}") or 3
        supplychain_config[5 + j] = normalize_value(
            lot, NORMALIZATION_CONFIG["lot_size_weeks"])

    # ── 供应商 CI only (5) ──
    supplier_ci_only = np.zeros(5, dtype=np.float32)
    for i, sid in enumerate(_SUPP_ID_LIST):
        raw_ci = _purch.predict_supplier_ci(sid)
        supplier_ci_only[i] = normalize_value(
            raw_ci, NORMALIZATION_CONFIG["contract_index_supplier"])

    return {
        "supplier_features": supplier_features,
        "supplier_decisions": supplier_decisions,
        "customer_features": customer_features,
        "production_config": production_config,
        "supplychain_config": supplychain_config,
        "supplier_ci_only": supplier_ci_only,
    }


def extract_result_state(result, current_round: int = 1) -> Dict[str, np.ndarray]:
    """从 SimulationResult 提取结果状态子向量。

    Args:
        result: simulation.SimulationResult 对象
        current_round: 当前轮次

    Returns:
        {
            "component_stock_value": np.ndarray(5,),
            "fg_stock_value":        np.ndarray(6,),
            "component_on_order":    np.ndarray(5,),
            "sales_runtime":         np.ndarray(9,),
            "production_features":   np.ndarray(6,),
            "financial":             np.ndarray(5,),
            "inventory_cost":        np.ndarray(5,),
            "meta":                  np.ndarray(3,),
            "product_demand":        np.ndarray(6,),
        }
    """
    from config import WEEKS_PER_ROUND

    pl = result.pl
    inv = result.inv

    # ── 组件库存价值 (5) — 从 Investment 中的 inventory_components ──
    # 无法拆分为单个组件，平均分配
    comp_stock_value = np.zeros(5, dtype=np.float32)
    avg_per_comp = inv.inventory_components / max(len(_COMP_ID_LIST), 1)
    for i in range(5):
        comp_stock_value[i] = normalize_value(
            avg_per_comp, NORMALIZATION_CONFIG["avg_component_value"])

    # ── 成品库存价值 (6) ──
    fg_stock_value = np.zeros(6, dtype=np.float32)
    avg_per_fg = inv.inventory_finished_goods / max(len(_PROD_ID_LIST), 1)
    for i in range(6):
        fg_stock_value[i] = normalize_value(
            avg_per_fg, NORMALIZATION_CONFIG["avg_fg_value"])

    # ── 组件在途量 (5) — 轮级后半周不可见，用零填充 ──
    component_on_order = np.zeros(5, dtype=np.float32)

    # ── 销售运行时 (9) — 3 customers × 3 features ──
    # features: actual_service_level, cumulative_shortfall, weekly_revenue
    sales_runtime = np.zeros(9, dtype=np.float32)
    # 从 kpi_values 中获取
    sl = result.kpi_values.get("service_level", 95.0)
    revenue = pl.contracted_sales_revenue
    for i in range(3):
        base = i * 3
        sales_runtime[base + 0] = normalize_value(
            sl, NORMALIZATION_CONFIG["actual_service_level"])
        sales_runtime[base + 1] = 0.0  # shortfall not available in round-level
        rev_per_cust = revenue / 3.0  # approximate
        sales_runtime[base + 2] = normalize_value(
            rev_per_cust, NORMALIZATION_CONFIG["weekly_revenue"])

    # ── 生产特征 (6) — 轮级半后不可见，用中性值 ──
    production_features = np.zeros(6, dtype=np.float32)

    # ── 财务 (5) ──
    # features: cum_revenue, cum_gross_margin, cum_operating_profit,
    #           cum_indirect_costs, current_roi
    financial = np.zeros(5, dtype=np.float32)
    financial[0] = normalize_value(
        pl.total_revenue, NORMALIZATION_CONFIG["cum_revenue"])
    financial[1] = normalize_value(
        pl.gross_margin, NORMALIZATION_CONFIG["cum_gross_margin"])
    financial[2] = normalize_value(
        pl.operating_profit, NORMALIZATION_CONFIG["cum_operating_profit"])
    financial[3] = normalize_value(
        pl.indirect_costs, NORMALIZATION_CONFIG["cum_indirect_costs"])
    financial[4] = normalize_value(
        result.roi, NORMALIZATION_CONFIG["current_roi"])

    # ── 库存成本 (5) ──
    inventory_cost = np.zeros(5, dtype=np.float32)
    inventory_cost[0] = normalize_value(
        pl.stock_costs_space, NORMALIZATION_CONFIG["warehouse_space_cost"])
    inventory_cost[1] = normalize_value(
        pl.stock_costs_interest, NORMALIZATION_CONFIG["stock_interest_cost"])
    inventory_cost[2] = normalize_value(
        pl.stock_costs_risk, NORMALIZATION_CONFIG["obsoletes_value"])
    inventory_cost[3] = normalize_value(
        inv.inventory_components, NORMALIZATION_CONFIG["avg_component_value"])
    inventory_cost[4] = normalize_value(
        inv.inventory_finished_goods, NORMALIZATION_CONFIG["avg_fg_value"])

    # ── Meta (3) ──
    meta = np.zeros(3, dtype=np.float32)
    meta[0] = normalize_value(
        current_round * WEEKS_PER_ROUND, NORMALIZATION_CONFIG["current_week"])
    meta[1] = normalize_value(
        max(0, (4 - current_round) * WEEKS_PER_ROUND),
        NORMALIZATION_CONFIG["weeks_remaining"])
    meta[2] = current_round / 4.0  # round_progress

    # ── 产品需求 (6) — 从 kpi 或固定值 ──
    product_demand = np.zeros(6, dtype=np.float32)

    return {
        "component_stock_value": comp_stock_value,
        "fg_stock_value": fg_stock_value,
        "component_on_order": component_on_order,
        "sales_runtime": sales_runtime,
        "production_features": production_features,
        "financial": financial,
        "inventory_cost": inventory_cost,
        "meta": meta,
        "product_demand": product_demand,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助：从 state_space 导入 NormalizationSpec（避免重复定义）
# ═══════════════════════════════════════════════════════════════════════════════

from state_space import NormalizationSpec


# ═══════════════════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("Observation Builder — 自检")
    print("=" * 70)

    builder = ObservationBuilder()
    cfg = builder.cfg

    print(f"\n全局观测维度: {cfg.global_state_dim}")
    print(f"局部观测维度:")
    for aid, info in cfg.LOCAL_OBSERVATION_CONFIG.items():
        print(f"  {aid}: {info['dim']} — {info['description']}")

    # 测试提取 config state
    print("\n提取 config state...")
    try:
        config_state = extract_config_state()
        for key, arr in config_state.items():
            print(f"  {key}: shape={arr.shape}, range=[{arr.min():.2f}, {arr.max():.2f}]")
        print("  [OK] config state extracted")
    except Exception as e:
        print(f"  [ERROR] {e}")

    # 测试构建全局观测
    print("\n构建全局观测 (空结果)...")
    try:
        global_obs = builder.build_global_obs(config_state, None)
        print(f"  shape={global_obs.shape}, range=[{global_obs.min():.2f}, {global_obs.max():.2f}]")
        assert global_obs.shape == (cfg.global_state_dim,), \
            f"Expected ({cfg.global_state_dim},), got {global_obs.shape}"
        print("  [OK] global obs built")
    except Exception as e:
        print(f"  [ERROR] {e}")

    # 测试局部观测
    print("\n构建局部观测...")
    for aid in cfg.LOCAL_OBSERVATION_CONFIG:
        try:
            obs = builder.build_local_obs(aid, config_state, None)
            expected_dim = cfg.LOCAL_OBSERVATION_CONFIG[aid]["dim"]
            assert obs.shape == (expected_dim,), \
                f"Expected ({expected_dim},), got {obs.shape}"
            print(f"  {aid}: shape={obs.shape} [OK]")
        except Exception as e:
            print(f"  {aid}: [ERROR] {e}")

    print("\n" + "=" * 70)
    print("[OK] observation_builder.py self-check completed")
