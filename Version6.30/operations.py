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
import math
import random

from entities import (FACILITY, FacilityConfig, PRODUCT_MAP, BOM, COMPONENT_MAP,
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
            "Platin PET":               True,
            "AlL Vitamins":             True,
        },

        # ── Raw materials warehouse ──
        "raw_materials_warehouse": {
            "pallet_locations":   866,  # Number of pallet locations
            "permanent_employees":   4,  # Number of permanent employees (FTE)
            "intake_time_days":      4,  # Intake time (days)
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

        # ── Production sequence（手动排产顺序）──
        # 决定每天产品生产的先后顺序。换型成本取决于相邻产品是否同口味/同尺寸。
        # 提示：同口味产品排在一起可减少口味清洗（如 orange_1l → orange_pet 仅尺寸换型）
        "production_sequence": [
            "p_orange_1l", "p_orange_pet",   # 橙汁系列（同口味，仅尺寸换型）
            "p_ocp_1l", "p_ocp_pet",         # 橙C系列
            "p_om_1l", "p_om_pet",           # 橙芒系列
        ],
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
        # Max overtime hours per week (0 = no OT allowed)
        # 默认为 1 天工时；OT 按 1.5× variable cost 计费，不收 fixed cost
        "max_overtime_hours": 16,

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
            "pallet_locations": 1350,
            # Number of permanent employees (FTE)
            "permanent_employees": 5,
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
# 生产模拟器 — 日级离散仿真
# ═══════════════════════════════════════════════════════════════
#
# 设计原则：
#   - 每周拆为 5 个工作日 (Mon-Fri)，逐天模拟
#   - 故障改为离散概率事件（每天独立判断），非固定比例
#   - 换型跨天追踪：同产品连续两天 → 无需换型
#   - 周末加班自动处理工作日缺口（1.5 倍工资）
#   - 对外接口不变：simulate_week() 内部驱动日级循环
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProductionPlan:
    """单周生产计划"""
    week: int
    batches: List[Tuple[str, float]] = field(default_factory=list)  # [(product_id, liters)]


@dataclass
class DailyResult:
    """单日生产结果（日级离散模拟的最小单元）"""
    day: int                                    # 1-5 (Mon-Fri), 6-7 (weekend OT)
    planned_liters: float = 0.0
    actual_liters: float = 0.0
    shortfall_liters: float = 0.0               # 当天未完成的升数
    changeover_hours: float = 0.0
    breakdown_hours: float = 0.0                # 离散故障停机（0 = 当天无故障）
    mixing_hours: float = 0.0
    bottling_hours: float = 0.0
    last_product: Optional[str] = None          # 当天最后生产的产品（跨天换型判断）
    # 分产品实际产量（用于 simulation.py 成品入库，避免统一缩放）
    actual_by_product: Dict[str, float] = field(default_factory=dict)
    # 成本明细（对齐游戏 P&L：Bottling fixed + Permanent + Flexible + Mixer fixed + Mixer variable）
    mixing_fixed_cost: float = 0.0
    mixing_variable_cost: float = 0.0
    bottling_fixed_cost: float = 0.0
    bottling_variable_cost: float = 0.0    # Flexible manpower (仅 OT/超时, 42€/h)
    permanent_labor_cost: float = 0.0       # Permanent employees (操作员基本工资, 固定)
    labor_cost: float = 0.0                 # 保留兼容，始终为 0
    # 因 batch_min 约束导致的超额生产（升）
    excess_from_batch_min: float = 0.0
    # 当天换型次数（用于启动产能损失计算）
    num_changeovers: int = 0
    # 启动产能损失（升）— 换型后首小时产生的缺陷品
    startup_loss_liters: float = 0.0


@dataclass
class ProductionResult:
    """一周生产结果（由 5-7 个 DailyResult 汇总）"""
    week: int
    planned_liters: float = 0.0
    actual_liters: float = 0.0
    shortfall_liters: float = 0.0           # 产能不足未能生产的升数
    changeover_loss_hours: float = 0.0
    breakdown_loss_hours: float = 0.0
    startup_loss_liters: float = 0.0
    mixing_hours: float = 0.0
    bottling_hours: float = 0.0
    mixing_cost: float = 0.0
    bottling_fixed_cost: float = 0.0
    bottling_variable_cost: float = 0.0
    permanent_labor_cost: float = 0.0
    labor_cost: float = 0.0
    total_production_cost: float = 0.0
    outsourced_liters: float = 0.0
    outsourced_cost: float = 0.0
    daily_results: List[DailyResult] = field(default_factory=list)
    weekend_overtime_days: int = 0
    # 分产品实际产量 {product_id: total_liters}（用于 simulation.py 成品入库）
    actual_by_product: Dict[str, float] = field(default_factory=dict)
    # 因 batch_min 约束导致的超额生产总量
    excess_from_batch_min: float = 0.0
    # 启动产能损失导致的废品材料成本（应归入 P&L Stock Risk 而非 Production）
    waste_material_cost: float = 0.0


class ProductionSimulator:
    """双阶段（Mixing + Bottling）生产模拟器 — 日级离散仿真。

    使用 OPERATIONS_CONFIG 中的决策参数 +
    entities.py 中的 MixerSpec / BottlingLineSpec 进行日级模拟。

    核心改进：
      1. 离散故障 — 每天独立概率判断，非按周比例平滑
      2. 跨天换型 — 同产品连续两天不重复计算换型
      3. 周末加班 — 工作日做不完的缺口自动触发周末补产
    """

    DAYS_PER_WEEK = 5
    WEEKEND_OVERTIME_MULTIPLIER = 1.5
    # 灌装线操作员人数由 BottlingLineSpec.num_operators 定义，班次内已包含。
    # 混合器操作员成本计入 mixer cost_per_hour，主管/质检/维护在 overhead 中。
    # 此处不再额外添加人员，以对齐游戏基线 production cost。
    ADDITIONAL_PRODUCTION_STAFF = 0

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._last_product: Optional[str] = None  # 跨天/跨周换型追踪

    # ── 工具方法 ──────────────────────────────────────────

    def _daily_available_hours(self) -> float:
        """每天可用生产小时数（Mon-Fri），扣除预防维护时间。

        预防维护 (per operations_info.txt:116-118):
          Minimal/A little: 1h/week → 减少30%故障
          Extensive/A lot:   3h/week → 减少50%故障
        """
        shifts = _cfg("bottling.shifts_per_week", 2)
        base = shifts * FACILITY.hours_per_shift
        pm = _cfg("bottling.general_settings.preventive_maintenance", "A little")
        maint_hours_per_week = {"None": 0.0, "A little": 1.0, "A lot": 3.0}.get(pm, 1.0)
        base -= maint_hours_per_week / self.DAYS_PER_WEEK
        return max(0.0, base)

    @staticmethod
    def _extract_flavor(pid: str) -> str:
        """从 product_id 提取口味标识，如 p_orange_1l → 'orange'"""
        parts = pid.split('_')
        return parts[1] if len(parts) >= 2 else pid

    @staticmethod
    def _extract_size(pid: str) -> str:
        """从 product_id 提取包装尺寸，如 p_orange_pet → 'PET'"""
        return "PET" if "pet" in pid else "1L"

    def _classify_changeover(self, prev_pid: Optional[str], curr_pid: str,
                              line_spec: BottlingLineSpec) -> float:
        """判断换型类型，返回所需小时数。同产品或首次生产返回 0。

        换型规则（对齐 game operations_info.txt）：
          - 仅口味变化 → formula_changeover (清洗混合器)
          - 仅尺寸变化 → size_changeover (调整灌装线)
          - 口味+尺寸同时变化 → size_changeover (两者取长；所有产线 size ≥ formula)
        """
        if prev_pid is None or prev_pid == curr_pid:
            return 0.0

        prev_f, curr_f = self._extract_flavor(prev_pid), self._extract_flavor(curr_pid)
        prev_s, curr_s = self._extract_size(prev_pid), self._extract_size(curr_pid)

        flavor_changed = (curr_f != prev_f)
        size_changed = (curr_s != prev_s)

        if flavor_changed and size_changed:
            # 两者同时变化：取较长的换型时间（所有灌装线 size ≥ formula）
            return line_spec.size_changeover_hours
        elif flavor_changed:
            return line_spec.formula_changeover_hours
        elif size_changed:
            return line_spec.size_changeover_hours
        return 0.0

    def _check_breakdown(self) -> float:
        """离散故障模型：返回当天故障停机小时数，0 表示无故障。

        每天独立概率判断。
        基准故障概率 (None): 30%/天
        预防维护: A little → -30%故障概率, A lot → -50%故障概率 (per operations_info.txt:116-118)
        故障排除培训: -40%故障持续时间 (per operations_info.txt:123: "reduces breakdown duration by 40%")
        来料检验: 额外降低故障概率 (per operations_info.txt:2-5: 拒收缺陷包装 → 减少灌装线故障)

        包装材料质量 & 灌装线公差 (per purchasing_info.txt:47-48, entity_info.txt:40):
          - 供应商 quality (Poor/Middle/High): Poor → +30% 故障概率, Middle → +15%, High → 基准
          - 灌装线 tolerances (Narrow/Middle/Wide): Narrow → +25% 概率, Middle → +10%, Wide → 基准
        """
        pm = _cfg("bottling.general_settings.preventive_maintenance", "A little")
        baseline_prob = 0.30
        reduction = {"None": 0.0, "A little": 0.30, "A lot": 0.50}.get(pm, 0.30)
        daily_prob = baseline_prob * (1.0 - reduction)

        # 来料检验：检查包装材料供应商是否启用检验，拒收缺陷品 → 减少故障
        # (per operations_info.txt:2-5, purchasing_info.txt:47-48)
        inspection = _cfg("inbound.raw_materials_inspection", {})
        if inspection.get("Mono Packaging Materials", False) or \
           inspection.get("Platin PET", False):
            daily_prob *= 0.80  # 包装检验额外降低 20% 故障概率

        # 包装材料供应商质量 → 影响故障概率 (per purchasing_info.txt:47-48)
        from purchasing import SUPPLIER_DECISIONS
        quality_map = {"High": 1.0, "Middle": 1.15, "Poor": 1.30}
        # 取两个包装供应商中最差的质量水平
        pack_q = SUPPLIER_DECISIONS.get("s_pack", {}).get("quality", "High")
        pet_q = SUPPLIER_DECISIONS.get("s_pet", {}).get("quality", "Middle")
        worst_q = min(pack_q, pet_q, key=lambda q: quality_map.get(q, 1.0))
        daily_prob *= quality_map.get(worst_q, 1.0)

        # 灌装线公差 → 影响对包装缺陷的敏感度 (per entity_info.txt:40)
        line_spec = get_bottling_line_spec()
        tolerance_map = {"Wide": 1.0, "Middle": 1.10, "Narrow": 1.25}
        daily_prob *= tolerance_map.get(line_spec.tolerances, 1.0)

        if self.rng.random() < daily_prob:
            downtime = self.rng.uniform(1.0, 4.0)
            # 故障排除培训缩短持续时间 (per operations_info.txt:123)
            training = _cfg("bottling.general_settings.solve_breakdowns_training", "No")
            if training == "Yes":
                downtime *= 0.6  # -40% duration
            return round(downtime, 2)
        return 0.0

    # ── 日级模拟核心 ──────────────────────────────────────

    def simulate_day(self, day: int, product_targets: Dict[str, float],
                     day_hours: float, is_overtime: bool = False) -> DailyResult:
        """模拟单日生产。

        Args:
            day: 1-5 (Mon-Fri), 6-7 (周末加班)
            product_targets: {product_id: target_liters} 当天生产目标
            day_hours: 当天可用小时数
            is_overtime: 是否周末加班（影响工资倍率）

        Returns:
            DailyResult 包含当日实际产出和成本明细
        """
        mixer_spec = get_mixer_spec()
        line_spec = get_bottling_line_spec()
        result = DailyResult(day=day)
        days_per_year = 260.0  # 5d × 52w
        shifts = _cfg("bottling.shifts_per_week", 2)
        num_ops = line_spec.num_operators

        if not product_targets:
            # 无生产计划：仍须支付固定成本（折旧+永久员工工资）
            result.mixing_fixed_cost = mixer_spec.fixed_cost_annual / days_per_year
            result.bottling_fixed_cost = line_spec.fixed_cost_annual / days_per_year
            total_staff = num_ops * shifts + self.ADDITIONAL_PRODUCTION_STAFF
            result.permanent_labor_cost = (
                total_staff * line_spec.operator_cost_annual / days_per_year
            )
            return result

        # ── 1) 故障检查（离散事件，每天独立判断）──
        breakdown = self._check_breakdown()
        result.breakdown_hours = breakdown

        # ── 2) 换型时间（跨天 + 天内）──
        changeover = 0.0
        num_changeovers = 0
        pids = list(product_targets.keys())

        # 跨天换型：当天第一个产品 vs 前一天最后一个产品
        cross = self._classify_changeover(self._last_product, pids[0], line_spec)
        if cross > 0:
            num_changeovers += 1
        changeover += cross

        # 天内换型：产品间切换
        for i in range(1, len(pids)):
            co = self._classify_changeover(pids[i - 1], pids[i], line_spec)
            if co > 0:
                num_changeovers += 1
            changeover += co

        # SMED action → -30% (per operations_info.txt: "reduces changeover times by 30%")
        if _cfg("bottling.smed_action", False):
            changeover *= 0.7

        result.changeover_hours = changeover
        result.num_changeovers = num_changeovers

        # ── 3) Bottling 产能 ──
        effective_hours = max(0.0, day_hours - changeover - breakdown)

        capacity_per_hour = float(line_spec.capacity_liters_per_hour)
        if _cfg("bottling.increase_speed", False):
            capacity_per_hour *= 1.10

        total_target = sum(product_targets.values())
        result.planned_liters = total_target

        max_bottling = effective_hours * capacity_per_hour
        actual = min(total_target, max_bottling)
        result.actual_liters = actual
        result.shortfall_liters = max(0.0, total_target - actual)

        if capacity_per_hour > 0 and actual > 0:
            result.bottling_hours = actual / capacity_per_hour

        # ── 3b) batch_min 约束 & 分产品产量追踪 ──
        # 混合器有技术最小批量（per entity_info.txt:49: "Minimum batch size"）。
        # 若某产品日产量 ÷ 批次数 < batch_min，提升至 batch_min × 批次数。
        scale = actual / total_target if total_target > 0 else 0.0
        product_scaled: Dict[str, float] = {}
        excess_batch_min = 0.0

        for pid, liters in product_targets.items():
            scaled = liters * scale
            if scaled <= 0:
                product_scaled[pid] = 0.0
                continue
            batches_needed = max(1, math.ceil(scaled / mixer_spec.batch_max_liters))
            per_batch = scaled / batches_needed
            if per_batch < mixer_spec.batch_min_liters:
                adjusted = batches_needed * mixer_spec.batch_min_liters
                excess_batch_min += adjusted - scaled
                product_scaled[pid] = adjusted
            else:
                product_scaled[pid] = scaled

        if excess_batch_min > 0:
            actual += excess_batch_min
            result.actual_liters = actual
            if capacity_per_hour > 0:
                result.bottling_hours = actual / capacity_per_hour
            result.shortfall_liters = max(0.0, total_target - actual)
            # 全部产品等比缩放以匹配新的 actual（超额生产部分按比例分配）
            new_total = sum(product_scaled.values())
            if new_total > 0:
                for pid in product_scaled:
                    product_scaled[pid] *= actual / new_total

        result.excess_from_batch_min = excess_batch_min

        # 分产品实际产量
        for pid in product_targets:
            result.actual_by_product[pid] = product_scaled.get(pid, 0.0)

        # ── 4) Mixing 时间 ──
        # 使用 product_scaled（已含 batch_min 调整）计算批次数
        total_mix_hours = 0.0
        last_flavor = None

        for pid, liters in product_targets.items():
            scaled = product_scaled.get(pid, 0.0)
            if scaled <= 0:
                continue
            # 向上取整批次数（ceil 避免整数倍时多算一批）
            batches_needed = max(1, math.ceil(scaled / mixer_spec.batch_max_liters))
            flavor = self._extract_flavor(pid)
            for _ in range(batches_needed):
                total_mix_hours += mixer_spec.run_time_hours
                if flavor != last_flavor and last_flavor is not None:
                    total_mix_hours += mixer_spec.clean_time_hours
                last_flavor = flavor

        result.mixing_hours = total_mix_hours

        # ── 4b) 混合+灌装并行约束 ──
        # 混合器是独立资源：第一批混合完成后才能灌装，后续批次混合可与灌装并行。
        # makespan = 第一批运行时间 + max(剩余混合, 灌装总时间)
        first_batch_mix = mixer_spec.run_time_hours
        remaining_mix = max(0.0, total_mix_hours - first_batch_mix)
        makespan = first_batch_mix + max(remaining_mix, result.bottling_hours)

        if makespan > day_hours and result.actual_liters > 0.001:
            # 混合-灌装联合约束比纯灌装约束更紧，等比缩减产量
            scale_mix = day_hours / makespan
            new_actual = result.actual_liters * scale_mix
            result.actual_liters = new_actual
            result.bottling_hours = new_actual / capacity_per_hour
            result.shortfall_liters = result.planned_liters - new_actual

            # 等比缩减分产品产量 & 更新 actual_by_product
            for pid in product_scaled:
                product_scaled[pid] *= scale_mix
                result.actual_by_product[pid] = product_scaled[pid]

            # 重新计算混合时间（使用已缩减的 product_scaled）
            total_mix_hours = 0.0
            last_flavor = None
            for pid, liters in product_targets.items():
                scaled = product_scaled.get(pid, 0.0)
                if scaled <= 0:
                    continue
                batches_needed = max(1, math.ceil(scaled / mixer_spec.batch_max_liters))
                flavor = self._extract_flavor(pid)
                for _ in range(batches_needed):
                    total_mix_hours += mixer_spec.run_time_hours
                    if flavor != last_flavor and last_flavor is not None:
                        total_mix_hours += mixer_spec.clean_time_hours
                    last_flavor = flavor
            result.mixing_hours = total_mix_hours

        # ── 4c) 启动产能损失（per operations_info.txt:97-98）──
        # "Once a bottling line starts after a changeover, an initial start-up
        #  productivity loss is inevitable... this loss typically only occurs
        #  in the first hour of production."
        # 每次换型后首小时产生缺陷品 = capacity/hour × 1h × loss_pct
        if num_changeovers > 0 and result.actual_liters > 0.001:
            loss_per_co = capacity_per_hour * 1.0 * (line_spec.startup_productivity_loss_pct / 100.0)
            startup_loss = min(num_changeovers * loss_per_co, result.actual_liters)
            result.startup_loss_liters = startup_loss
            result.actual_liters -= startup_loss
            if capacity_per_hour > 0:
                result.bottling_hours = result.actual_liters / capacity_per_hour
            # 等比缩减分产品产量
            if result.actual_liters > 0:
                scale_sl = result.actual_liters / (result.actual_liters + startup_loss)
                for pid in product_scaled:
                    product_scaled[pid] *= scale_sl
                    result.actual_by_product[pid] = product_scaled[pid]

        # ── 5) 成本计算 ──
        # 对齐游戏 P&L 结构（固定成本仅工作日收取，OT 天不收）：
        #   Bottling fixed    = 设备折旧 (工作日)
        #   Permanent employees = 操作员基本工资 × 班次数 (工作日)
        #   Flexible manpower  = 仅 OT/超时 时计费: 灌装工时 × 42€/h（per ops_info:35-39）
        #                       工作日永久员工已覆盖排班产能，不额外收取灵活工费用
        #   Mixer fixed        = 混合器折旧 (工作日)
        #   Mixer variable     = 混合工时 × 135€/h
        #   周末加班 → variable cost × 1.5, 不收 fixed, 全部按灵活工计费
        days_per_year = 260.0  # 5d × 52w
        ot_mult = self.WEEKEND_OVERTIME_MULTIPLIER if is_overtime else 1.0
        num_ops = line_spec.num_operators
        shifts = _cfg("bottling.shifts_per_week", 2)

        # 混合成本
        if not is_overtime:
            result.mixing_fixed_cost = mixer_spec.fixed_cost_annual / days_per_year
        else:
            result.mixing_fixed_cost = 0.0
        result.mixing_variable_cost = (
            total_mix_hours * mixer_spec.cost_per_hour * ot_mult
        )

        # 灌装成本
        if not is_overtime:
            result.bottling_fixed_cost = line_spec.fixed_cost_annual / days_per_year
            # Permanent employees: 灌装操作员 × 班次 + 额外生产人员（混合器、主管、质检等）
            # per ops_info:104 — "Each bottling line requires a fixed number of operators per shift"
            total_staff = num_ops * shifts + self.ADDITIONAL_PRODUCTION_STAFF
            result.permanent_labor_cost = (
                total_staff * line_spec.operator_cost_annual / days_per_year
            )
            # 工作日：永久员工覆盖排班产能，不产生灵活工费用
            result.bottling_variable_cost = 0.0
        else:
            result.bottling_fixed_cost = 0.0
            result.permanent_labor_cost = 0.0
            # 周末/OT：全部按灵活工计费 (€42/h × 1.5 OT multiplier)
            result.bottling_variable_cost = (
                result.bottling_hours * line_spec.flexible_labor_per_hour * ot_mult
            )

        # labor_cost 保持为 0（兼容旧字段）
        result.labor_cost = 0.0

        # ── 6) 更新跨天状态 ──
        result.last_product = pids[-1] if pids else None
        self._last_product = result.last_product

        return result

    # ── 日计划构建（按排产序列）─────────────────────────

    def _build_daily_from_sequence(self, batches: List[Tuple[str, float]]
                                   ) -> List[Dict[str, float]]:
        """按 OPERATIONS_CONFIG mixing.production_sequence 构建日目标。

        核心逻辑：按口味分组排产，每天只生产 1 个口味的产品。
        - 同口味不同尺寸 → 仅尺寸换型（2-4h），无口味清洗（2h）
        - 不同口味 → 分配在不同天生产，避免跨口味换型
        - 每个口味分配的天数按其周需求占比计算，至少 1 天

        用户通过调整 production_sequence 顺序来控制相邻天之间的口味切换。
        """
        if not batches:
            return [{} for _ in range(self.DAYS_PER_WEEK)]

        seq = _cfg("mixing.production_sequence", [])
        batch_map = dict(batches)

        # ── 1. 从 production_sequence 中提取口味分组（保留序列顺序）──
        groups: List[Tuple[str, List[str]]] = []  # [(flavor, [pid, ...])]
        for pid in seq:
            if pid not in batch_map:
                continue
            flavor = self._extract_flavor(pid)
            if not groups or groups[-1][0] != flavor:
                groups.append((flavor, []))
            groups[-1][1].append(pid)

        # 序列外的产品追加到末尾，各自成组
        for pid, _ in batches:
            if pid not in seq:
                flavor = self._extract_flavor(pid)
                if not groups or groups[-1][0] != flavor:
                    groups.append((flavor, []))
                groups[-1][1].append(pid)

        # ── 2. 计算每组周需求 ──
        group_demand = {}
        for flavor, pids in groups:
            group_demand[flavor] = sum(batch_map.get(p, 0.0) for p in pids)
        total_demand = sum(group_demand.values())

        # ── 3. 按需求占比分配天数（最大余数法，每组至少 1 天）──
        n = self.DAYS_PER_WEEK
        n_groups = len(groups)

        if n_groups > n:
            # 组数超天数：合并需求最小的相邻组
            merged = list(groups)
            while len(merged) > n:
                min_idx = min(range(len(merged) - 1),
                             key=lambda i: group_demand.get(merged[i][0], 0)
                                         + group_demand.get(merged[i+1][0], 0))
                merged[min_idx] = (f"{merged[min_idx][0]}+{merged[min_idx+1][0]}",
                                   merged[min_idx][1] + merged[min_idx+1][1])
                # 更新 group_demand
                group_demand[merged[min_idx][0]] = (
                    group_demand.get(merged[min_idx][0], 0) +
                    group_demand.get(merged[min_idx+1][0], 0))
                merged.pop(min_idx + 1)
            groups = merged

        if n_groups <= n:
            # 按需求占比直接分配所有 n 天（每组至少 1 天）
            quotas = {f: group_demand.get(f, 0) / total_demand * n
                     for f, _ in groups} if total_demand > 0 else {f: 1 for f, _ in groups}
            raw_days = {f: max(1, int(quotas[f])) for f in quotas}
            # 调整至恰好 n 天
            total_alloc = sum(raw_days.values())
            by_frac = sorted(raw_days, key=lambda f: quotas[f] % 1.0)
            while total_alloc > n:
                for f in by_frac:
                    if raw_days[f] > 1:
                        raw_days[f] -= 1
                        total_alloc -= 1
                        break
            while total_alloc < n:
                for f in reversed(by_frac):
                    raw_days[f] += 1
                    total_alloc += 1
                    break
        else:
            raw_days = {f: 1 for f, _ in groups}

        # ── 4. 构建 daily_targets（口味组内产品也按需求占比分配天数）──
        # 核心优化：当天数 ≥ 产品数时，每天只生产 1 个产品，消除天内尺寸换型。
        # 但周需求 < batch_min 的产品不得独占一天（否则 simulate_day 会超产至 batch_min）。
        daily_targets: List[Dict[str, float]] = []
        mixer_spec = get_mixer_spec()
        batch_min = mixer_spec.batch_min_liters

        for flavor, pids in groups:
            group_days = raw_days.get(flavor, 1)
            group_total = group_demand.get(flavor, 1.0)

            # 拆分"可独立排产"和"必须共享天数"的产品
            viable_pids = [p for p in pids if batch_map.get(p, 0.0) >= batch_min]
            small_pids = [p for p in pids if batch_map.get(p, 0.0) < batch_min]

            # 所有产品都低于 batch_min → 全部走共享模式
            if not viable_pids:
                viable_pids, small_pids = small_pids, []

            if group_days >= len(viable_pids) and viable_pids:
                # 天数足够 → 每个可独立产品分配天数，每天只生产 1 个产品
                small_total = sum(batch_map.get(p, 0.0) for p in small_pids)
                # 先给 viable 产品分配天数
                viable_total = sum(batch_map.get(p, 0.0) for p in viable_pids)
                # 留出 small 产品需要的天数（至少 1 天如果 small_total > 0）
                small_days = 1 if small_total > 0 else 0
                available_days = group_days - small_days

                if available_days <= 0:
                    # 天数不足以独立排产，回退到共享模式
                    all_pids = viable_pids + small_pids
                    for _ in range(group_days):
                        day: Dict[str, float] = {}
                        for pid in all_pids:
                            day[pid] = batch_map.get(pid, 0.0) / group_days
                        daily_targets.append(day)
                    continue

                prod_quotas = {}
                for pid in viable_pids:
                    d = batch_map.get(pid, 0.0)
                    prod_quotas[pid] = (d / max(viable_total, 1.0)) * available_days if viable_total > 0 else 1.0

                prod_days = {}
                for pid in viable_pids:
                    prod_days[pid] = max(1, int(prod_quotas[pid]))

                # 调整至恰好 available_days 天
                total_pd = sum(prod_days.values())
                by_frac_p = sorted(viable_pids, key=lambda p: prod_quotas[p] % 1.0)
                while total_pd > available_days:
                    for p in by_frac_p:
                        if prod_days[p] > 1:
                            prod_days[p] -= 1
                            total_pd -= 1
                            break
                while total_pd < available_days:
                    for p in reversed(by_frac_p):
                        prod_days[p] += 1
                        total_pd += 1
                        break

                # 输出 viable 产品的独立天
                for pid in viable_pids:
                    n_days = prod_days.get(pid, 1)
                    daily_liters = batch_map.get(pid, 0.0) / n_days
                    for _ in range(n_days):
                        daily_targets.append({pid: daily_liters})

                # small 产品：按需求比例附加到已有天的末尾（与当天产品同口味，仅尺寸换型）
                if small_total > 0 and small_days > 0:
                    # 把 small 产品分配到 viable 的最后一天（或多天均分）
                    for _ in range(small_days):
                        day_idx = len(daily_targets) - small_days
                        if day_idx < 0:
                            day_idx = 0
                        # 将 small 产品附加到该天
                        target_day = daily_targets[day_idx]
                        for pid in small_pids:
                            sp_liters = batch_map.get(pid, 0.0) / small_days
                            if pid in target_day:
                                target_day[pid] = target_day[pid] + sp_liters
                            else:
                                target_day[pid] = sp_liters
            else:
                # 天数不足：每天包含多个产品（回退到均分逻辑）
                all_pids = viable_pids + small_pids
                for _ in range(group_days):
                    day: Dict[str, float] = {}
                    for pid in all_pids:
                        day[pid] = batch_map.get(pid, 0.0) / group_days
                    daily_targets.append(day)

        # 截断或补齐至 n 天
        daily_targets = daily_targets[:n]
        while len(daily_targets) < n:
            daily_targets.append({})

        return daily_targets

    @staticmethod
    def _check_component_availability(daily_targets: List[Dict[str, float]],
                                       component_stock: Dict[str, float]
                                       ) -> List[Dict[str, float]]:
        """检查组件库存是否足够支撑计划产量，不足则按产品各自缩减。

        每个产品独立检查其 BOM 中各组件的库存约束，
        仅缩减受影响的产品的产量（非全局统一缩放）。

        Args:
            daily_targets: 每天的产品目标 [{pid: liters}, ...]
            component_stock: 可用组件库存 {comp_id: available_liters}

        Returns:
            (可能缩减后的) daily_targets
        """
        if not component_stock:
            return daily_targets

        # 汇总一周各产品总需求
        total_demand: Dict[str, float] = {}
        for day in daily_targets:
            for pid, liters in day.items():
                total_demand[pid] = total_demand.get(pid, 0.0) + liters

        # 每个产品独立计算缩放因子（基于其 BOM 中最紧张的组件）
        product_scale: Dict[str, float] = {}
        for pid, demand in total_demand.items():
            if demand <= 0:
                product_scale[pid] = 1.0
                continue
            recipe = BOM.get(pid, {})
            min_scale = 1.0
            for comp_id, ratio in recipe.items():
                if comp_id not in component_stock:
                    continue  # 未传入 = 不限量
                need = demand * ratio
                available = component_stock[comp_id]
                if need > 0 and available < need:
                    scale = available / need
                    if scale < min_scale:
                        min_scale = scale
            product_scale[pid] = min_scale

        # 检查是否所有产品都不受限
        if all(s >= 1.0 for s in product_scale.values()):
            return daily_targets

        # 按各产品自己的缩放因子缩减
        # 同时检查 batch_min：缩减后若低于 batch_min，直接置零（避免 simulate_day 回弹超产）
        mixer_spec = get_mixer_spec()
        batch_min = mixer_spec.batch_min_liters
        scaled: List[Dict[str, float]] = []
        for day in daily_targets:
            s_day: Dict[str, float] = {}
            for pid, liters in day.items():
                s_liters = liters * product_scale.get(pid, 1.0)
                # 若缩减后日产量 < batch_min，该产品当天不生产
                if 0 < s_liters < batch_min:
                    s_liters = 0.0
                s_day[pid] = s_liters
            scaled.append(s_day)
        return scaled

    # ── 周级接口（兼容旧调用方）───────────────────────────

    def simulate_week(self, week: int, plan: ProductionPlan,
                      component_stock: Optional[Dict[str, float]] = None
                      ) -> ProductionResult:
        """模拟一周生产（日级离散 + 手动排产序列）。

        Args:
            week: 周次
            plan: 生产计划
            component_stock: 可选，当前可用组件库存 {comp_id: liters}。
                             传入后会自动检查 BOM 约束，不足时缩减产量。

        流程:
          1. 按 production_sequence 拆分日目标
          2. 组件库存检查 (如提供 component_stock)
          3. 逐天 simulate_day()
          4. 周末加班补缺口
          5. 汇总
        """
        # 重置跨周换型状态：周末清洗维护后，新周从干净状态开始
        self._last_product = None

        mixer_spec = get_mixer_spec()
        line_spec = get_bottling_line_spec()
        result = ProductionResult(week=week)

        # 无计划时仅计固定成本（含永久员工工资，与 simulate_day 空目标分支一致）
        if not plan.batches:
            wpy = 52.0
            days_per_year = 260.0
            result.bottling_fixed_cost = line_spec.fixed_cost_annual / wpy
            result.mixing_cost = mixer_spec.fixed_cost_annual / wpy
            # 永久员工即使不生产也需支付工资（与 simulate_day 空目标逻辑一致）
            shifts = _cfg("bottling.shifts_per_week", 2)
            total_staff = line_spec.num_operators * shifts + self.ADDITIONAL_PRODUCTION_STAFF
            result.permanent_labor_cost = (
                total_staff * line_spec.operator_cost_annual / wpy
            )
            result.total_production_cost = (
                result.bottling_fixed_cost + result.mixing_cost
                + result.permanent_labor_cost
            )
            return result

        daily_hours = self._daily_available_hours()

        # ── 1) 按排产序列拆分日目标 ──
        daily_targets = self._build_daily_from_sequence(plan.batches)

        # ── 2) 组件库存约束 ──
        if component_stock is not None:
            daily_targets = self._check_component_availability(
                daily_targets, component_stock)

        # ── 3) 逐天模拟 (Mon-Fri) ──
        total_shortfall = 0.0
        shortfall_by_product: Dict[str, float] = {}  # per-product shortfall for OT targeting
        planned_by_product: Dict[str, float] = {}     # per-product planned liters
        for day_idx, targets in enumerate(daily_targets):
            day_result = self.simulate_day(
                day=day_idx + 1,
                product_targets=targets,
                day_hours=daily_hours,
                is_overtime=False,
            )
            result.daily_results.append(day_result)
            total_shortfall += day_result.shortfall_liters

            # 追踪分产品计划量和缺口
            for pid, planned in targets.items():
                planned_by_product[pid] = planned_by_product.get(pid, 0.0) + planned
                actual_pid = day_result.actual_by_product.get(pid, 0.0)
                sf = planned - actual_pid
                if sf > 0:
                    shortfall_by_product[pid] = shortfall_by_product.get(pid, 0.0) + sf

            result.planned_liters += day_result.planned_liters
            result.actual_liters += day_result.actual_liters
            result.changeover_loss_hours += day_result.changeover_hours
            result.breakdown_loss_hours += day_result.breakdown_hours
            result.mixing_hours += day_result.mixing_hours
            result.bottling_hours += day_result.bottling_hours

        # ── 4) 周末加班（按各产品缺口比例追产，最多两天）──
        max_ot_hours = _cfg("bottling.max_overtime_hours", daily_hours)
        ot_hours_remaining = max_ot_hours

        for ot_day in [6, 7]:  # Saturday, Sunday
            if ot_hours_remaining <= 0:
                break
            # 汇总当前剩余缺口
            remaining_sf = sum(shortfall_by_product.values())
            if remaining_sf < 0.1:
                break

            # 按各产品缺口比例分配 OT 产能
            ot_targets: Dict[str, float] = {}
            for pid, sf in shortfall_by_product.items():
                if sf > 0.001:
                    ot_targets[pid] = sf * (remaining_sf / max(remaining_sf, 0.001))
                    # 确保 ot_targets 不超过剩余缺口
                    ot_targets[pid] = min(ot_targets[pid], sf)

            ot_result = self.simulate_day(
                day=ot_day,
                product_targets=ot_targets,
                day_hours=min(daily_hours, ot_hours_remaining),
                is_overtime=True,
            )

            if ot_result.actual_liters > 0.01:
                result.daily_results.append(ot_result)
                result.actual_liters += ot_result.actual_liters
                result.changeover_loss_hours += ot_result.changeover_hours
                result.breakdown_loss_hours += ot_result.breakdown_hours
                result.mixing_hours += ot_result.mixing_hours
                result.bottling_hours += ot_result.bottling_hours
                result.weekend_overtime_days += 1
                # OT 时间消耗 = 灌装 + 换型 + 故障（总占用时间，非仅有效生产时间）
                ot_time_consumed = (ot_result.bottling_hours +
                                    ot_result.changeover_hours +
                                    ot_result.breakdown_hours)
                ot_hours_remaining -= ot_time_consumed

                # 更新各产品缺口
                for pid in list(shortfall_by_product.keys()):
                    ot_produced = ot_result.actual_by_product.get(pid, 0.0)
                    shortfall_by_product[pid] = max(0.0, shortfall_by_product.get(pid, 0.0) - ot_produced)
            else:
                # 无产出则不再尝试后续 OT 天
                break

        # ── 4b) 汇总分产品产量 ──
        for day_result in result.daily_results:
            for pid, actual_liters in day_result.actual_by_product.items():
                result.actual_by_product[pid] = (
                    result.actual_by_product.get(pid, 0.0) + actual_liters)
            result.excess_from_batch_min += day_result.excess_from_batch_min

        # ── 4c) 最终产能缺口 ──
        result.shortfall_liters = max(0.0, result.planned_liters - result.actual_liters)

        # ── 4d) 外包生产（仅当需求超出 5 班制上限 168h/周时才触发）──
        # per operations_info.txt:106: "If the required capacity exceeds 168 hours
        #  per week, additional production must be outsourced."
        # 计算满足全部需求（已生产 + 缺口）所需的总生产小时
        hours_for_shortfall = (
            result.shortfall_liters / max(line_spec.capacity_liters_per_hour, 1)
        )
        total_hours_needed = result.bottling_hours + hours_for_shortfall
        if result.shortfall_liters > 0.1 and total_hours_needed > 168:
            # 内部产能已达上限，缺口外包
            result.outsourced_liters = result.shortfall_liters
            # 外包成本 = 2× 单位内部总成本（含固定折旧+人工+变动）
            # 先计算单位内部总生产成本
            total_internal_cost = (
                sum(d.mixing_fixed_cost + d.mixing_variable_cost +
                    d.bottling_fixed_cost + d.bottling_variable_cost +
                    d.permanent_labor_cost
                    for d in result.daily_results)
            )
            if result.actual_liters > 0:
                unit_internal_cost = total_internal_cost / result.actual_liters
            else:
                unit_internal_cost = (
                    mixer_spec.cost_per_hour / max(line_spec.capacity_liters_per_hour, 1) +
                    line_spec.flexible_labor_per_hour / max(line_spec.capacity_liters_per_hour, 1)
                )
            result.outsourced_cost = result.outsourced_liters * unit_internal_cost * 2.0
            # 外包产量不计入 actual_liters（非内部生产），但满足需求
            result.shortfall_liters = 0.0

        # ── 4d) 汇总启动产能损失 & 废品材料成本 ──
        # 启动损失已在 simulate_day 中从 actual_liters 扣除，
        # 此处汇总并计算对应的材料浪费成本（组件已消耗但未产出合格品）
        total_startup_loss = sum(d.startup_loss_liters for d in result.daily_results)
        result.startup_loss_liters = total_startup_loss
        waste_material_cost = 0.0
        if total_startup_loss > 0 and plan.batches:
            batch_map = dict(plan.batches)
            total_weekly_liters = sum(batch_map.values())
            if total_weekly_liters > 0:
                avg_material_cost = 0.0
                for pid, liters in batch_map.items():
                    recipe = BOM.get(pid, {})
                    mat_cost = sum(
                        ratio * COMPONENT_MAP[cid].base_price
                        for cid, ratio in recipe.items()
                    )
                    avg_material_cost += mat_cost * (liters / total_weekly_liters)
                waste_material_cost = total_startup_loss * avg_material_cost

        result.waste_material_cost = waste_material_cost

        # ── 6) 汇总成本 ──
        result.mixing_cost = sum(
            d.mixing_fixed_cost + d.mixing_variable_cost
            for d in result.daily_results
        )
        result.bottling_fixed_cost = sum(
            d.bottling_fixed_cost for d in result.daily_results
        )
        result.bottling_variable_cost = sum(
            d.bottling_variable_cost for d in result.daily_results
        )
        result.permanent_labor_cost = sum(
            d.permanent_labor_cost for d in result.daily_results
        )
        result.labor_cost = 0.0
        result.total_production_cost = (
            result.mixing_cost + result.bottling_fixed_cost
            + result.bottling_variable_cost + result.permanent_labor_cost
            + result.outsourced_cost + waste_material_cost
        )
        return result

    def make_plan(self, week: int, demand_by_product: Dict[str, float]) -> ProductionPlan:
        """根据周需求生成生产计划（接口不变）"""
        batches = [(pid, liters) for pid, liters in demand_by_product.items() if liters > 0]
        return ProductionPlan(week=week, batches=batches)


# ═══════════════════════════════════════════════════════════════
# 组件需求计算（BOM 反推）
# ═══════════════════════════════════════════════════════════════

def calculate_component_needs(product_liters: Dict[str, float]) -> Dict[str, float]:
    """
    根据成品产量计算所需组件量。

    BOM ratios 是 per-pack 用量（如 p_orange_pet: 1 pet bottle + 0.060L orange per pack）。
    因此需先将 liters 转为 packs 再乘以 ratio。

    参数:
        product_liters: {product_id: total_liters_produced_over_26_weeks}

    返回:
        {component_id: total_units_needed}
        包装组件单位为 pieces，液体组件单位为 liters
    """
    needs: Dict[str, float] = {}
    for pid, liters in product_liters.items():
        p = PRODUCT_MAP.get(pid)
        if not p:
            continue
        recipe = BOM.get(pid, {})
        packs = liters / p.liters_per_pack  # 升 → 包数
        for comp_id, ratio in recipe.items():
            needs[comp_id] = needs.get(comp_id, 0.0) + packs * ratio
    return needs


# ═══════════════════════════════════════════════════════════════
# 各 Tab 辅助计算函数
# ═══════════════════════════════════════════════════════════════

def calculate_inspection_cost(num_inbound_order_lines: int = 0) -> Dict[str, float]:
    """Inbound tab — 来料检验成本（26 周）。

    网页位置：Operations → inbound → Raw materials inspection

    成本构成 (per operations_info.txt:2-5):
      1. 固定费用: €5,000/年/供应商 (检验项目本身)
      2. 额外劳动力: 检验增加 2h/订单行 的入库操作时间，
         超出永久员工容量部分按 €42/h 灵活工计费

    Args:
        num_inbound_order_lines: 26周内的入库订单行总数

    Returns:
        {"fixed_cost": float, "extra_labor_hours": float, "total": float}
    """
    inspection = _cfg("inbound.raw_materials_inspection", {})
    count = sum(1 for v in inspection.values() if v)
    fixed_cost = count * 5000.0 * 0.5  # EUR 5k/year/supplier, half year

    # 检验额外劳动力：2h/订单行 (per operations_info.txt:2-5)
    extra_labor_hours = 0.0
    if count > 0:
        extra_labor_hours = num_inbound_order_lines * 2.0

    return {
        "fixed_cost": fixed_cost,
        "extra_labor_hours": extra_labor_hours,
        "total": fixed_cost,  # 劳动力成本在 calculate_warehouse_cost_raw_materials 中统一计算
    }


def calculate_administration_costs(num_inbound_orders: int = 0,
                                    num_inbound_order_lines: int = 0,
                                    num_outbound_orders: int = 0,
                                    num_outbound_order_lines: int = 0,
                                    num_active_suppliers: int = 5) -> Dict[str, float]:
    """管理成本（26 周）。

    网页位置：Finance → Administration costs

    成本构成 (per finance_info.txt:85-100):
      - 入库订单: €50/订单
      - 入库订单行: €10/订单行
      - 出库订单: €25/订单
      - 出库订单行: €2/订单行
      - 供应商关系维护: €40,000/年

    Returns:
        {"inbound_orders": float, "inbound_lines": float,
         "outbound_orders": float, "outbound_lines": float,
         "supplier_relations": float, "total": float}
    """
    half = 0.5  # 26 weeks

    inbound_order_cost = num_inbound_orders * 50.0
    inbound_line_cost = num_inbound_order_lines * 10.0
    outbound_order_cost = num_outbound_orders * 25.0
    outbound_line_cost = num_outbound_order_lines * 2.0
    supplier_relations = num_active_suppliers * 40000.0 * half  # €40k/year PER supplier

    total = (inbound_order_cost + inbound_line_cost +
             outbound_order_cost + outbound_line_cost +
             supplier_relations)

    return {
        "inbound_orders": inbound_order_cost,
        "inbound_lines": inbound_line_cost,
        "outbound_orders": outbound_order_cost,
        "outbound_lines": outbound_line_cost,
        "supplier_relations": supplier_relations,
        "total": total,
    }


def calculate_project_costs() -> dict:
    """汇总所有运营改进项目的成本（26周）。

    包含:
      - SMED action: €20,000/year
      - Breakdown training: €400/employee (所有操作员)
      - Speed optimization: €30,000/year
      - PET inflate module: €140,000/year
      - MCC: €10,000/year

    Returns:
        {"total": float, "details": {str: float}, "investment_delta": float}
        investment_delta 是设备投资的变动（PET inflate: +€700,000）
    """
    half = 0.5  # 26 weeks = 0.5 year
    details = {}
    investment_delta = 0.0

    # SMED: €20,000/year
    if _cfg("bottling.smed_action", False):
        details["smed"] = 20000.0 * half

    # Speed optimization: €30,000/year
    if _cfg("bottling.increase_speed", False):
        details["speed_optimization"] = 30000.0 * half

    # PET inflate: €140,000/year + €700,000 investment
    if _cfg("bottling.general_settings.inflate_pet_bottles", False):
        details["pet_inflate"] = 140000.0 * half
        investment_delta += 700000.0

    # Breakdown training: €400 × 操作员总数
    # 注：游戏中此费用不单独列在 Project costs 下（仅 SMED 在 Project costs），
    # 培训成本已隐含在 overhead / production labor 中，此处不再重复计入 project。
    # 如需启用培训成本追踪，取消下面注释：
    # training = _cfg("bottling.general_settings.solve_breakdowns_training", "No")
    # if training == "Yes":
    #     line_spec = get_bottling_line_spec()
    #     shifts = _cfg("bottling.shifts_per_week", 2)
    #     total_operators = line_spec.num_operators * shifts + ProductionSimulator.ADDITIONAL_PRODUCTION_STAFF
    #     details["breakdown_training"] = 400.0 * total_operators

    # MCC: €10,000/year
    outsource = _cfg("outbound.finished_goods_warehouse.outsource_type", "None")
    if outsource == "MCC":
        details["mcc"] = 10000.0 * half

    total = sum(details.values())
    return {"total": total, "details": details, "investment_delta": investment_delta}


def calculate_warehouse_cost_finished_goods(avg_daily_pallets: float = 0,
                                             num_outbound_order_lines: int = 0,
                                             num_obsolete_batches: int = 0,
                                             num_pallets_from_production: float = 0,
                                             num_outer_boxes: int = 0) -> Dict[str, float]:
    """Outbound tab — 成品仓库成本（26 周）。

    网页位置：Operations → outbound → Finished goods warehouse

    自营仓库 (per operations_info.txt:140-157):
      - 托盘位: €200/年/位
      - 永久员工: €40,000/年/人 (40h/week)
      - 溢出仓库: €3/托盘/天
      - 劳动力需求:
        · 生产入库上架: 6 min/托盘
        · 拣货: 10 min/订单行 + 6 min/托盘(或托盘层) + 3 min/外箱
        · 溢出仓库搬运: 6 min/托盘 × 2（往返）
        · 报废品处理: 6 min/托盘
        · 清洁整理: 4 h/天
      - 灵活工: €42/h（超出永久员工容量时）

    外包仓库 (per operations_info.txt:159-168):
      Conventional:  €1.30/pallet/day + €1.25/pallet intake + €3.00/order line dispatch
      Automated:     €1.50/pallet/day + €1.00/pallet intake + €2.50/order line dispatch
      MCC:           €10,000/year + 自动化费率 (storage cost follows automated model)

    Returns:
        {"space_cost": float, "overflow_cost": float, "perm_labor_cost": float,
         "flex_labor_cost": float, "total_labor_hours": float,
         "perm_hours_available": float, "flex_hours": float, "total": float}
    """
    fg = _cfg("outbound.finished_goods_warehouse", {})
    pallets = fg.get("pallet_locations", 1400)
    employees = fg.get("permanent_employees", 4)
    outsource = fg.get("outsource_type", "None")
    from entities import WAREHOUSE

    half_year_days = 26 * 5  # 130 working days in half year (5-day week × 26 weeks)
    weeks = 26.0
    half = 0.5

    if outsource == "Conventional":
        # per operations_info.txt: €1.30/pallet/day, €1.25/pallet intake, €3.00/order line dispatch
        storage = avg_daily_pallets * 1.30 * half_year_days
        intake = avg_daily_pallets * 1.25  # daily intake ≈ avg daily throughput
        dispatch = num_outbound_order_lines * 3.00
        space_cost = storage + intake + dispatch
        overflow_cost = 0.0
        perm_labor_cost = 0.0
        flex_labor_cost = 0.0
        total_labor_hours = 0.0
        perm_hours_available = 0.0
        flex_hours = 0.0
    elif outsource == "Automated":
        # per operations_info.txt: €1.50/pallet/day, €1.00/pallet intake, €2.50/order line dispatch
        storage = avg_daily_pallets * 1.50 * half_year_days
        intake = avg_daily_pallets * 1.00
        dispatch = num_outbound_order_lines * 2.50
        space_cost = storage + intake + dispatch
        overflow_cost = 0.0
        perm_labor_cost = 0.0
        flex_labor_cost = 0.0
        total_labor_hours = 0.0
        perm_hours_available = 0.0
        flex_hours = 0.0
    elif outsource == "MCC":
        # per operations_info.txt: €10,000/year + automated warehouse rates
        storage = avg_daily_pallets * 1.50 * half_year_days
        intake = avg_daily_pallets * 1.00
        dispatch = num_outbound_order_lines * 2.50
        space_cost = storage + intake + dispatch
        overflow_cost = 0.0
        perm_labor_cost = 0.0
        flex_labor_cost = 0.0
        total_labor_hours = 0.0
        perm_hours_available = 0.0
        flex_hours = 0.0
        # MCC年费已在 calculate_project_costs 中计入
    else:
        # ── 自营仓库 ──
        # 空间成本
        space_cost = pallets * WAREHOUSE.pallet_location_cost_annual * half
        # 溢出仓库: €3/pallet/day (per operations_info.txt:13,143)
        overflow_pallets = max(0.0, avg_daily_pallets - pallets)
        overflow_cost = overflow_pallets * WAREHOUSE.overflow_pallet_cost_per_day * half_year_days

        # ── 劳动力成本 (per operations_info.txt:145-156) ──
        # 永久员工容量: employees × 40h/week × 26 weeks
        perm_hours_available = employees * 40.0 * weeks

        # a) 生产入库上架: 6 min(0.1h)/托盘
        storing_hours = num_pallets_from_production * 0.1

        # b) 拣货: 10 min/订单行 + 6 min/托盘 + 3 min/外箱
        # 估算拣货托盘数 ≈ 出库托盘总量（avg_daily_pallets × working_days）
        outbound_pallets_total = avg_daily_pallets * half_year_days
        picking_hours = (
            num_outbound_order_lines * (10.0 / 60.0) +
            outbound_pallets_total * 0.1 +
            num_outer_boxes * (3.0 / 60.0)
        )

        # c) 清洁整理: 4 h/天
        cleaning_hours = 4.0 * half_year_days

        # d) 溢出仓库搬运: 6 min(0.1h)/托盘 × 2（往返）
        overflow_handling_hours = overflow_pallets * 0.1 * 2 * half_year_days

        # e) 报废品处理: 6 min(0.1h)/托盘 (per operations_info.txt:153)
        obsolete_hours = num_obsolete_batches * 0.1

        total_labor_hours = (storing_hours + picking_hours + cleaning_hours +
                             overflow_handling_hours + obsolete_hours)

        # 永久员工成本
        perm_labor_cost = employees * WAREHOUSE.perm_employee_cost_annual * half

        # 灵活劳动力: 超出永久员工容量的部分 × €42/h
        flex_hours = max(0.0, total_labor_hours - perm_hours_available)
        flex_labor_cost = flex_hours * 42.0  # per operations_info.txt:32

    # 报废品处理: €2.50/batch (仅外包仓库, per operations_info.txt:166)
    if outsource != "None":
        space_cost += num_obsolete_batches * 2.50

    total = space_cost + overflow_cost + perm_labor_cost + flex_labor_cost

    return {
        "space_cost": space_cost,
        "overflow_cost": overflow_cost,
        "perm_labor_cost": perm_labor_cost,
        "flex_labor_cost": flex_labor_cost,
        "total_labor_hours": total_labor_hours,
        "perm_hours_available": perm_hours_available,
        "flex_hours": flex_hours,
        "total": total,
    }


def calculate_warehouse_cost_raw_materials(avg_daily_pallets: float = 0,
                                            avg_daily_tanks: float = 0,
                                            num_inbound_order_lines: int = 0,
                                            num_ibc_overflow: int = 0,
                                            num_inbound_deliveries: int = 0,
                                            total_inbound_pallets: float = 0) -> Dict[str, float]:
    """Inbound tab — 原料仓库成本（26 周）。

    网页位置：Operations → inbound → Raw materials warehouse + Tank yard

    包含:
      - 托盘位: €200/年/位 (per operations_info.txt:9)
      - 永久员工: €40,000/年/人 (per operations_info.txt:32)
      - 溢仓: €3/托盘/天 (per operations_info.txt:13)
      - 罐区外包: €25/罐/天 + €10/次入库 + €100/次运输 (per operations_info.txt:20-22)
      - 劳动力需求 & 灵活工成本 (per operations_info.txt:24-32)

    劳动力需求明细（per operations_info.txt:24-32）:
      - 入库: 1h/订单行 + 6min/托盘
      - 配送生产: 6min/托盘 + 12min/罐
      - 清洁/维护: 4h/天
      - 溢仓搬运: 6min/托盘（往返）
      - IBC 灌装: 1h/IBC（罐区不足时）

    注意：本函数中的 space_cost / overflow_cost 由 supplychain.calculate_warehouse_costs
    统一计算并计入 P&L。此处保留计算但不再重复计入，仅返回供参考。

    Returns:
        {"space_cost": float, "labor_cost": float, "flex_labor_cost": float,
         "tank_yard_cost": float, "overflow_cost": float, "total": float}
    """
    from entities import WAREHOUSE

    inbound = _cfg("inbound.raw_materials_warehouse", {})
    pallets = inbound.get("pallet_locations", 1000)
    employees = inbound.get("permanent_employees", 5)
    intake_days = inbound.get("intake_time_days", 3)

    half_year_days = 26 * 5  # 130 working days
    weeks = 26.0
    half = 0.5

    # ── 1) 空间成本 ──
    # 托盘位固定成本
    pallet_space_cost = pallets * WAREHOUSE.pallet_location_cost_annual * half

    # 溢仓成本: 超出容量的托盘 × €3/天
    overflow_pallets = max(0.0, avg_daily_pallets - pallets)
    overflow_cost = overflow_pallets * WAREHOUSE.overflow_pallet_cost_per_day * half_year_days

    # ── 2) 罐区成本（外包）──
    # per operations_info.txt:20-22
    tank_yard_cost = (
        avg_daily_tanks * WAREHOUSE.tank_yard_cost_per_day_per_tank * half_year_days +
        num_inbound_deliveries * WAREHOUSE.tank_yard_intake_cost_per_delivery +
        num_inbound_deliveries * WAREHOUSE.tank_yard_delivery_cost_per_trip
    )

    # ── 3) 劳动力成本 ──
    # 永久员工容量: employees × 40h/week × 26 weeks
    perm_hours_available = employees * 40.0 * weeks

    # 劳动力需求计算
    # a) 入库: 1h/订单行 + 6min(0.1h)/托盘 (per operations_info.txt:24-26)
    #     intake_time_days 降低峰值但不改变总工时
    intake_hours = num_inbound_order_lines * 1.0 + total_inbound_pallets * 0.1

    # b) 配送生产: 6min(0.1h)/托盘 + 12min(0.2h)/罐
    issue_hours = (avg_daily_pallets * 0.1 + avg_daily_tanks * 0.2) * half_year_days

    # c) 清洁/维护: 4h/天
    cleaning_hours = 4.0 * half_year_days

    # d) 溢仓搬运: 6min(0.1h)/托盘 × 2（往返）
    overflow_handling_hours = overflow_pallets * 0.1 * 2 * half_year_days

    # e) IBC 灌装: 1h/IBC（罐区容量不足时）
    ibc_hours = num_ibc_overflow * 1.0

    total_labor_hours = (intake_hours + issue_hours + cleaning_hours +
                         overflow_handling_hours + ibc_hours)

    # 永久员工成本
    perm_labor_cost = employees * WAREHOUSE.perm_employee_cost_annual * half

    # 灵活劳动力: 超出永久员工容量的部分 × €42/h
    flex_hours = max(0.0, total_labor_hours - perm_hours_available)
    flex_labor_cost = flex_hours * 42.0  # per operations_info.txt:32

    # ── 4) 汇总 ──
    total = (pallet_space_cost + overflow_cost + tank_yard_cost +
             perm_labor_cost + flex_labor_cost)

    return {
        "space_cost": pallet_space_cost,
        "overflow_cost": overflow_cost,
        "tank_yard_cost": tank_yard_cost,
        "perm_labor_cost": perm_labor_cost,
        "flex_labor_cost": flex_labor_cost,
        "total": total,
        "total_labor_hours": total_labor_hours,
        "perm_hours_available": perm_hours_available,
        "flex_hours": flex_hours,
    }


def calculate_stock_interest_cost(component_stock_value: float = 0.0,
                                   finished_goods_stock_value: float = 0.0) -> Dict[str, float]:
    """库存利息成本（26 周）。

    网页位置：Finance → Stock costs → Interest Costs

    成本构成 (per finance_info.txt:56-64):
      - 组件库存: 按采购成本计价，15% 年利率
      - 成品库存: 按采购+生产成本计价，15% 年利率

    Args:
        component_stock_value: 组件平均库存价值 €
        finished_goods_stock_value: 成品平均库存价值 €

    Returns:
        {"component_interest": float, "fg_interest": float, "total": float}
    """
    annual_rate = 0.15
    half = 0.5  # 26 weeks

    component_interest = component_stock_value * annual_rate * half
    fg_interest = finished_goods_stock_value * annual_rate * half

    return {
        "component_interest": component_interest,
        "fg_interest": fg_interest,
        "total": component_interest + fg_interest,
    }


def calculate_purchasing_project_costs(dual_sourcing_suppliers: int = 0,
                                        vmi_suppliers: int = 0,
                                        supplier_development_suppliers: int = 0
                                        ) -> Dict[str, float]:
    """采购相关项目成本（26 周）。

    网页位置：Purchasing → 各项协作/项目决策

    成本构成:
      - 双源采购: €40,000/年/额外供应商 (per purchasing_info.txt:75)
      - VMI: €5,000/年/供应商 (per purchasing_info.txt:64)
      - 供应商发展: €60,000/年/供应商 (per purchasing_info.txt:69)

    Returns:
        {"dual_sourcing": float, "vmi": float, "supplier_development": float, "total": float}
    """
    half = 0.5  # 26 weeks

    dual_cost = dual_sourcing_suppliers * 40000.0 * half
    vmi_cost = vmi_suppliers * 5000.0 * half
    dev_cost = supplier_development_suppliers * 60000.0 * half

    return {
        "dual_sourcing": dual_cost,
        "vmi": vmi_cost,
        "supplier_development": dev_cost,
        "total": dual_cost + vmi_cost + dev_cost,
    }


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
