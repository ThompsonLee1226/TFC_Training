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
    # 成本明细
    mixing_fixed_cost: float = 0.0
    mixing_variable_cost: float = 0.0
    bottling_fixed_cost: float = 0.0
    bottling_variable_cost: float = 0.0
    labor_cost: float = 0.0


@dataclass
class ProductionResult:
    """一周生产结果（由 5-7 个 DailyResult 汇总）"""
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
    daily_results: List[DailyResult] = field(default_factory=list)
    weekend_overtime_days: int = 0


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

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._last_product: Optional[str] = None  # 跨天/跨周换型追踪

    # ── 工具方法 ──────────────────────────────────────────

    def _daily_available_hours(self) -> float:
        """每天可用生产小时数（Mon-Fri）"""
        shifts = _cfg("bottling.shifts_per_week", 2)
        return shifts * FACILITY.hours_per_shift

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
        """判断换型类型，返回所需小时数。同产品或首次生产返回 0。"""
        if prev_pid is None or prev_pid == curr_pid:
            return 0.0

        prev_f, curr_f = self._extract_flavor(prev_pid), self._extract_flavor(curr_pid)
        prev_s, curr_s = self._extract_size(prev_pid), self._extract_size(curr_pid)

        if curr_f != prev_f:
            return line_spec.formula_changeover_hours
        elif curr_s != prev_s:
            return line_spec.size_changeover_hours
        return 0.0

    def _check_breakdown(self) -> float:
        """离散故障模型：返回当天故障停机小时数，0 表示无故障。

        每天独立概率判断，而非按周总时间比例平滑。
        预防性维护降低故障概率；故障排除培训再乘 0.7。
        """
        pm = _cfg("bottling.general_settings.preventive_maintenance", "A little")
        daily_prob = {
            "None": 0.30,       # 30% 概率当天发生故障
            "A little": 0.20,   # 20%
            "A lot": 0.10,      # 10%
        }.get(pm, 0.20)

        training = _cfg("bottling.general_settings.solve_breakdowns_training", "No")
        if training == "Yes":
            daily_prob *= 0.7

        if self.rng.random() < daily_prob:
            return round(self.rng.uniform(1.0, 4.0), 2)  # 停机 1-4 小时
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

        if not product_targets:
            return result

        # ── 1) 故障检查（离散事件，每天独立判断）──
        breakdown = self._check_breakdown()
        result.breakdown_hours = breakdown

        # ── 2) 换型时间（跨天 + 天内）──
        changeover = 0.0
        pids = list(product_targets.keys())

        # 跨天换型：当天第一个产品 vs 前一天最后一个产品
        changeover += self._classify_changeover(self._last_product, pids[0], line_spec)

        # 天内换型：产品间切换
        for i in range(1, len(pids)):
            changeover += self._classify_changeover(pids[i - 1], pids[i], line_spec)

        # SMED action → -50%
        if _cfg("bottling.smed_action", False):
            changeover *= 0.5

        result.changeover_hours = changeover

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

        # ── 4) Mixing 时间 ──
        total_mix_hours = 0.0
        last_flavor = None
        scale = actual / total_target if total_target > 0 else 0.0

        for pid, liters in product_targets.items():
            scaled = liters * scale
            if scaled <= 0:
                continue
            # 向上取整批次数
            batches_needed = max(1, int(scaled / mixer_spec.batch_max_liters) + 1)
            flavor = self._extract_flavor(pid)
            for _ in range(batches_needed):
                total_mix_hours += mixer_spec.run_time_hours
                if flavor != last_flavor and last_flavor is not None:
                    total_mix_hours += mixer_spec.clean_time_hours
                last_flavor = flavor

        result.mixing_hours = total_mix_hours

        # ── 5) 成本计算 ──
        days_per_year = 260.0  # 5d × 52w
        hourly_rate = FACILITY.labor_cost_per_fte_annual / 52.0 / 40.0
        num_ops = line_spec.num_operators

        # 混合成本
        result.mixing_fixed_cost = mixer_spec.fixed_cost_annual / days_per_year
        result.mixing_variable_cost = total_mix_hours * mixer_spec.cost_per_hour

        # 灌装成本
        result.bottling_fixed_cost = line_spec.fixed_cost_annual / days_per_year
        result.bottling_variable_cost = (
            result.bottling_hours * line_spec.flexible_labor_per_hour * num_ops
        )

        # 人工成本（含当天内加班）
        base_mult = self.WEEKEND_OVERTIME_MULTIPLIER if is_overtime else 1.0
        total_work_hours = result.bottling_hours * num_ops + result.mixing_hours
        standard = min(total_work_hours, day_hours * num_ops)
        overtime = max(0.0, total_work_hours - day_hours * num_ops)

        result.labor_cost = (
            standard * hourly_rate * base_mult
            + overtime * hourly_rate * base_mult * 1.5
        )

        # ── 6) 更新跨天状态 ──
        result.last_product = pids[-1] if pids else None
        self._last_product = result.last_product

        return result

    # ── 周级接口（兼容旧调用方）───────────────────────────

    def simulate_week(self, week: int, plan: ProductionPlan) -> ProductionResult:
        """模拟一周生产（日级离散）。

        流程:
          1. 把 plan.batches 均匀拆到 5 个工作日
          2. 逐天调用 simulate_day()
          3. 如有缺口，周末加班 (Sat→Sun) 补产
          4. 汇总 DailyResult → ProductionResult

        对外接口与旧版完全兼容。
        """
        mixer_spec = get_mixer_spec()
        line_spec = get_bottling_line_spec()
        result = ProductionResult(week=week)

        # 无计划时仅计固定成本
        if not plan.batches:
            wpy = 52.0
            result.bottling_fixed_cost = line_spec.fixed_cost_annual / wpy
            result.mixing_cost = mixer_spec.fixed_cost_annual / wpy
            result.total_production_cost = result.bottling_fixed_cost + result.mixing_cost
            return result

        daily_hours = self._daily_available_hours()

        # ── 1) 拆分日目标：每种产品均匀分配到 5 天 ──
        daily_targets: List[Dict[str, float]] = []
        for _ in range(self.DAYS_PER_WEEK):
            day_target: Dict[str, float] = {}
            for pid, liters in plan.batches:
                day_liters = liters / self.DAYS_PER_WEEK
                if day_liters > 0.001:
                    day_target[pid] = day_liters
            daily_targets.append(day_target)

        # ── 2) 逐天模拟 (Mon-Fri) ──
        total_shortfall = 0.0
        for day_idx, targets in enumerate(daily_targets):
            day_result = self.simulate_day(
                day=day_idx + 1,
                product_targets=targets,
                day_hours=daily_hours,
                is_overtime=False,
            )
            result.daily_results.append(day_result)
            total_shortfall += day_result.shortfall_liters

            # 累计
            result.planned_liters += day_result.planned_liters
            result.actual_liters += day_result.actual_liters
            result.changeover_loss_hours += day_result.changeover_hours
            result.breakdown_loss_hours += day_result.breakdown_hours
            result.mixing_hours += day_result.mixing_hours
            result.bottling_hours += day_result.bottling_hours

        # ── 3) 周末加班（如有缺口）──
        remaining = total_shortfall
        weekend_day = 6

        while remaining > 0.1 and weekend_day <= 7:
            # 按原始周计划比例分配缺口到各产品
            ot_targets: Dict[str, float] = {}
            total_planned = sum(l for _, l in plan.batches)
            if total_planned > 0:
                for pid, liters in plan.batches:
                    ot_targets[pid] = remaining * (liters / total_planned)

            ot_result = self.simulate_day(
                day=weekend_day,
                product_targets=ot_targets,
                day_hours=daily_hours,
                is_overtime=True,
            )
            result.daily_results.append(ot_result)

            result.actual_liters += ot_result.actual_liters
            result.changeover_loss_hours += ot_result.changeover_hours
            result.breakdown_loss_hours += ot_result.breakdown_hours
            result.mixing_hours += ot_result.mixing_hours
            result.bottling_hours += ot_result.bottling_hours
            result.weekend_overtime_days += 1

            remaining -= ot_result.actual_liters
            weekend_day += 1

        # ── 4) 启动产能损失 ──
        result.startup_loss_liters = (
            result.actual_liters * (line_spec.startup_productivity_loss_pct / 100.0)
        )

        # ── 5) 汇总成本 ──
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
        result.labor_cost = sum(d.labor_cost for d in result.daily_results)
        result.total_production_cost = (
            result.mixing_cost + result.bottling_fixed_cost
            + result.bottling_variable_cost + result.labor_cost
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
