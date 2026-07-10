"""
purchasing_demo.py — Purchasing 模块演示脚本
=============================================
展示如何调用 Purchasing 模块的核心功能
"""

from purchasing import (
    SUPPLIER_DECISIONS,
    predict_supplier_ci,
    get_effective_purchase_price,
    calculate_inbound_transport,
    calculate_purchase_costs,
    calibration_report,
)
from entities import SUPPLIERS, COMPONENT_MAP


def print_section(title: str):
    """打印分隔标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def demo_ci_calculation():
    """演示 CI 指数计算"""
    print_section("1. 供应商 Contract Index 计算")
    
    print("\n当前配置下的各供应商 CI 指数：")
    print(f"{'供应商ID':<15} {'供应商名称':<30} {'CI':>10}")
    print("-" * 60)
    
    for s in SUPPLIERS:
        ci = predict_supplier_ci(s.id)
        print(f"{s.id:<15} {s.name[:28]:<30} {ci:>10.6f}")
    
    print("\n📌 CI > 1.0 表示实际采购价比基础价更高")
    print("📌 CI < 1.0 表示实际采购价比基础价更低")


def demo_effective_prices():
    """演示实际采购价格计算"""
    print_section("2. 实际采购价格（基础价 × CI）")
    
    print(f"\n{'供应商ID':<15} {'基础价 (€/L)':>15} {'CI':>10} {'实际价 (€/L)':>15}")
    print("-" * 60)
    
    for s in SUPPLIERS:
        ci = predict_supplier_ci(s.id)
        effective_price = get_effective_purchase_price(s.id)
        print(f"{s.id:<15} {s.base_price:>15.4f} {ci:>10.6f} {effective_price:>15.4f}")
    
    print("\n💡 注意：实际价 = 基础价 × CI")


def demo_transport_calculation():
    """演示运输成本计算"""
    print_section("3. 入库运输成本计算（按 100,000L 估算）")
    
    TEST_VOLUME = 100_000  # 10万升
    print(f"\n📦 测试量：{TEST_VOLUME:,.0f} L")
    print(f"{'供应商ID':<15} {'贸易单位':<10} {'距离(km)':>10} {'运输方式':>10} {'成本(€)':>18}")
    print("-" * 70)
    
    for s in SUPPLIERS:
        cost = calculate_inbound_transport(s.id, TEST_VOLUME)
        d = SUPPLIER_DECISIONS.get(s.id, {})
        trade_unit = d.get("trade_unit", "Pallet")
        distance = 500  # 默认值
        
        # 获取距离
        from purchasing import _SUPPLIER_DISTANCE
        distance = _SUPPLIER_DISTANCE.get(s.id, 500)
        
        transport_mode = "海运" if s.transport_mode.value == "BOAT" else "卡车"
        
        print(f"{s.id:<15} {trade_unit:<10} {distance:>10} {transport_mode:>10} {cost:>18,.2f}")
    
    print("\n📊 成本影响因素：距离 × 贸易单位 × 运输方式")


def demo_full_cost_analysis():
    """演示完整采购成本分析"""
    print_section("4. 完整采购成本分析（26周模拟）")
    
    # 模拟各组件需求（从 BOM 推算，这里使用示例数据）
    component_needs = {
        "pack_1l":   150_000.0,   # Pack 需求量 15万升
        "pet":       200_000.0,   # PET 需求量 20万升
        "orange":    100_000.0,   # Orange 需求量 10万升
        "mango":      80_000.0,   # Mango 需求量 8万升
        "vitamin_c":  50_000.0,   # Vitamin C 需求量 5万升
    }
    
    print("\n📋 组件需求量（26周）")
    print(f"{'组件ID':<15} {'需求(L)':>15}")
    print("-" * 35)
    for comp_id, liters in component_needs.items():
        print(f"{comp_id:<15} {liters:>15,.0f}")
    
    # 执行成本计算
    result = calculate_purchase_costs(component_needs)
    
    print(f"\n💰 总采购成本汇总")
    print("-" * 50)
    print(f"总采购金额：    {result['total_purchase']:>20,.2f} €")
    print(f"总运输成本：    {result['total_transport']:>20,.2f} €")
    print(f"总成本（采购+运输）：{result['total_purchase'] + result['total_transport']:>15,.2f} €")
    
    print(f"\n📊 各供应商明细")
    print(f"{'供应商':<15} {'采购额(€)':>18} {'运输费(€)':>18} {'合计(€)':>18} {'CI变化率':>12}")
    print("-" * 85)
    
    for s in SUPPLIERS:
        if s.id in result["by_supplier"]:
            data = result["by_supplier"][s.id]
            total = data["purchase"] + data["transport"]
            ci_delta = result["ci_deltas"].get(s.id, 1.0)
            print(f"{s.id:<15} {data['purchase']:>18,.2f} {data['transport']:>18,.2f} {total:>18,.2f} {ci_delta:>12.4f}")
    
    print("\n📌 CI变化率 > 1.0 表示合同指数上升（成本增加）")
    print("📌 CI变化率 < 1.0 表示合同指数下降（成本降低）")


def demo_scenario_comparison():
    """演示不同决策参数的成本影响对比"""
    print_section("5. 场景对比：修改供应商参数的成本影响")
    
    # 场景1：使用默认配置
    print("\n🔹 场景 1：默认配置")
    component_needs = {
        "pack_1l":   150_000.0,
        "pet":       200_000.0,
        "orange":    100_000.0,
        "mango":      80_000.0,
        "vitamin_c":  50_000.0,
    }
    result1 = calculate_purchase_costs(component_needs)
    print(f"  总采购成本：{result1['total_purchase'] + result1['total_transport']:>15,.2f} €")
    print(f"  其中采购：{result1['total_purchase']:>15,.2f} €  运输：{result1['total_transport']:>15,.2f} €")
    
    # 场景2：优化某供应商参数
    print("\n🔸 场景 2：提高 s_pack 的交付可靠性（82% → 95%）")
    
    # 修改配置（演示用，实际应该深拷贝）
    original_pack = SUPPLIER_DECISIONS["s_pack"].copy()
    SUPPLIER_DECISIONS["s_pack"]["delivery_reliability_pct"] = 95.0
    
    result2 = calculate_purchase_costs(component_needs)
    print(f"  总采购成本：{result2['total_purchase'] + result2['total_transport']:>15,.2f} €")
    print(f"  其中采购：{result2['total_purchase']:>15,.2f} €  运输：{result2['total_transport']:>15,.2f} €")
    
    # 恢复配置
    SUPPLIER_DECISIONS["s_pack"] = original_pack
    
    # 计算变化
    change_purchase = result2['total_purchase'] - result1['total_purchase']
    change_total = (result2['total_purchase'] + result2['total_transport']) - (result1['total_purchase'] + result1['total_transport'])
    
    print(f"\n📊 变化分析：")
    print(f"  采购额变化：{change_purchase:>+15,.2f} €")
    print(f"  总成本变化：{change_total:>+15,.2f} €")
    print(f"  💡 交付可靠性提高 → CI 上升 → 采购成本增加")


def demo_calibration_report():
    """演示校准报告"""
    print_section("6. 校准报告")
    print("\n" + calibration_report())
    
    print("\n📌 说明：Pred 是当前配置下的预测值，Actual 是游戏中的实际值")
    print("📌 Err 接近 0 表示模型校准良好")


def demo_what_if_analysis():
    """演示 What-If 分析：不同参数对 CI 的影响"""
    print_section("7. 参数敏感性分析（以 s_pack 为例）")
    
    supplier_id = "s_pack"
    base_ci = predict_supplier_ci(supplier_id)
    
    print(f"\n📌 基准配置下的 CI：{base_ci:.6f}")
    print(f"\n{'参数变化':<30} {'CI 变化':>15}")
    print("-" * 50)
    
    # 测试质量变化
    original_quality = SUPPLIER_DECISIONS[supplier_id]["quality"]
    SUPPLIER_DECISIONS[supplier_id]["quality"] = "Middle"
    ci_middle = predict_supplier_ci(supplier_id)
    SUPPLIER_DECISIONS[supplier_id]["quality"] = original_quality
    print(f"{'质量: High → Middle':<30} {ci_middle - base_ci:>+15.6f}")
    
    # 测试交付可靠性变化
    original_reliability = SUPPLIER_DECISIONS[supplier_id]["delivery_reliability_pct"]
    SUPPLIER_DECISIONS[supplier_id]["delivery_reliability_pct"] = 90.0
    ci_90 = predict_supplier_ci(supplier_id)
    SUPPLIER_DECISIONS[supplier_id]["delivery_reliability_pct"] = original_reliability
    print(f"{'可靠性: 96% → 90%':<30} {ci_90 - base_ci:>+15.6f}")

    # 测试付款期限变化
    original_payment = SUPPLIER_DECISIONS[supplier_id]["payment_term_weeks"]
    SUPPLIER_DECISIONS[supplier_id]["payment_term_weeks"] = 8
    ci_8w = predict_supplier_ci(supplier_id)
    SUPPLIER_DECISIONS[supplier_id]["payment_term_weeks"] = original_payment
    print(f"{'付款期限: 4周 → 8周':<30} {ci_8w - base_ci:>+15.6f}")
    
    # 测试贸易单位变化
    original_unit = SUPPLIER_DECISIONS[supplier_id]["trade_unit"]
    SUPPLIER_DECISIONS[supplier_id]["trade_unit"] = "IBC"
    ci_ibc = predict_supplier_ci(supplier_id)
    SUPPLIER_DECISIONS[supplier_id]["trade_unit"] = original_unit
    print(f"{'贸易单位: Pallet → IBC':<30} {ci_ibc - base_ci:>+15.6f}")
    
    print("\n💡 正向变化 → CI 增加 → 采购成本上升")
    print("💡 负向变化 → CI 降低 → 采购成本下降")


def main():
    """主函数：运行所有演示"""
    print("\n" + "=" * 70)
    print("  🚀 Purchasing 模块功能演示")
    print("=" * 70)
    print("\n📖 本演示展示 Purchasing 模块的核心功能：")
    print("  1. CI 指数计算")
    print("  2. 实际采购价格")
    print("  3. 运输成本")
    print("  4. 完整采购成本分析")
    print("  5. 场景对比")
    print("  6. 校准报告")
    print("  7. 参数敏感性分析")
    
    # 运行所有演示
    demo_ci_calculation()
    demo_effective_prices()
    demo_transport_calculation()
    demo_full_cost_analysis()
    demo_scenario_comparison()
    demo_calibration_report()
    demo_what_if_analysis()
    
    print("\n" + "=" * 70)
    print("  ✅ 演示完成")
    print("=" * 70)


if __name__ == "__main__":
    main()