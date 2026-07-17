"""
MARL 动作编解码器 — MultiDiscrete 动作 ↔ TFC 决策配置
======================================================
基于 decision.py 的 DECISION_CONFIG 元数据自动生成动作空间。

职责:
  - 定义各 Agent 控制的决策变量及其离散选项
  - 构建 gym.spaces.MultiDiscrete 动作空间
  - decode(): 动作索引数组 → 更新 decision.DECISION_CONFIG
  - encode(): decision.DECISION_CONFIG → 动作索引数组
  - 往返验证: 随机采样 N 组确认 decode(encode(x)) == x

用法:
  from marl.env.action_codec import ActionCodec

  codec = ActionCodec("purchasing")
  action_space = codec.build_action_space()   # → MultiDiscrete([3,8,5,8,4,2,2, ...])
  actions = action_space.sample()              # → np.array([0,3,2,5,1,0,1, ...])
  codec.decode(actions)                        # → 更新 DECISION_CONFIG
  restored = codec.encode()                    # → np.array([0,3,2,5,1,0,1, ...])
  assert np.array_equal(actions, restored)
"""

import sys
import os
from typing import Dict, List, Tuple, Any, Optional
import numpy as np

# 确保能 import 上层模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    import gymnasium as gym
except ImportError:
    gym = None


# ═══════════════════════════════════════════════════════════════════════════════
# 离散化辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def discretize_float_range(lo: float, hi: float, n_bins: int) -> List[float]:
    """将连续范围均匀离散化为 n_bins 个值。"""
    if n_bins <= 1:
        return [lo]
    step = (hi - lo) / (n_bins - 1)
    return [round(lo + i * step, 6) for i in range(n_bins)]


def discretize_int_range(lo: int, hi: int) -> List[int]:
    """整型范围展开为离散列表。"""
    if hi - lo > 20:
        raise ValueError(f"Int range [{lo}, {hi}] too wide for discrete action "
                         f"({hi - lo + 1} options). Consider binning.")
    return list(range(lo, hi + 1))


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 动作变量定义
# ═══════════════════════════════════════════════════════════════════════════════

# 供应商 ID 列表（与 decision.py 对齐）
_SUPPLIER_IDS = ["s_pack", "s_pet", "s_orange", "s_mango", "s_vitc"]
_CUSTOMER_IDS = ["c_fg", "c_land", "c_dom"]
_COMPONENT_IDS = ["pack_1l", "pet", "orange", "mango", "vitamin_c"]
_PRODUCT_IDS = [
    "p_orange_1l", "p_ocp_1l", "p_om_1l",
    "p_orange_pet", "p_ocp_pet", "p_om_pet",
]

# ── 供应商质量等级 ──
QUALITY_OPTIONS = ["High", "Middle", "Poor"]

# ── 供应商贸易单位 ──
TRADE_UNIT_SUPPLIER_OPTIONS = ["Pallet", "FTL", "Tank", "IBC", "Drum"]

# ── 供应商交货窗口 ──
DELIVERY_WINDOW_OPTIONS = ["4 hours", "1 day", "2 days", "1 week"]

# ── 供应商交货可靠性离散值 (%) ──
DELIVERY_RELIABILITY_OPTIONS = discretize_float_range(85.0, 99.0, 8)
# → [85.0, 87.0, 89.0, 91.0, 93.0, 95.0, 97.0, 99.0]

# ── 客户服务水平离散值 (%) ──
SERVICE_LEVEL_OPTIONS = discretize_float_range(90.0, 99.0, 8)
# → [90.0, 91.29, 92.57, 93.86, 95.14, 96.43, 97.71, 99.0]

# ── 客户保质期要求离散值 (%) ──
SHELF_LIFE_OPTIONS = discretize_float_range(50.0, 85.0, 8)
# → [50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0]

# ── 客户订单截止时间 ──
ORDER_DEADLINE_OPTIONS = ["12:00", "14:00", "17:00", "20:00"]

# ── 客户贸易单位 ──
TRADE_UNIT_CUSTOMER_OPTIONS = ["Box", "Pallet layer", "Pallet"]

# ── 促销压力 ──
PROMO_PRESSURE_OPTIONS = ["None", "Low", "Middle", "Heavy"]

# ── 促销预知期 ──
PROMO_HORIZON_OPTIONS = ["Short", "Middle", "Long"]

# ── 混合器 ──
MIXER_OPTIONS = ["Fruitmix MQ", "MegaChurn 20", "FMM 4000"]

