"""
单智能体包装器 — 从多智能体环境中暴露单个 Agent
==================================================
将 TFCEnv(mode="multi") 包装为标准的单 Agent Gymnasium Env，
只暴露指定 Agent 的动作空间和观测空间，其余 Agent 使用默认配置。

用法:
  from marl.training.single_agent_wrapper import SingleAgentWrapper

  env = SingleAgentWrapper(agent_id="supplychain")
  obs, info = env.reset()
  action = env.action_space.sample()
  obs, reward, terminated, truncated, info = env.step(action)

支持的 Agent:
  - purchasing:   40 维动作, 65 维观测
  - sales:        24 维动作, 34 维观测
  - operations:   21 维动作, 27 维观测
  - supplychain:  18 维动作, 42 维观测
"""

from typing import Dict, Tuple, Optional, Any
import numpy as np

try:
    import gymnasium as gym
except ImportError:
    gym = None
    raise ImportError("gymnasium required. pip install gymnasium")

from marl.env.marl_env import TFCEnv


_AGENT_IDS = ["purchasing", "sales", "operations", "supplychain"]

_AGENT_INFO = {
    "purchasing": {
        "action_dims": 40,
        "obs_dims": 65,
        "description": "VP Purchasing — 供应商合同条款、质量、交货期",
    },
    "sales": {
        "action_dims": 24,
        "obs_dims": 34,
        "description": "VP Sales — 客户服务水平、保质期、促销策略",
    },
    "operations": {
        "action_dims": 21,
        "obs_dims": 27,
        "description": "VP Operations — 生产设备、班次、维护策略",
    },
    "supplychain": {
        "action_dims": 18,
        "obs_dims": 42,
        "description": "VP Supply Chain — 安全库存、批量大小、冻结期",
    },
}


class SingleAgentWrapper(gym.Env):
    """将多智能体环境中的单个 Agent 暴露为独立 Gymnasium Env。

    内部持有一个 TFCEnv(mode="multi") 实例。
    在每步中，仅目标 Agent 使用 RL 输出的动作，
    其余 Agent 使用 reset 时捕获的默认配置。

    奖励为全局 ROI%，因为单个 Agent 的决策会影响整条供应链。
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        agent_id: str,
        n_rounds: int = 1,
        use_noise: bool = False,
        reward_scale: float = 1.0,
    ):
        """
        Args:
            agent_id: 要暴露的 Agent ID
                      ("purchasing" | "sales" | "operations" | "supplychain")
            n_rounds: Episode 包含的 Round 数
            use_noise: 是否启用仿真噪声
            reward_scale: 奖励缩放因子
        """
        if agent_id not in _AGENT_IDS:
            raise ValueError(
                f"Unknown agent_id '{agent_id}'. "
                f"Must be one of {_AGENT_IDS}"
            )

        self._agent_id = agent_id
        self._info = _AGENT_INFO[agent_id]

        # 内部多智能体环境
        self._env = TFCEnv(
            mode="multi",
            n_rounds=n_rounds,
            use_noise=use_noise,
            reward_scale=reward_scale,
        )

        # 暴露目标 Agent 的空间
        self.action_space = self._env.action_spaces[agent_id]
        self.observation_space = self._env.observation_spaces[agent_id]

        # 默认动作缓存（reset 时填充）
        self._default_actions: Dict[str, np.ndarray] = {}

    # ═══════════════════════════════════════════════════════════════════
    # Gymnasium API
    # ═══════════════════════════════════════════════════════════════════

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, dict]:
        """重置环境并捕获所有 Agent 的默认动作。

        Returns:
            (target_agent_obs, info)
        """
        obs_dict, info = self._env.reset(seed=seed, options=options)

        # 捕获默认动作（reset 后 DECISION_CONFIG 已恢复默认值）
        self._default_actions = {
            aid: codec.encode().copy()
            for aid, codec in self._env._codecs.items()
        }

        return obs_dict[self._agent_id].copy(), info

    def step(
        self, action: np.ndarray
    ) -> Tuple[np.ndarray, float, bool, bool, dict]:
        """执行一步：目标 Agent 使用 RL 动作，其余使用默认。

        Args:
            action: 目标 Agent 的动作数组

        Returns:
            (obs, reward, terminated, truncated, info)
        """
        # 构建完整动作字典：默认 + RL 覆盖
        actions = {
            aid: arr.copy() for aid, arr in self._default_actions.items()
        }
        actions[self._agent_id] = action

        # 执行
        obs_dict, rewards, terminated, truncated, info = self._env.step(actions)

        return (
            obs_dict[self._agent_id].copy(),
            rewards[self._agent_id],
            terminated,
            truncated,
            info,
        )

    def close(self):
        """清理资源。"""
        self._env.close()

    # ═══════════════════════════════════════════════════════════════════
    # 便捷属性
    # ═══════════════════════════════════════════════════════════════════

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def agent_info(self) -> dict:
        return self._info.copy()

    @property
    def default_actions(self) -> Dict[str, np.ndarray]:
        """当前缓存的默认动作（每次 reset 后更新）。"""
        return {aid: arr.copy() for aid, arr in self._default_actions.items()}

    @classmethod
    def list_agents(cls) -> Dict[str, dict]:
        """列出所有可用 Agent 及其信息。"""
        return {aid: info.copy() for aid, info in _AGENT_INFO.items()}

    def _reset_defaults(self):
        """手动将所有 Agent 恢复默认（通常不需要外部调用）。"""
        self._env._restore_defaults()
        self._default_actions = {
            aid: codec.encode().copy()
            for aid, codec in self._env._codecs.items()
        }


# ═══════════════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("SingleAgentWrapper — 自检")
    print("=" * 70)

    for agent_id in _AGENT_IDS:
        info = _AGENT_INFO[agent_id]
        print(f"\n[{agent_id}] {info['description']}")
        print(f"  Action dims: {info['action_dims']}, Obs dims: {info['obs_dims']}")

        wrapper = SingleAgentWrapper(agent_id=agent_id)

        # 检查空间
        print(f"  action_space:  {wrapper.action_space}")
        print(f"  obs_space:     {wrapper.observation_space}")

        # reset + step
        obs, info = wrapper.reset(seed=42)
        print(f"  reset obs:     shape={obs.shape}, range=[{obs.min():.2f}, {obs.max():.2f}]")

        action = wrapper.action_space.sample()
        obs, reward, terminated, truncated, info = wrapper.step(action)
        print(f"  step reward:   ROI={reward:.2f}%")
        print(f"  step obs:      shape={obs.shape}, range=[{obs.min():.2f}, {obs.max():.2f}]")

        # 验证默认动作缓存
        defaults = wrapper.default_actions
        for aid, arr in defaults.items():
            assert arr is not None, f"{aid} default action is None"
        print(f"  defaults:      { {aid: f'shape={arr.shape}' for aid, arr in defaults.items()} }")

        wrapper.close()
        print(f"  [OK] {agent_id}")

    # ── 多步一致性测试 ──
    print(f"\n[一致性] supplychain 10步连续测试...")
    env = SingleAgentWrapper(agent_id="supplychain")
    obs, _ = env.reset(seed=42)
    roi_list = []
    for i in range(10):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        roi_list.append(reward)
        if terminated:
            env.reset(seed=42 + i + 1)
    print(f"  10步 ROI: mean={np.mean(roi_list):.2f}%, "
          f"std={np.std(roi_list):.2f}%, "
          f"range=[{min(roi_list):.2f}%, {max(roi_list):.2f}%]")
    env.close()
    print("  [OK]")

    print("\n" + "=" * 70)
    print("[OK] SingleAgentWrapper self-check completed")
