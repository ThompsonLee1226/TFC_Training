# TFC 橙汁游戏 — 本地仿真引擎
#
# 四角色模块：
#   purchasing.py  — 采购决策 + 供应商 Contract Index + 运输成本
#   sales.py       — 销售决策 + 客户 Contract Index + 需求数据 + 收入计算
#   operations.py  — 运营决策 + 生产模拟器（混合+灌装）
#   supplychain.py — 供应链决策 + FIFO 库存引擎 + 仓储/配送成本
#
# 编排 & 输出：
#   simulation.py  — 四角色编排器，连接所有模块 → 输出财务结果
#   finance.py     — P&L + Investment + ROI 定义
#   config.py      — 全局配置 + 标定因子
#   entities.py    — 静态数据（供应商/客户/产品/组件/BOM/设施）
#
# 入口：
#   python main.py   — 运行仿真
#   python verify.py — 对标 Round 3 验证
