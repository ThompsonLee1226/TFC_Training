# TFC 橙汁游戏 — 本地仿真引擎

TFC (The Fresh Connection) 橙汁游戏供应链仿真模拟器，用于模拟供应链决策对经营绩效的影响。

## 项目结构

```
tfc_sim/
├── main.py          # 入口脚本：运行仿真、输出损益表与 ROI
├── simulation.py    # 仿真引擎核心：多轮 Monte Carlo 仿真
├── contracts.py     # Contract Index 模型（供应商合同与付款条件建模）
├── decisions.py     # 各轮次决策参数定义
├── entities.py      # 数据实体（工厂、供应商、产品等）
├── finance.py       # 损益表与财务报表计算
├── inventory.py     # 库存建模
├── logistics.py     # 物流与运输建模
├── production.py    # 生产与产能建模
└── verify.py        # 验证脚本
```

## 使用方法

```bash
# 运行 Round 3 仿真（默认）
python main.py

# 运行参数优化
python main.py --optimize
```

## 依赖

- Python 3.10+
- 仅使用标准库，无需额外安装第三方包
