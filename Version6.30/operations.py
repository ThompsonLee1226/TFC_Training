"""
Operations 模块 — 对应游戏 Operations 页面四个 Tab
======================================================
Tab 结构 :
  inbound   — 来料检验 (Per supplier) + 原料仓库设置 (Raw materials warehouse)
  mixing    — 混合器选择 (Mixers available) + 产品分配 (Allocate products to mixers)
  bottling  — 通用设置 (General settings) + 产线设置 (Line settings) + 产品分配
  outbound  — 成品仓库 (Finished goods warehouse) + 外包选项

使用方法：修改 OPERATIONS_CONFIG 字典中各 tab 的参数，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import random

from entities import (FACILITY, FacilityConfig, PRODUCT_MAP, BOM,
                      MixerSpec, BottlingLineSpec,
                      MIXER_SPECS, BOTTLING_LINE_SPECS, SUPPLIERS)


# ═══════════════════════════════════════════════════════════════
# 运营决策参数 — 按游戏 Operations 页面四个 Tab 组织
# ═══════════════════════════════════════════════════════════════

OPERATIONS_CONFIG: Dict = {

    # ────────────────────────────────────────────────────────
    # Tab 1: inbound — 来料检验 + 原料仓库
    # 对应网页 Operations → inbound tab
    # ────────────────────────────────────────────────────────
    "inbound": {
        # ── Per supplier → Raw materials inspection ──
        # 每个供应商一个 checkbox，开启后 EUR 5,000/年/供应商
        "raw_materials_inspection": {
            "NO8DO Mango":              True,
            "Mono Packaging Materials": False,
            "Miami Oranges":            True,
            "Philip Jones Plastics":    True,
            "SYI":                      True,
        },

        # ── Raw materials warehouse ──
        "raw_materials_warehouse": {
            "pallet_locations":   1000,  # Number of pallet locations
            "permanent_employees":   5,  # Number of permanent employees (FTE)
            "intake_time_days":      3,  # Intake time (days)
        },
    },

    # ────────────────────────────────────────────────────────
    # Tab 2: mixing — 混合器选择 + 产品分配
    # 对应网页 Operations → mixing tab
    # ────────────────────────────────────────────────────────
    "mixing": {
        # ── Mixers available ──
        # 当前选用的混合器（可选: Fruitmix MQ / MegaChurn 20 / FMM 4000）
        "current_mixer": "Fruitmix MQ",

        # ── Allocate products to mixers ──
        # 每个成品分配到哪个混合器
        "product_to_mixer": {
            "p_orange_1l":  "Fruitmix MQ",
            "p_ocp_1l":    "Fruitmix MQ",
            "p_om_1l":     "Fruitmix MQ",
            "p_orange_pet": "Fruitmix MQ",
            "p_ocp_pet":   "Fruitmix MQ",
            "p_om_pet":    "Fruitmix MQ",
        },
    },

    # ────────────────────────────────────────────────────────
    # Tab 3: bottling — 灌装线通用设置 + 产线设置 + 产品分配
    # 对应网页 Operations → bottling tab
    # ────────────────────────────────────────────────────────
    "bottling": {
        # ── General settings ──
        "general_settings": {
            # Preventive maintenance: "None" / "A little" / "A lot"
            "preventive_maintenance": "A little",
            # Solve breakdowns training: "No" / "Yes"
            "solve_breakdowns_training": "Yes",
            # Inflate PET bottles (checkbox)
            "inflate_pet_bottles": False,
        },

        # ── Line settings (对应当前选用的灌装线) ──
        # 当前选用的灌装线（可选: Swiss Fill 2 / TopSpeed 1 / MultiFlex 1 / Swiss Fill 1）
        "current_line": "Swiss Fill 2",
        # Number of shifts: 1 / 2 / 3 / 4 / 5
        "shifts_per_week": 2,
        # SMED action (checkbox): 缩短换型时间 50%
        "smed_action": True,
        # Increase speed (checkbox): 提升灌装速度
        "increase_speed": False,

        # ── Allocate products to bottling lines ──
        # 每个成品分配到哪条灌装线
        "product_to_line": {
            "p_orange_1l":  "Swiss Fill 2",
            "p_ocp_1l":    "Swiss Fill 2",
            "p_om_1l":     "Swiss Fill 2",
            "p_orange_pet": "Swiss Fill 2",
            "p_ocp_pet":   "Swiss Fill 2",
            "p_om_pet":    "Swiss Fill 2",
        },
    },

    # ────────────────────────────────────────────────────────
    # Tab 4: outbound — 成品仓库 + 外包 + Carrier 选择
    # 对应网页 Operations → outbound tab
    # ────────────────────────────────────────────────────────
    "outbound": {
        # ── Finished goods warehouse ──
        "finished_goods_warehouse": {
            # Outsource finished goods warehouse:
            #   "None" / "Conventional" / "Automated" / "MCC"
            "outsource_type": "None",
            # MCC type (仅 outsource_type == "MCC" 时生效):
            #   None / "yoghurt" / "ice_cream" / "tissue"
            "mcc_type": None,
            # Number of pallet locations
            "pallet_locations": 1400,
            # Number of permanent employees (FTE)
            "permanent_employees": 4,
        },
        # Carrier 选择在 Supply Chain 页面，此处仅记录
    },
}


# ═══════════════════════════════════════════════════════════════
# 便捷访问函数
# ═══════════════════════════════════════════════════════════════

def _cfg(path: str, default=None):
    """按点号路径访问 OPERATIONS_CONFIG，如 _cfg('inbound.raw_materials_inspection')"""
    keys = path.split(".")
    node = OPERATIONS_CONFIG
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
            if node is None:
                return default
        else:
            return default
    return node


def get_mixer_spec(mixer_name: Optional[str] = None) -> MixerSpec:
    """获取当前（或指定）混合器规格"""
    name = mixer_name or _cfg("mixing.current_mixer", "Fruitmix MQ")
    return MIXER_SPECS.get(name, MIXER_SPECS["Fruitmix MQ"])


def get_bottling_line_spec(line_name: Optional[str] = None) -> BottlingLineSpec:
    """获取当前（或指定）灌装线规格"""
    name = line_name or _cfg("bottling.current_line", "Swiss Fill 2")
    return BOTTLING_LINE_SPECS.get(name, BOTTLING_LINE_SPECS["Swiss Fill 2"])


# ═══════════════════════════════════════════════════════════════
# 生产模拟器
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProductionPlan:
    """单周生产计划"""
    week: int
    batches: List[Tuple[str, float]] = field(default_factory=list)  # [(product_id, liters)]


@dataclass
class ProductionResult:
    """一周生产结果"""
    week: int
    planned_liters: float = 0.0
    actual_liters: float = 0.0
    changeover_loss_hours: float = 0.0
    breakdown_loss_hours: float = 0.0
    startup_loss_liters: float = 0.0
    mixing_hours: float = 0.0
    bottling_hours: float = 0.0
    mixing_cost: float = 0.0
    bottling_fixed_cost: float = 0.0
    bottling_variable_cost: float = 0.0
    labor_cost: float = 0.0
    total_production_cost: float = 0.0


class ProductionSimulator:
    """双阶段（Mixing + Bottling）生产模拟器。

    使用 OPERATIONS_CONFIG 中的决策参数 +
    entities.py 中的 MixerSpec / BottlingLineSpec 进行模拟。
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def _available_hours(self, shifts: int) -> float:
        return shifts * FACILITY.hours_per_shift

    def simulate_week(self, week: int, plan: ProductionPlan) -> ProductionResult:
        """模拟一周生产。决策参数从 OPERATIONS_CONFIG 读取。"""
        mixer_spec = get_mixer_spec()
        line_spec = get_bottling_line_spec()

        shifts = _cfg("bottling.shifts_per_week", 2)
        available = self._available_hours(shifts)
        result = ProductionResult(week=week)

        if not plan.batches:
            # 没生产计划时也要付固定成本
            wpy = 52
            result.bottling_fixed_cost = line_spec.fixed_cost_annual / wpy
            result.mixing_cost = mixer_spec.fixed_cost_annual / wpy
            result.total_production_cost = result.bottling_fixed_cost + result.mixing_cost
            return result

        # ── Bottling: 换型损失 ──
        # 按产品ID和包装类型分组，切换时计算换型时间
        changeover_hours = 0.0
        prev_product = None
        for pid, _ in plan.batches:
            if prev_product is not None and pid != prev_product:
                # 检查是否仅包装尺寸变化 or 配方变化
                prev_flavor = prev_product.split('_')[1] if '_' in prev_product else prev_product
                curr_flavor = pid.split('_')[1] if '_' in pid else pid
                prev_size = "PET" if "pet" in prev_product else "1L"
                curr_size = "PET" if "pet" in pid else "1L"
                if curr_flavor != prev_flavor:
                    changeover_hours += line_spec.formula_changeover_hours
                elif curr_size != prev_size:
                    changeover_hours += line_spec.size_changeover_hours
            prev_product = pid

        # SMED action → changeover time -50%
        if _cfg("bottling.smed_action", False):
            changeover_hours *= 0.5

        result.changeover_loss_hours = changeover_hours

        # ── Bottling: 故障损失 ──
        pm = _cfg("bottling.general_settings.preventive_maintenance", "A little")
        breakdown_base = {
            "None": 0.06, "A little": 0.04, "A lot": 0.02
        }.get(pm, 0.04)

        training = _cfg("bottling.general_settings.solve_breakdowns_training", "Yes")
        if training == "Yes":
            breakdown_base *= 0.7

        result.breakdown_loss_hours = available * breakdown_base * self.rng.uniform(0.5, 1.5)

        # ── Bottling: 灌装产能 ──
        bottling_avail = available - changeover_hours - result.breakdown_loss_hours
        if bottling_avail < 0:
            bottling_avail = 0

        total_liters = sum(l for _, l in plan.batches)
        result.planned_liters = total_liters

        capacity_per_hour = line_spec.capacity_liters_per_hour
        # Increase speed → +10% capacity
        if _cfg("bottling.increase_speed", False):
            capacity_per_hour = int(capacity_per_hour * 1.10)

        max_bottling = bottling_avail * capacity_per_hour
        result.actual_liters = min(total_liters, max_bottling)

        if capacity_per_hour > 0:
            result.bottling_hours = result.actual_liters / capacity_per_hour

        # ── Bottling: 启动产能损失 ──
        result.startup_loss_liters = result.actual_liters * (line_spec.startup_productivity_loss_pct / 100)

        # ── Mixing: 混合时间 ──
        last_flavor = None
        total_mix_hours = 0.0
        scale = result.actual_liters / total_liters if total_liters > 0 else 0

        for product_id, liters in plan.batches:
            actual = liters * scale
            batches_needed = max(1, int(actual / mixer_spec.batch_max_liters) + 1)
            flavor = product_id.split('_')[1] if '_' in product_id else product_id
            for _ in range(batches_needed):
                total_mix_hours += mixer_spec.run_time_hours
                if flavor != last_flavor and last_flavor is not None:
                    total_mix_hours += mixer_spec.clean_time_hours
                last_flavor = flavor

        result.mixing_hours = total_mix_hours

        # ── 成本计算 ──
        wpy = 52
        # Mixing
        mixer_fixed = mixer_spec.fixed_cost_annual / wpy
        mixer_var = total_mix_hours * mixer_spec.cost_per_hour
        # Bottling
        bottling_fixed = line_spec.fixed_cost_annual / wpy
        bottling_var = result.bottling_hours * line_spec.flexible_labor_per_hour * line_spec.num_operators

        # Labor (permanent + overtime)
        num_ops = line_spec.num_operators
        base_labor = num_ops * FACILITY.labor_cost_per_fte_annual / wpy
        standard_hours = shifts * FACILITY.hours_per_shift * num_ops
        total_hours_needed = result.bottling_hours * num_ops + result.mixing_hours
        overtime = max(0, total_hours_needed - standard_hours)
        overtime_cost = overtime * (FACILITY.labor_cost_per_fte_annual / 52 / 40) * 1.5

        result.mixing_cost = mixer_fixed + mixer_var
        result.bottling_fixed_cost = bottling_fixed
        result.bottling_variable_cost = bottling_var
        result.labor_cost = base_labor + overtime_cost
        result.total_production_cost = (
            result.mixing_cost + result.bottling_fixed_cost +
            result.bottling_variable_cost + result.labor_cost
        )
        return result

    def make_plan(self, week: int, demand_by_product: Dict[str, float]) -> ProductionPlan:
        """根据周需求生成生产计划"""
        batches = [(pid, liters) for pid, liters in demand_by_product.items() if liters > 0]
        return ProductionPlan(week=week, batches=batches)


