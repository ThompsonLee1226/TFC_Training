"""
TFC 橙汁游戏 — 本地仿真引擎入口

用法:
    python main.py
修改策略：
  1. 编辑 purchasing.py 头部 SUPPLIER_DECISIONS
  2. 编辑 sales.py 头部 CUSTOMER_DECISIONS / WEEKLY_DEMAND_PIECES
  3. 编辑 operations.py 头部 OPERATIONS_CONFIG
  4. 编辑 supplychain.py 头部 SUPPLY_CHAIN_CONFIG
  5. python main.py 查看结果
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from simulation import run_multi, calibration_reports


def fm(v):
    if abs(v) >= 1_000_000:
        return f"EUR {v/1_000_000:,.2f}M"
    return f"EUR {v:,.0f}"


def main():
    print("=" * 70)
    print("  TFC 橙汁游戏 — 本地仿真引擎")
    print("=" * 70)
    print()

    print(calibration_reports())
    print()
    print()

    print("运行仿真...")
    result = run_multi()

    pl = result.pl
    inv = result.inv

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