# ── 灌装线 ──
BOTTLING_LINE_OPTIONS = ["Swiss Fill 2", "TopSpeed 1", "MultiFlex 1", "Swiss Fill 1"]

# ── 预防维护 ──
MAINTENANCE_OPTIONS = ["None", "A little", "A lot"]

# ── 故障培训 ──
TRAINING_OPTIONS = ["No", "Yes"]

# ── 外包类型 ──
OUTSOURCE_OPTIONS = ["None", "Conventional", "Automated", "MCC"]

# ── MCC 类型 ──
MCC_OPTIONS = [None, "yoghurt", "ice_cream", "tissue"]

# ── 安全库存离散值 (周) ──
SAFETY_STOCK_OPTIONS = discretize_float_range(0.0, 6.0, 13)
# → [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]

# ── 补货批量离散值 (周) ──
LOT_SIZE_OPTIONS = list(range(1, 9))  # 1-8 weeks

# ── 冻结期离散值 (周) ──
FROZEN_PERIOD_OPTIONS = list(range(0, 7))  # 0-6 weeks

# ── 生产间隔离散值 (周) ──
PRODUCTION_INTERVAL_OPTIONS = list(range(1, 6))  # 1-5 weeks

# ── 班次 ──
SHIFTS_OPTIONS = list(range(1, 6))  # 1-5 shifts

# ── 加班上限离散值 (小时) ──
MAX_OVERTIME_OPTIONS = discretize_float_range(0, 40, 9)
# → [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]

# ── 托盘位离散值（步长100）──
PALLET_LOCATIONS_OPTIONS_RAW = list(range(100, 2100, 100))  # 21 options

# ── 员工数离散值 ──
EMPLOYEES_OPTIONS = list(range(1, 31))  # 1-30 FTE (步长1已经够细)

# ── 入库时间 (天) ──
INTAKE_TIME_OPTIONS = list(range(1, 8))  # 1-7 days


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 动作配置表
# ═══════════════════════════════════════════════════════════════════════════════

def _build_purchasing_var_specs() -> List[Dict]:
    """构建 Purchasing Agent 的动作变量列表。

    每个元素 = {
        "path": "dotted.path.to.variable",    # decision.py 点号路径
        "options": [value0, value1, ...],     # 离散选项值列表
        "default_index": int,                  # 当前默认值在 options 中的索引
    }
    """
    specs = []

    for sid in _SUPPLIER_IDS:
        prefix = f"purchasing.supplier_decisions.{sid}"
        # quality
        specs.append({
            "path": f"{prefix}.quality",
            "options": QUALITY_OPTIONS,
            "default_index": QUALITY_OPTIONS.index("High"),
        })
        # payment_term_weeks (int 1-8)
        pt_opts = list(range(1, 9))
        specs.append({
            "path": f"{prefix}.payment_term_weeks",
            "options": pt_opts,
            "default_index": pt_opts.index(4),
        })
        # trade_unit
        specs.append({
            "path": f"{prefix}.trade_unit",
            "options": TRADE_UNIT_SUPPLIER_OPTIONS,
            "default_index": 0,  # 默认值各不相同，取 Pallet 作为通用默认
        })
        # delivery_reliability_pct
        specs.append({
            "path": f"{prefix}.delivery_reliability_pct",
            "options": DELIVERY_RELIABILITY_OPTIONS,
            "default_index": 5,  # 96.0 → index 5 (closest: 95.0)
        })
        # delivery_window
        specs.append({
            "path": f"{prefix}.delivery_window",
            "options": DELIVERY_WINDOW_OPTIONS,
            "default_index": DELIVERY_WINDOW_OPTIONS.index("1 day"),
        })
        # supplier_development
        specs.append({
            "path": f"{prefix}.supplier_development",
            "options": [False, True],
            "default_index": 0,
        })
        # vmi
        specs.append({
            "path": f"{prefix}.vmi",
            "options": [False, True],
            "default_index": 0,
        })

    # dual_sourcing (5 components)
    for cid in _COMPONENT_IDS:
        specs.append({
            "path": f"purchasing.dual_sourcing.{cid}",
            "options": [False, True],
            "default_index": 0,
        })

    return specs


