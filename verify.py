"""
TFC 仿真验证 — 与 Round 3 实际游戏数据对标

实际数据 (从 Finance 页面 Round 3):
  ROI: 6.15%
  Revenue: EUR 2,655,320
  Gross Margin: EUR 1,376,266
  Operating Profit: EUR 235,137
  Investment: EUR 3,820,615
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from simulation import TFCSimulation
from decisions import ROUND3_DECISIONS
from contracts import calibration_report


def format_money(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"EUR {val/1_000_000:,.2f}M"
    elif abs(val) >= 1_000:
        return f"EUR {val:,.0f}"
    else:
        return f"EUR {val:.2f}"


def verify():
    print("=" * 70)
    print("  TFC 橙汁游戏 — 本地仿真引擎 验证报告")
    print("  对标: Round 3 实际游戏数据")
    print("=" * 70)
    print()

    # Print calibration first
    print(calibration_report())
    print()
    print()

    # Run simulation
    print("运行仿真中 (单次)...")
    sim = TFCSimulation(ROUND3_DECISIONS, base_seed=42)
    result = sim.run_round()

    pl = result.pl
    inv = result.inv

    # Actual data for comparison
    actual = {
        "ROI (%)": 6.15,
        "Revenue": 2_655_320,
        "Gross Margin": 1_376_266,
        "Operating Profit": 235_137,
        "Investment": 3_820_615,
        "COGS (%)": 48.2,  # (2,655,320 - 1,376,266) / 2,655,320
        "Profit (%)": 8.86,  # 235,137 / 2,655,320
    }

    simulated = {
        "ROI (%)": result.roi,
        "Revenue": pl.total_revenue,
        "Gross Margin": pl.gross_margin,
        "Operating Profit": pl.operating_profit,
        "Investment": inv.total,
        "COGS (%)": (pl.cogs / pl.total_revenue * 100) if pl.total_revenue else 0,
        "Profit (%)": pl.profit_pct,
    }

    # Comparison table
    print()
    print(f"{'指标':<25} {'实际值':>14} {'仿真值':>14} {'差异':>10} {'差异%':>10}")
    print("-" * 75)

    for key in actual:
        act = actual[key]
        sim_val = simulated[key]
        diff = sim_val - act
        diff_pct = (diff / act * 100) if act != 0 else 0

        if key == "ROI (%)":
            fmt_act = f"{act:.2f}%"
            fmt_sim = f"{sim_val:.2f}%"
            fmt_diff = f"{diff:+.2f}pp"
            fmt_pct = ""
        elif "(%" in key:
            fmt_act = f"{act:.2f}%"
            fmt_sim = f"{sim_val:.2f}%"
            fmt_diff = f"{diff:+.2f}pp"
            fmt_pct = ""
        else:
            fmt_act = format_money(act)
            fmt_sim = format_money(sim_val)
            fmt_diff = format_money(diff)
            fmt_pct = f"{diff_pct:+.1f}%"

        print(f"{key:<25} {fmt_act:>14} {fmt_sim:>14} {fmt_diff:>10} {fmt_pct:>10}")

    print()
    print("=" * 70)
    print("  详细 P&L")
    print("=" * 70)
    print(f"  Contracted Sales Revenue:  {format_money(pl.contracted_sales_revenue)}")
    print(f"  Bonus or Penalty:         {format_money(pl.bonus_or_penalty)}")
    print(f"  ── Total Revenue:         {format_money(pl.total_revenue)}")
    print(f"  Purchase Costs:           {format_money(pl.purchase_costs)}")
    print(f"  Production Costs:         {format_money(pl.production_costs)}")
    print(f"  ── COGS:                  {format_money(pl.cogs)}")
    print(f"  ── Gross Margin:          {format_money(pl.gross_margin)}")
    print(f"  Overhead Costs:           {format_money(pl.overhead_costs)}")
    print(f"  Stock Costs:              {format_money(pl.stock_costs)}")
    print(f"    Interest:               {format_money(pl.stock_costs_interest)}")
    print(f"    Space:                  {format_money(pl.stock_costs_space)}")
    print(f"    Risk (obsoletes):       {format_money(pl.stock_costs_risk)}")
    print(f"  Handling Costs:           {format_money(pl.handling_costs)}")
    print(f"  Administration Costs:     {format_money(pl.administration_costs)}")
    print(f"  Distribution Costs:       {format_money(pl.distribution_costs)}")
    print(f"  Project Costs:            {format_money(pl.project_costs)}")
    print(f"  Interest AR/AP:           {format_money(pl.interest_costs_ar_ap)}")
    print(f"  ── Indirect Costs:        {format_money(pl.indirect_costs)}")
    print(f"  ── Operating Profit:      {format_money(pl.operating_profit)}")
    print(f"  Profit %:                 {pl.profit_pct:.2f}%")
    print()
    print("=" * 70)
    print("  详细 Investment")
    print("=" * 70)
    print(f"  Fixed (Building):         {format_money(inv.fixed_building)}")
    print(f"  Inventory Components:     {format_money(inv.inventory_components)}")
    print(f"  Inventory FG:             {format_money(inv.inventory_finished_goods)}")
    print(f"  Machinery:                {format_money(inv.machinery)}")
    print(f"  Payment Terms (net):      {format_money(inv.payment_terms_net)}")
    print(f"  Software:                 {format_money(inv.software)}")
    print(f"  ── Total Investment:      {format_money(inv.total)}")
    print(f"  ── ROI:                   {result.roi:.2f}%")
    print()

    # Verdict
    roi_deviation = abs(result.roi - actual["ROI (%)"])
    profit_deviation = abs(
        (pl.operating_profit - actual["Operating Profit"]) / actual["Operating Profit"] * 100
        if actual["Operating Profit"] != 0 else 0
    )

    print("=" * 70)
    print("  验证结论")
    print("=" * 70)
    if roi_deviation < 2.0:
        print(f"  [PASS] ROI deviation {roi_deviation:.1f}pp, within 2pp target")
    elif roi_deviation < 5.0:
        print(f"  [WARN] ROI deviation {roi_deviation:.1f}pp, needs Contract Index tuning")
    else:
        print(f"  [FAIL] ROI deviation {roi_deviation:.1f}pp, gap is large")

    if profit_deviation < 20:
        print(f"  [PASS] Operating Profit deviation {profit_deviation:.1f}%, within 20% target")
    else:
        print(f"  [WARN] Operating Profit deviation {profit_deviation:.1f}%")

    print()
    print("Note: Main error source = Contract Index black-box mapping + demand distribution assumptions")
    print("Tuning lever: adjust weight parameters in contracts.py")


if __name__ == "__main__":
    verify()
