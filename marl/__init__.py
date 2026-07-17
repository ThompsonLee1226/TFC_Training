"""
TFC MARL — 多智能体强化学习环境包装
====================================

基于 TFC 橙汁游戏仿真引擎构建的 Gymnasium 环境。

模块:
  - marl.env.marl_env:            Gymnasium Env 主类 (TFCEnv)
  - marl.env.action_codec:        动作编解码器 (MultiDiscrete ↔ 决策配置)
  - marl.env.observation_builder: 观测构建器 (仿真状态 → 观测向量)
  - marl.training:                训练脚本 (SB3 PPO / RLlib MAPPO)
  - marl.evaluation:              评估脚本
"""
import sys
import os

# 确保引擎模块可被导入（Simulation/ 包和内部 flat import 兼容）
_SIMULATION_DIR = os.path.join(os.path.dirname(__file__), '..', 'Simulation')
if _SIMULATION_DIR not in sys.path:
    sys.path.insert(0, _SIMULATION_DIR)