def _build_sales_var_specs() -> List[Dict]:
    """构建 Sales Agent 的动作变量列表。"""
    specs = []

    for cid in _CUSTOMER_IDS:
        prefix = f"sales.customer_decisions.{cid}"
        # service_level_pct
        specs.append({
            "path": f"{prefix}.service_level_pct",
            "options": SERVICE_LEVEL_OPTIONS,
            "default_index": 4,  # 95.0 → index 4 (95.14 ≈ 95.0)
        })
        # shelf_life_pct
        specs.append({
            "path": f"{prefix}.shelf_life_pct",
            "options": SHELF_LIFE_OPTIONS,
            "default_index": 5,  # 75.0 → index 5
        })
        # order_deadline
        specs.append({
            "path": f"{prefix}.order_deadline",
            "options": ORDER_DEADLINE_OPTIONS,
            "default_index": ORDER_DEADLINE_OPTIONS.index("14:00"),
        })
        # trade_unit
        specs.append({
            "path": f"{prefix}.trade_unit",
            "options": TRADE_UNIT_CUSTOMER_OPTIONS,
            "default_index": TRADE_UNIT_CUSTOMER_OPTIONS.index("Pallet layer"),
        })
        # payment_term_weeks
        pt_opts = list(range(1, 9))
        specs.append({
            "path": f"{prefix}.payment_term_weeks",
            "options": pt_opts,
            "default_index": pt_opts.index(3) if cid != "c_dom" else pt_opts.index(4),
        })
        # promotional_pressure
        specs.append({
            "path": f"{prefix}.promotional_pressure",
            "options": PROMO_PRESSURE_OPTIONS,
            "default_index": (PROMO_PRESSURE_OPTIONS.index("Middle")
                              if cid != "c_dom" else PROMO_PRESSURE_OPTIONS.index("Heavy")),
        })
        # promotion_horizon
        specs.append({
            "path": f"{prefix}.promotion_horizon",
            "options": PROMO_HORIZON_OPTIONS,
            "default_index": PROMO_HORIZON_OPTIONS.index("Short"),
        })
        # vmi
        specs.append({
            "path": f"{prefix}.vmi",
            "options": [False, True],
            "default_index": 0,
        })

    return specs


def _build_operations_var_specs() -> List[Dict]:
    """构建 Operations Agent 的动作变量列表。

    涵盖 4 个 Tab: inbound / mixing / bottling / outbound。
    """
    specs = []

    # ── Tab 1: inbound ──
    # raw_materials_inspection (5 suppliers)
    inspection_supplier_names = [
        "NO8DO Mango", "Mono Packaging Materials", "Miami Oranges",
        "Platin PET", "AlL Vitamins",
    ]
    for name in inspection_supplier_names:
        specs.append({
            "path": f"operations.inbound.raw_materials_inspection.{name}",
            "options": [False, True],
            "default_index": 0,  # 默认值各不相同但无需精确，decode 会覆盖
        })

    # raw_materials_warehouse
    specs.append({
        "path": "operations.inbound.raw_materials_warehouse.pallet_locations",
        "options": PALLET_LOCATIONS_OPTIONS_RAW,
        "default_index": PALLET_LOCATIONS_OPTIONS_RAW.index(866) if 866 in PALLET_LOCATIONS_OPTIONS_RAW else 8,
    })
    specs.append({
        "path": "operations.inbound.raw_materials_warehouse.permanent_employees",
        "options": EMPLOYEES_OPTIONS,
        "default_index": EMPLOYEES_OPTIONS.index(4),
    })
    specs.append({
        "path": "operations.inbound.raw_materials_warehouse.intake_time_days",
        "options": INTAKE_TIME_OPTIONS,
        "default_index": INTAKE_TIME_OPTIONS.index(4),
    })

    # ── Tab 2: mixing ──
    specs.append({
        "path": "operations.mixing.current_mixer",
        "options": MIXER_OPTIONS,
        "default_index": MIXER_OPTIONS.index("Fruitmix MQ"),
    })

    # ── Tab 3: bottling ──
    specs.append({
        "path": "operations.bottling.general_settings.preventive_maintenance",
        "options": MAINTENANCE_OPTIONS,
        "default_index": MAINTENANCE_OPTIONS.index("A little"),
    })
    specs.append({
        "path": "operations.bottling.general_settings.solve_breakdowns_training",
        "options": TRAINING_OPTIONS,
        "default_index": TRAINING_OPTIONS.index("Yes"),
    })
    specs.append({
        "path": "operations.bottling.general_settings.inflate_pet_bottles",
        "options": [False, True],
        "default_index": 0,
    })
    specs.append({
        "path": "operations.bottling.current_line",
        "options": BOTTLING_LINE_OPTIONS,
        "default_index": BOTTLING_LINE_OPTIONS.index("Swiss Fill 2"),
    })
    specs.append({
        "path": "operations.bottling.shifts_per_week",
        "options": SHIFTS_OPTIONS,
        "default_index": SHIFTS_OPTIONS.index(2),
    })
    specs.append({
        "path": "operations.bottling.smed_action",
        "options": [False, True],
        "default_index": 1,  # True
    })
    specs.append({
        "path": "operations.bottling.increase_speed",
        "options": [False, True],
        "default_index": 0,  # False
    })
    specs.append({
        "path": "operations.bottling.max_overtime_hours",
        "options": MAX_OVERTIME_OPTIONS,
        "default_index": 3,  # 16.0 → index 3 (15.0, closest)
    })

    # ── Tab 4: outbound ──
    specs.append({
        "path": "operations.outbound.finished_goods_warehouse.outsource_type",
        "options": OUTSOURCE_OPTIONS,
        "default_index": OUTSOURCE_OPTIONS.index("None"),
    })
    specs.append({
        "path": "operations.outbound.finished_goods_warehouse.mcc_type",
        "options": MCC_OPTIONS,
        "default_index": 0,  # None
    })
    specs.append({
        "path": "operations.outbound.finished_goods_warehouse.pallet_locations",
        "options": PALLET_LOCATIONS_OPTIONS_RAW,
        "default_index": PALLET_LOCATIONS_OPTIONS_RAW.index(1350) if 1350 in PALLET_LOCATIONS_OPTIONS_RAW else 13,
    })
    specs.append({
        "path": "operations.outbound.finished_goods_warehouse.permanent_employees",
        "options": EMPLOYEES_OPTIONS,
        "default_index": EMPLOYEES_OPTIONS.index(5),
    })

    return specs