# ═══════════════════════════════════════════════════════════════
# 组件需求计算（BOM 反推）
# ═══════════════════════════════════════════════════════════════

def calculate_component_needs(product_liters: Dict[str, float]) -> Dict[str, float]:
    """
    根据成品产量计算所需组件量。

    参数:
        product_liters: {product_id: total_liters_produced_over_26_weeks}

    返回:
        {component_id: total_liters_needed}
    """
    needs: Dict[str, float] = {}
    for pid, liters in product_liters.items():
        recipe = BOM.get(pid, {})
        for comp_id, ratio in recipe.items():
            needs[comp_id] = needs.get(comp_id, 0.0) + liters * ratio
    return needs


# ═══════════════════════════════════════════════════════════════
# 各 Tab 辅助计算函数
# ═══════════════════════════════════════════════════════════════

def calculate_inspection_cost() -> float:
    """Inbound tab — 来料检验成本（26 周）。
    网页位置：Operations → inbound → Raw materials inspection
    """
    inspection = _cfg("inbound.raw_materials_inspection", {})
    count = sum(1 for v in inspection.values() if v)
    return count * 5000.0 * 0.5  # EUR 5k/year/supplier, half year


def calculate_warehouse_cost_raw_materials() -> float:
    """Inbound tab — 原料仓库成本（26 周）。
    网页位置：Operations → inbound → Raw materials warehouse
    """
    wh = _cfg("inbound.raw_materials_warehouse", {})
    pallets = wh.get("pallet_locations", 1000)
    employees = wh.get("permanent_employees", 5)
    from entities import WAREHOUSE
    space_cost = pallets * WAREHOUSE.pallet_location_cost_annual * 0.5  # half year
    labor_cost = employees * WAREHOUSE.perm_employee_cost_annual * 0.5
    return space_cost + labor_cost


