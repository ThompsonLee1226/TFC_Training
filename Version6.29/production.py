"""
TFC 生产模拟 — 混合(Mixing) + 灌装(Bottling) 双阶段
含批次调度、换型时间、故障损失、生产成本计算
"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import random
from entities import FACILITY, FacilityConfig, PRODUCT_MAP, BOM, COMPONENT_MAP


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
    """生产模拟器"""

    def __init__(self, config: FacilityConfig = FACILITY, seed: int = 42):
        self.config = config
        self.rng = random.Random(seed)

    def calculate_available_hours(self, shifts_per_week: int) -> float:
        """计算每周可用生产小时数"""
        return shifts_per_week * self.config.hours_per_shift

    def simulate_week(self, week: int, plan: ProductionPlan,
                      shifts_per_week: int,
                      has_smed: bool = False,
                      has_breakdown_training: bool = False) -> ProductionResult:
        """
        模拟一周生产。
        plan: 按序生产的批次列表 [(product_id, liters), ...]
        """
        cfg = self.config
        available_hours = self.calculate_available_hours(shifts_per_week)
        result = ProductionResult(week=week)

        if not plan.batches:
            # 固定成本仍然发生
            result.bottling_fixed_cost = cfg.bottling_fixed_cost_annual / 52
            result.mixing_cost = cfg.mixer_fixed_cost_annual / 52
            result.total_production_cost = result.bottling_fixed_cost + result.mixing_cost
            return result

        # 换型损失
        num_changeovers = len(plan.batches) - 1
        changeover_time = cfg.bottling_changeover_hours * num_changeovers
        if has_smed:
            changeover_time *= 0.5  # SMED reduces changeover time by 50%
        result.changeover_loss_hours = changeover_time

        # 故障损失
        breakdown_rate = cfg.bottling_breakdown_rate_pct / 100
        if has_breakdown_training:
            breakdown_rate *= 0.7  # Training reduces breakdown by 30%
        result.breakdown_loss_hours = available_hours * breakdown_rate * self.rng.uniform(0.5, 1.5)

        # 可用灌装小时
        bottling_available = available_hours - changeover_time - result.breakdown_loss_hours
        if bottling_available < 0:
            bottling_available = 0

        # 计算实际产量
        total_liters = sum(liters for _, liters in plan.batches)
        result.planned_liters = total_liters

        max_bottling_liters = bottling_available * cfg.bottling_liters_per_hour * cfg.num_bottling_lines
        result.actual_liters = min(total_liters, max_bottling_liters)
        result.bottling_hours = result.actual_liters / (cfg.bottling_liters_per_hour * cfg.num_bottling_lines)

        # 混合时间
        last_flavor = None
        total_mix_hours = 0.0
        for product_id, liters in plan.batches:
            # 按比例算批次
            actual_liters_for_product = liters * (result.actual_liters / total_liters) if total_liters > 0 else 0
            batches_needed = max(1, int(actual_liters_for_product / cfg.mixer_max_batch_liters) + 1)
            flavor = product_id.split('_')[1] if '_' in product_id else product_id  # orange / ocp / om
            for _ in range(batches_needed):
                total_mix_hours += cfg.mixer_run_time_hours
                if flavor != last_flavor and last_flavor is not None:
                    total_mix_hours += cfg.mixer_clean_time_hours
                last_flavor = flavor

        result.mixing_hours = total_mix_hours

        # 成本计算 (按周分摊)
        weeks_per_year = 52
        # Mixer 固定成本
        mixer_fixed_weekly = cfg.mixer_fixed_cost_annual / weeks_per_year
        # Mixer 可变成本
        mixer_variable = total_mix_hours * cfg.mixer_variable_cost_per_hour
        # Bottling 固定成本 (2条线)
        bottling_fixed_weekly = cfg.bottling_fixed_cost_annual / weeks_per_year
        # Bottling 可变 (maintenance per hour)
        bottling_variable = result.bottling_hours * 80.0  # €80/hour/line maintenance

        # 劳动力 (永久员工 + 加班)
        permanent_labor_weekly = cfg.permanent_production_fte * cfg.labor_cost_per_fte_annual / weeks_per_year
        # 如果实际工作时长超过标准40h则有加班
        standard_hours = shifts_per_week * 8
        total_labor_hours_needed = result.mixing_hours + result.bottling_hours * cfg.num_bottling_lines
        overtime = max(0, total_labor_hours_needed - standard_hours * cfg.permanent_production_fte)
        overtime_cost = overtime * (cfg.labor_cost_per_fte_annual / 52 / 40) * 1.5  # 1.5x overtime

        result.mixing_cost = mixer_fixed_weekly + mixer_variable
        result.bottling_fixed_cost = bottling_fixed_weekly
        result.bottling_variable_cost = bottling_variable
        result.labor_cost = permanent_labor_weekly + overtime_cost
        result.total_production_cost = (
            result.mixing_cost + result.bottling_fixed_cost +
            result.bottling_variable_cost + result.labor_cost
        )

        return result

    def generate_weekly_plan(self, week: int, total_weekly_demand_liters: float,
                              product_mix: Dict[str, float]) -> ProductionPlan:
        """
        根据周需求和产品配比生成生产计划。
        product_mix: {product_id: proportion} (sum=1.0)
        """
        batches = []
        for product_id, proportion in product_mix.items():
            if proportion > 0:
                liters = total_weekly_demand_liters * proportion
                batches.append((product_id, liters))
        return ProductionPlan(week=week, batches=batches)