def _build_supplychain_var_specs() -> List[Dict]:
    """构建 SupplyChain Agent 的动作变量列表。"""
    specs = []

    # safety_stock_weeks (5 components)
    for cid in _COMPONENT_IDS:
        specs.append({
            "path": f"supply_chain.safety_stock_weeks.{cid}",
            "options": SAFETY_STOCK_OPTIONS,
            "default_index": 3,  # 1.5 → index 3
        })

    # lot_size_weeks (5 components)
    for cid in _COMPONENT_IDS:
        specs.append({
            "path": f"supply_chain.lot_size_weeks.{cid}",
            "options": LOT_SIZE_OPTIONS,
            "default_index": LOT_SIZE_OPTIONS.index(3) if cid != "vitamin_c" else LOT_SIZE_OPTIONS.index(4),
        })

    # fg_safety_stock_weeks (6 products)
    for pid in _PRODUCT_IDS:
        specs.append({
            "path": f"supply_chain.fg_safety_stock_weeks.{pid}",
            "options": SAFETY_STOCK_OPTIONS,
            "default_index": 5,  # ~2.5-3.0 → index 5
        })

    # frozen_period_weeks
    specs.append({
        "path": "supply_chain.frozen_period_weeks",
        "options": FROZEN_PERIOD_OPTIONS,
        "default_index": FROZEN_PERIOD_OPTIONS.index(3),
    })

    # production_interval_weeks
    specs.append({
        "path": "supply_chain.production_interval_weeks",
        "options": PRODUCTION_INTERVAL_OPTIONS,
        "default_index": PRODUCTION_INTERVAL_OPTIONS.index(1),
    })

    return specs


# ═══════════════════════════════════════════════════════════════════════════════
# 各 Agent 动作配置汇总
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_VAR_SPECS: Dict[str, List[Dict]] = {
    "purchasing":   _build_purchasing_var_specs(),
    "sales":        _build_sales_var_specs(),
    "operations":   _build_operations_var_specs(),
    "supplychain":  _build_supplychain_var_specs(),
}

# 各 Agent 的变量数量
AGENT_VAR_COUNTS = {agent: len(specs) for agent, specs in AGENT_VAR_SPECS.items()}

# 所有 Agent（按固定顺序）
_AGENT_ORDER = ["purchasing", "sales", "operations", "supplychain"]


# ═══════════════════════════════════════════════════════════════════════════════
# ActionCodec 类
# ═══════════════════════════════════════════════════════════════════════════════

