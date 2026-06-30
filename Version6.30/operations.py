"""
Operations 模块 — 对应游戏 Operations 页面
==========================================
包含：运营决策参数、生产模拟器（混合 + 灌装双阶段）。

使用方法：修改 OPERATIONS_CONFIG 字典中的参数，
          然后运行 simulation.py 查看结果。
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
import random

from entities import FACILITY, FacilityConfig, PRODUCT_MAP, BOM


# ═══════════════════════════════════════════════════════════════
# 运营决策参数（对应 Operations 页面设置）
# ═══════════════════════════════════════════════════════════════

OPERATIONS_CONFIG = {
    # ── 来料检验（True = 开启，EUR 5,000/年/供应商）──
    "raw_materials_inspection": {
        "s_pack":   False,
        "s_pet":    True,
        "s_orange": True,
        "s_mango":  True,
        "s_vitc":   True,
    },
    # ── 原料仓库 ──
    "raw_materials_pallet_locations": 1000,
    "raw_materials_perm_employees": 5,
    "intake_time_days": 3,
    # ── 生产排班 ──
    "production_shifts_per_week": 5,
    # ── 培训项目 ──
    "smed_training":            False,   # SMED → 换型时间 -50%
    "solve_breakdowns_training": False,  # 故障率 -30%
}


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
    mixing_hours: float = 0.0
    bottling_hours: float = 0.0
    mixing_cost: float = 0.0
    bottling_fixed_cost: float = 0.0
    bottling_variable_cost: float = 0.0
    labor_cost: float = 0.0
    total_production_cost: float = 0.0


class ProductionSimulator:
    """双阶段（Mixing + Bottling）生产模拟器"""

    def __init__(self, config: FacilityConfig = FACILITY, seed: int = 42):
        self.config = config
        self.rng = random.Random(seed)

    def _available_hours(self, shifts: int) -> float:
        return shifts * self.config.hours_per_shift

    def simulate_week(self, week: int, plan: ProductionPlan,
                      shifts_per_week: int,
                      has_smed: bool = False,
                      has_breakdown_training: bool = False) -> ProductionResult:
        """模拟一周生产"""
        cfg = self.config
        available = self._available_hours(shifts_per_week)
        result = ProductionResult(week=week)

        if not plan.batches:
            result.bottling_fixed_cost = cfg.bottling_fixed_cost_annual / 52
            result.mixing_cost = cfg.mixer_fixed_cost_annual / 52
            result.total_production_cost = result.bottling_fixed_cost + result.mixing_cost
            return result

        # 换型损失
        changeovers = len(plan.batches) - 1
        changeover_time = cfg.bottling_changeover_hours * changeovers
        if has_smed:
            changeover_time *= 0.5
        result.changeover_loss_hours = changeover_time

        # 故障损失
        breakdown_rate = cfg.bottling_breakdown_rate_pct / 100
        if has_breakdown_training:
            breakdown_rate *= 0.7
        result.breakdown_loss_hours = available * breakdown_rate * self.rng.uniform(0.5, 1.5)

        # 可用灌装时间
        bottling_avail = available - changeover_time - result.breakdown_loss_hours
        if bottling_avail < 0:
            bottling_avail = 0

        # 产量
        total_liters = sum(l for _, l in plan.batches)
        result.planned_liters = total_liters
        max_bottling = bottling_avail * cfg.bottling_liters_per_hour * cfg.num_bottling_lines
        result.actual_liters = min(total_liters, max_bottling)
        if cfg.bottling_liters_per_hour * cfg.num_bottling_lines > 0:
            result.bottling_hours = result.actual_liters / (cfg.bottling_liters_per_hour * cfg.num_bottling_lines)

        # 混合时间
        last_flavor = None
        total_mix_hours = 0.0
        scale = result.actual_liters / total_liters if total_liters > 0 else 0
        for product_id, liters in plan.batches:
            actual = liters * scale
            batches_needed = max(1, int(actual / cfg.mixer_max_batch_liters) + 1)
            flavor = product_id.split('_')[1] if '_' in product_id else product_id
            for _ in range(batches_needed):
                total_mix_hours += cfg.mixer_run_time_hours
                if flavor != last_flavor and last_flavor is not None:
                    total_mix_hours += cfg.mixer_clean_time_hours
                last_flavor = flavor
        result.mixing_hours = total_mix_hours

        # 成本
        wpy = 52
        mixer_fixed = cfg.mixer_fixed_cost_annual / wpy
        mixer_var = total_mix_hours * cfg.mixer_variable_cost_per_hour
        bottling_fixed = cfg.bottling_fixed_cost_annual / wpy
        bottling_var = result.bottling_hours * 80.0  # EUR 80/h/line maintenance

        perm_labor = cfg.permanent_production_fte * cfg.labor_cost_per_fte_annual / wpy
        standard = shifts_per_week * 8
        total_hours_needed = result.mixing_hours + result.bottling_hours * cfg.num_bottling_lines
        overtime = max(0, total_hours_needed - standard * cfg.permanent_production_fte)
        overtime_cost = overtime * (cfg.labor_cost_per_fte_annual / 52 / 40) * 1.5

        result.mixing_cost = mixer_fixed + mixer_var
        result.bottling_fixed_cost = bottling_fixed
        result.bottling_variable_cost = bottling_var
        result.labor_cost = perm_labor + overtime_cost
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


def calculate_inspection_cost() -> float:
    """计算来料检验成本（26 周）"""
    inspection = OPERATIONS_CONFIG["raw_materials_inspection"]
    count = sum(1 for v in inspection.values() if v)
    return count * 5000.0 * 0.5  # EUR 5k/year/supplier, half year
