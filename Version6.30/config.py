"""
TFC 仿真 — 全局配置
===================
所有可调参数集中在此文件头部。
"""

# ═══════════════════════════════════════════════════════════════
# 仿真模式
# ═══════════════════════════════════════════════════════════════
RANDOM_SEED = 42
WEEKS_PER_ROUND = 26

# 噪声开关（关闭 = 确定性仿真；开启 = 蒙特卡洛）
USE_NOISE = False

# ═══════════════════════════════════════════════════════════════
# 成本标定因子
# 设为 1.0，使用模型原始计算结果。
# 如需要对齐特定 Round 的游戏数据，可临时调整以下因子。
# ═══════════════════════════════════════════════════════════════
PURCHASE_COST_FACTOR = 1.0       # 采购成本缩放
STOCK_SPACE_FACTOR = 1.0         # 库存空间成本缩放
STOCK_INTEREST_FACTOR = 1.0      # 库存资金利息缩放
STOCK_RISK_BASELINE = 0          # 库存风险固定值（现由 expire_all() 动态计算）
DISTRIBUTION_COST_FACTOR = 1.0   # 配送成本缩放
INVENTORY_VALUE_FACTOR = 1.0     # 投资项中库存价值缩放

# ═══════════════════════════════════════════════════════════════
# 噪声参数（仅 USE_NOISE=True 时生效）
# ═══════════════════════════════════════════════════════════════
DEMAND_NOISE_STD = 0.08        # 需求波动 ±8%
PRODUCTION_NOISE_STD = 0.03    # 生产效率 ±3%
COST_NOISE_STD = 0.04          # 成本波动 ±4%

# ═══════════════════════════════════════════════════════════════
# Round 3 实际财务基线（来自 FinanceReport.csv，用于标定/验证）
# ═══════════════════════════════════════════════════════════════
BASELINE = {
    "revenue":              2_650_296.43,
    "purchase_costs":         860_934.88,
    "production_costs":       453_884.85,
    "overhead_energy":        146_876.35,
    "overhead_water":          27_749.35,
    "overhead_other":         146_451.81,
    "stock_interest":          21_820.82,
    "stock_space":            281_207.39,
    "stock_risk":             24_421.75,
    "handling_inbound":        94_262.37,
    "handling_outbound":      101_336.41,
    "admin_cost":             110_044.35,
    "distribution":           193_767.28,
    "project_cost":            10_000.0,
    "interest_ar_ap":          22_127.42,
    "fixed_building":       2_500_000.0,
    "inventory_components":   290_944.33,
    "machinery":              802_500.0,
    "payment_terms_net":      295_032.25,
    "operating_profit":       155_411.40,
    "roi":                      4.0,
}