class ActionCodec:
    """单个 Agent 的动作编解码器。

    每个 Agent 的 ActionCodec 管理该 Agent 的:
      - 动作变量列表 (var_specs)
      - MultiDiscrete 动作空间
      - decode: 动作 → decision.DECISION_CONFIG
      - encode: DECISION_CONFIG → 动作
    """

    def __init__(self, agent_id: str):
        if agent_id not in AGENT_VAR_SPECS:
            raise ValueError(
                f"Unknown agent_id: '{agent_id}'. "
                f"Valid: {list(AGENT_VAR_SPECS.keys())}"
            )
        self.agent_id = agent_id
        self.var_specs = AGENT_VAR_SPECS[agent_id]
        self._n_dims = len(self.var_specs)
        self._nvec = [len(spec["options"]) for spec in self.var_specs]
        self._default_action = np.array(
            [spec["default_index"] for spec in self.var_specs],
            dtype=np.int64,
        )

    # ── 属性 ──
    @property
    def n_dims(self) -> int:
        """动作维度数（变量数）。"""
        return self._n_dims

    @property
    def total_combinations(self) -> int:
        """动作组合总数（可能极大）。"""
        prod = 1
        for n in self._nvec:
            prod *= n
        return prod

    # ── 空间构建 ──
    def build_action_space(self) -> "gym.spaces.MultiDiscrete":
        """构建该 Agent 的 MultiDiscrete 动作空间。"""
        if gym is None:
            raise ImportError("gymnasium is required. Install with: pip install gymnasium")
        return gym.spaces.MultiDiscrete(self._nvec)

    # ── 解码 ──
    def decode(self, actions: np.ndarray) -> Dict[str, Any]:
        """将动作数组解码为决策配置更新字典。

        Args:
            actions: shape=(n_dims,) 的整数数组

        Returns:
            {dotted_path: new_value} 字典，可直接用于更新 DECISION_CONFIG
        """
        if len(actions) != self._n_dims:
            raise ValueError(
                f"Expected {self._n_dims} actions, got {len(actions)}"
            )

        updates = {}
        for i, spec in enumerate(self.var_specs):
            idx = int(actions[i])
            if idx < 0 or idx >= len(spec["options"]):
                raise IndexError(
                    f"Action dim {i}: index {idx} out of range [0, {len(spec['options'])})"
                )
            updates[spec["path"]] = spec["options"][idx]
        return updates

    def apply(self, actions: np.ndarray):
        """解码动作并直接写入 decision.DECISION_CONFIG。

        内部调用 decision.set_value() 逐变量更新。
        """
        from decision import set_value as _set_decision

        updates = self.decode(actions)
        for path, value in updates.items():
            ok = _set_decision(path, value)
            if not ok:
                raise RuntimeError(
                    f"Failed to set decision '{path}' = {value!r}"
                )

    # ── 编码 ──
    def encode(self) -> np.ndarray:
        """从当前 decision.DECISION_CONFIG 编码为动作数组。

        Returns:
            shape=(n_dims,) 的整数数组
        """
        from decision import get_value as _get_decision

        actions = np.zeros(self._n_dims, dtype=np.int64)
        for i, spec in enumerate(self.var_specs):
            current_val = _get_decision(spec["path"])
            try:
                idx = spec["options"].index(current_val)
            except ValueError:
                # 当前值不在离散选项列表中 → 找最近值
                idx = self._find_closest(current_val, spec["options"])
            actions[i] = idx
        return actions

    # ── 往返验证 ──
    def validate_round_trip(self, n_samples: int = 1000) -> Dict[str, Any]:
        """随机采样 n_samples 组动作，验证 encode(decode(x)) == x。

        Returns:
            {
                "ok": True/False,
                "n_samples": n_samples,
                "n_passed": int,
                "n_failed": int,
                "errors": list of error messages (max 10),
            }
        """
        import random as _random
        _rng = _random.Random(42)

        errors = []
        n_passed = 0

        for _ in range(n_samples):
            # 随机采样动作
            actions = np.array([
                _rng.randrange(len(spec["options"]))
                for spec in self.var_specs
            ], dtype=np.int64)

            # decode → apply (写入 DECISION_CONFIG)
            try:
                self.apply(actions)
            except Exception as e:
                errors.append(f"decode failed: {e}")
                continue

            # encode ← 从 DECISION_CONFIG 读回
            try:
                restored = self.encode()
            except Exception as e:
                errors.append(f"encode failed: {e}")
                continue

            # 比较
            if np.array_equal(actions, restored):
                n_passed += 1
            else:
                diffs = np.where(actions != restored)[0]
                err_detail = []
                for d in diffs[:5]:
                    spec = self.var_specs[d]
                    err_detail.append(
                        f"  dim {d} ({spec['path']}): "
                        f"original={actions[d]} ({spec['options'][actions[d]]!r}), "
                        f"restored={restored[d]} ({spec['options'][restored[d]]!r})"
                    )
                errors.append(
                    f"Round-trip mismatch:\n" + "\n".join(err_detail)
                )
                if len(errors) >= 10:
                    break

        return {
            "ok": len(errors) == 0,
            "n_samples": n_samples,
            "n_passed": n_passed,
            "n_failed": n_samples - n_passed,
            "errors": errors[:10],
        }

    @staticmethod
    def _find_closest(value, options: list) -> int:
        """在离散选项列表中找最接近的索引。"""
        if isinstance(value, str):
            # 字符串不回退
            raise ValueError(f"Cannot find '{value}' in options {options}")
        if isinstance(value, bool):
            return options.index(value) if value in options else 0
        # 数值 → 最近值
        best_idx = 0
        best_dist = float("inf")
        for i, opt in enumerate(options):
            if opt is None:
                continue
            dist = abs(float(value) - float(opt))
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        return best_idx


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数：所有 Agent 的编解码器
# ═══════════════════════════════════════════════════════════════════════════════