def calculate_warehouse_cost_finished_goods() -> float:
    """Outbound tab — 成品仓库成本（26 周）。
    网页位置：Operations → outbound → Finished goods warehouse
    """
    fg = _cfg("outbound.finished_goods_warehouse", {})
    pallets = fg.get("pallet_locations", 1400)
    employees = fg.get("permanent_employees", 4)
    outsource = fg.get("outsource_type", "None")
    from entities import WAREHOUSE

    if outsource == "Conventional":
        # 外包仓库成本不同
        space_cost = pallets * WAREHOUSE.overflow_pallet_cost_annual * 0.5
    elif outsource == "Automated":
        space_cost = pallets * WAREHOUSE.overflow_pallet_cost_annual * 0.5 * 1.3
    elif outsource == "MCC":
        # MCC: 与合作方共享仓库
        space_cost = pallets * WAREHOUSE.pallet_location_cost_annual * 0.5 * 0.6
    else:
        space_cost = pallets * WAREHOUSE.pallet_location_cost_annual * 0.5

    labor_cost = employees * WAREHOUSE.perm_employee_cost_annual * 0.5
    return space_cost + labor_cost


# ═══════════════════════════════════════════════════════════════
# 产线分配查询
# ═══════════════════════════════════════════════════════════════

def get_products_for_mixer(mixer_name: Optional[str] = None) -> List[str]:
    """返回分配到指定混合器的所有成品 ID"""
    name = mixer_name or _cfg("mixing.current_mixer", "Fruitmix MQ")
    ptm = _cfg("mixing.product_to_mixer", {})
    return [pid for pid, m in ptm.items() if m == name]


def get_products_for_bottling_line(line_name: Optional[str] = None) -> List[str]:
    """返回分配到指定灌装线的所有成品 ID"""
    name = line_name or _cfg("bottling.current_line", "Swiss Fill 2")
    ptl = _cfg("bottling.product_to_line", {})
    return [pid for pid, l in ptl.items() if l == name]
