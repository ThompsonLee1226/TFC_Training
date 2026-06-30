"""
TFC 橙汁游戏 — 本地仿真引擎入口

用法:
    python main.py                    # 使用 Round 3 决策运行仿真
    python main.py --round 4          # 使用 Round 4 决策
    python main.py --optimize         # 运行参数优化
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from simulation import TFCSimulation
from decisions import ROUND3_DECISIONS
from contracts import calibration_report


def main():
    print("=" * 70)
    print("  TFC 橙汁游戏 — 本地仿真引擎")
    print("=" * 70)
    print()

    print("Contract Index 模型校准:")
    print(calibration_report())
    print()
    print()

    print("运行 Round 3 仿真 (单次)...")
    sim = TFCSimulation(ROUND3_DECISIONS, base_seed=42)
    result = sim.run_round()

    pl = result.pl
    inv = result.inv

    def fm(v):
        if abs(v) >= 1_000_000:
            return f"EUR {v/1_000_000:,.2f}M"
        return f"EUR {v:,.0f}"

    print()
    print("── 损益表 ──")
    print(f"  Revenue:           {fm(pl.total_revenue):>15}")
    print(f"  COGS:              {fm(pl.cogs):>15}")
    print(f"  Gross Margin:      {fm(pl.gross_margin):>15}")
    print(f"  Indirect Costs:    {fm(pl.indirect_costs):>15}")
    print(f"  Operating Profit:  {fm(pl.operating_profit):>15}")
    print(f"  Profit %:          {pl.profit_pct:>14.2f}%")
    print()
    print("── 投资 ──")
    print(f"  Fixed:             {fm(inv.fixed_building):>15}")
    print(f"  Inventory:         {fm(inv.total_inventory):>15}")
    print(f"  Machinery:         {fm(inv.machinery):>15}")
    print(f"  Payment Terms:     {fm(inv.payment_terms_net):>15}")
    print(f"  Total Investment:  {fm(inv.total):>15}")
    print()
    print(f"  ═══  ROI: {result.roi:.2f}%  ═══")


if __name__ == "__main__":
    main()