def create_all_codecs() -> Dict[str, ActionCodec]:
    """为 4 个 Agent 创建编解码器。"""
    return {agent_id: ActionCodec(agent_id) for agent_id in _AGENT_ORDER}


def build_single_action_space() -> "gym.spaces.MultiDiscrete":
    """构建合并的 Single-Agent 动作空间（所有 Agent 拼接）。"""
    all_nvec = []
    for agent_id in _AGENT_ORDER:
        specs = AGENT_VAR_SPECS[agent_id]
        all_nvec.extend(len(spec["options"]) for spec in specs)
    if gym is None:
        raise ImportError("gymnasium is required.")
    return gym.spaces.MultiDiscrete(all_nvec)


def build_multi_action_spaces() -> Dict[str, "gym.spaces.MultiDiscrete"]:
    """构建 Multi-Agent 动作空间字典。"""
    codecs = create_all_codecs()
    return {agent_id: codec.build_action_space() for agent_id, codec in codecs.items()}


def decode_single_action(actions: np.ndarray) -> Dict[str, np.ndarray]:
    """将合并的 Single-Agent 动作拆分为各 Agent 子动作并解码。

    Returns:
        {agent_id: per_agent_action_array, ...}
    """
    offset = 0
    per_agent = {}
    for agent_id in _AGENT_ORDER:
        n = AGENT_VAR_COUNTS[agent_id]
        per_agent[agent_id] = actions[offset:offset + n]
        offset += n
    return per_agent


def apply_all_actions(per_agent_actions: Dict[str, np.ndarray]):
    """将所有 Agent 的动作解码并写入 DECISION_CONFIG。"""
    codecs = create_all_codecs()
    for agent_id, actions in per_agent_actions.items():
        codecs[agent_id].apply(actions)


# ═══════════════════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("Action Codec — 自检")
    print("=" * 70)

    for agent_id in _AGENT_ORDER:
        codec = ActionCodec(agent_id)
        nvec = codec._nvec
        print(f"\n[{agent_id}]")
        print(f"  变量数:    {codec.n_dims}")
        print(f"  nvec:      {nvec}")
        print(f"  组合总数:  {codec.total_combinations:,}")

        # 往返验证
        result = codec.validate_round_trip(n_samples=500)
        status = "PASS" if result["ok"] else "FAIL"
        print(f"  往返验证:  {status} ({result['n_passed']}/{result['n_samples']})")
        if not result["ok"]:
            for err in result["errors"][:3]:
                print(f"    {err}")

    # Single agent 汇总
    print(f"\n[Single Agent (合并)]")
    total_dims = sum(AGENT_VAR_COUNTS.values())
    print(f"  总变量数: {total_dims}")
    single_nvec = []
    for agent_id in _AGENT_ORDER:
        single_nvec.extend([len(s["options"]) for s in AGENT_VAR_SPECS[agent_id]])
    print(f"  nvec:      {single_nvec}")
    total_combos = 1
    for n in single_nvec:
        total_combos *= n
    print(f"  组合总数:  {total_combos:,}")

    print("\n" + "=" * 70)
    print("[OK] action_codec.py self-check completed")
