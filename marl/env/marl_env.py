"""
TFC MARL Gymnasium 环境 — 轮级 step
=====================================
将 TFC 仿真引擎包装为标准 Gymnasium Env。

模式:
  - mode="single": 合并 4 个 Agent 的动作为一个超级动作向量，
                    单一观测空间，供 SB3 PPO 等单 Agent 算法使用。
  - mode="multi":  4 个独立 Agent，各自有动作/观测空间，
                    供 RLlib MAPPO 等多 Agent 算法使用。

用法:
  from marl.env.marl_env import TFCEnv

  # Single Agent 模式
  env = TFCEnv(mode="single")
  obs, info = env.reset(seed=42)
  action = env.action_space.sample()
  obs, reward, terminated, truncated, info = env.step(action)

  # Multi Agent 模式
  env = TFCEnv(mode="multi")
  obs_dict, info = env.reset(seed=42)
  actions = {aid: space.sample() for aid, space in env.action_spaces.items()}
  obs_dict, rewards, terminated, truncated, info = env.step(actions)
"""

import os
from typing import Dict, Tuple, Optional, Any, Union

import numpy as np

try:
    import gymnasium as gym
except ImportError:
    gym = None
    raise ImportError(
        "gymnasium is required for MARL environment. "
        "Install with: pip install gymnasium"
    )

# 先导入 marl 包以触发 marl/__init__.py 中的路径配置
from marl.env.action_codec import (
    ActionCodec, create_all_codecs,
    build_single_action_space, build_multi_action_spaces,
    decode_single_action, apply_all_actions,
    AGENT_VAR_COUNTS, _AGENT_ORDER,
)
from marl.env.observation_builder import (
    ObservationBuilder,
    extract_config_state,
    extract_result_state,
)

# 引擎模块（需在 marl 路径配置之后导入）
from Simulation.decision import sync_to_modules, validate_decisions
from Simulation.simulation import run
from Simulation.config import RANDOM_SEED, WEEKS_PER_ROUND


# ═══════════════════════════════════════════════════════════════════════════════
# TFCEnv
# ═══════════════════════════════════════════════════════════════════════════════

class TFCEnv(gym.Env):
    """TFC 供应链 MARL 环境（轮级 step）。

    每步 = 一个完整 26 周仿真 Round。
    Agent 设定决策参数 → 仿真运行 → 输出财务结果和下一轮观测。

    ## 观测空间
      - Single 模式: Box(119,) 全局观测
      - Multi 模式: Dict of Box per Agent

    ## 动作空间
      - Single 模式: MultiDiscrete(nvec_combined) ~103 维
      - Multi 模式: Dict of MultiDiscrete per Agent

    ## 奖励
      - Sparse: 最终 ROI (%) 作为每步奖励
    """

    metadata = {"render_modes": []}

    # ── 支持的 Agent ──
    AGENT_IDS = _AGENT_ORDER  # ["purchasing", "sales", "operations", "supplychain"]

    def __init__(
        self,
        mode: str = "single",
        n_rounds: int = 1,
        use_noise: bool = False,
        reward_scale: float = 1.0,
    ):
        """
        Args:
            mode: "single" | "multi"
            n_rounds: Episode 包含的 Round 数。每 Round = 26 周。
                      设为 1 表示单轮仿真（无跨轮状态传递）。
            use_noise: 是否启用仿真噪声（蒙特卡洛模式）。
            reward_scale: 奖励缩放因子。reward = ROI * reward_scale。
        """
        if mode not in ("single", "multi"):
            raise ValueError(f"mode must be 'single' or 'multi', got '{mode}'")

        self.mode = mode
        self.n_rounds = n_rounds
        self.use_noise = use_noise
        self.reward_scale = reward_scale

        # 内部状态
        self._codecs = create_all_codecs()
        self._obs_builder = ObservationBuilder()
        self._current_round = 0
        self._rng = np.random.default_rng(RANDOM_SEED)
        self._episode_seed = RANDOM_SEED

        # ── 动作空间 ──
        if mode == "single":
            self.action_space = build_single_action_space()
            self.action_spaces = None
        else:
            self.action_spaces = build_multi_action_spaces()
            self.action_space = None

        # ── 观测空间 ──
        if mode == "single":
            self.observation_space = self._obs_builder.build_global_observation_space()
            self.observation_spaces = None
        else:
            self.observation_spaces = self._obs_builder.build_local_observation_spaces()
            self.observation_space = None

    # ═══════════════════════════════════════════════════════════════════
    # Gymnasium API
    # ═══════════════════════════════════════════════════════════════════

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Tuple[Union[np.ndarray, Dict[str, np.ndarray]], dict]:
        """重置环境到初始状态。

        Args:
            seed: 随机种子。传递给仿真引擎和 numpy rng。
            options: 保留，暂未使用。

        Returns:
            (observation, info)
        """
        if seed is not None:
            self._episode_seed = seed
        else:
            self._episode_seed = RANDOM_SEED

        self._current_round = 0
        self._rng = np.random.default_rng(self._episode_seed)

        # 恢复默认决策配置并同步到各模块
        self._restore_defaults()

        # 构建初始观测（基于默认配置，仿真尚未运行）
        config_state = extract_config_state()
        empty_result = self._empty_result_state()
        info = {"round": 0, "roi": None}

        if self.mode == "single":
            obs = self._obs_builder.build_global_obs(config_state, empty_result)
            return obs.astype(np.float32), info
        else:
            obs_dict = {}
            for aid in self.AGENT_IDS:
                obs_dict[aid] = self._obs_builder.build_local_obs(
                    aid, config_state, empty_result
                ).astype(np.float32)
            return obs_dict, info

    def step(
        self, actions: Union[np.ndarray, Dict[str, np.ndarray]]
    ) -> Tuple[
        Union[np.ndarray, Dict[str, np.ndarray]],  # observation
        Union[float, Dict[str, float]],             # reward
        bool,                                        # terminated
        bool,                                        # truncated
        dict,                                        # info
    ]:
        """执行一步（一个 Round = 26 周仿真）。

        Args:
            actions:
              - single 模式: np.ndarray, shape=(n_total_dims,)
              - multi 模式:  Dict[str, np.ndarray], {agent_id: action_array}

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        # 1. 解码动作 → 写入 DECISION_CONFIG
        if self.mode == "single":
            per_agent = decode_single_action(actions)
        else:
            per_agent = actions

        apply_all_actions(per_agent)

        # 2. 验证决策合法性
        errors = validate_decisions()
        if errors:
            # 不中止仿真，但记录警告
            pass

        # 3. 同步到原始模块 → 运行仿真
        sync_to_modules()

        seed = self._episode_seed + self._current_round if self.use_noise else self._episode_seed
        result = run(seed=seed)

        # 4. 更新轮次
        self._current_round += 1

        # 5. 构建观测
        config_state = extract_config_state()
        result_state = extract_result_state(result, self._current_round)

        if self.mode == "single":
            obs = self._obs_builder.build_global_obs(config_state, result_state).astype(np.float32)
        else:
            obs = {}
            for aid in self.AGENT_IDS:
                obs[aid] = self._obs_builder.build_local_obs(
                    aid, config_state, result_state
                ).astype(np.float32)

        # 6. 计算奖励
        reward = result.roi * self.reward_scale

        if self.mode == "multi":
            # Multi 模式下各 Agent 共享同一个全局奖励 (CTDE)
            rewards = {aid: reward for aid in self.AGENT_IDS}
        else:
            rewards = reward

        # 7. 终止判断
        terminated = self._current_round >= self.n_rounds
        truncated = False

        # 8. Info
        info = {
            "round": self._current_round,
            "roi": result.roi,
            "operating_profit": result.pl.operating_profit,
            "gross_margin": result.pl.gross_margin,
            "total_revenue": result.pl.total_revenue,
            "total_investment": result.inv.total,
            "kpi_values": result.kpi_values,
        }

        return obs, rewards, terminated, truncated, info

    # ═══════════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════════

    def _restore_defaults(self):
        """恢复默认决策配置。

        通过重新加载 decision 模块来重置 DECISION_CONFIG，
        然后同步到各原始模块。
        """
        from Simulation import decision as _dec
        import importlib
        # 重新加载 decision 模块以获取默认配置
        importlib.reload(_dec)
        # 同步到原始模块
        _dec.sync_to_modules()

    @staticmethod
    def _empty_result_state() -> Dict[str, np.ndarray]:
        """生成空的（全零）结果状态，用于 reset() 时无仿真结果的场景。"""
        cfg = ObservationBuilder().cfg
        return {
            "component_stock_value": np.zeros(cfg.COMPONENT_STOCK_DIM, dtype=np.float32),
            "fg_stock_value": np.zeros(cfg.FG_STOCK_DIM, dtype=np.float32),
            "component_on_order": np.zeros(cfg.COMPONENT_ON_ORDER_DIM, dtype=np.float32),
            "sales_runtime": np.zeros(cfg.SALES_RUNTIME_DIM, dtype=np.float32),
            "production_features": np.zeros(cfg.PRODUCTION_DIM, dtype=np.float32),
            "financial": np.zeros(cfg.FINANCIAL_DIM, dtype=np.float32),
            "inventory_cost": np.zeros(cfg.INVENTORY_COST_DIM, dtype=np.float32),
            "meta": np.zeros(cfg.META_DIM, dtype=np.float32),
            "product_demand": np.zeros(cfg.FG_STOCK_DIM, dtype=np.float32),
        }

    def close(self):
        """清理资源（无外部资源需要释放）。"""
        pass

    # ═══════════════════════════════════════════════════════════════════
    # 便捷属性
    # ═══════════════════════════════════════════════════════════════════

    @property
    def total_action_dims(self) -> int:
        """总动作维度数（single 模式有效）。"""
        return sum(AGENT_VAR_COUNTS.values())

    @property
    def current_round(self) -> int:
        """当前 Round 编号 (1-indexed)。"""
        return self._current_round

    def get_codec(self, agent_id: str) -> ActionCodec:
        """获取指定 Agent 的 ActionCodec。"""
        return self._codecs[agent_id]


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════════════════════

def make_env(
    mode: str = "single",
    n_rounds: int = 1,
    use_noise: bool = False,
    **kwargs,
) -> TFCEnv:
    """创建 TFCEnv 实例的工厂函数。

    符合 SB3 的 make_vec_env 兼容接口。
    """
    return TFCEnv(mode=mode, n_rounds=n_rounds, use_noise=use_noise, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("TFC MARL Env — 自检")
    print("=" * 70)

    # ── Single Agent 模式 ──
    print("\n[1] Single Agent 模式")
    env = TFCEnv(mode="single", n_rounds=1)

    print(f"  Observation space: {env.observation_space}")
    print(f"  Action space: nvec={env.action_space.nvec[:5]}... "
          f"({len(env.action_space.nvec)} dims total)")

    print("\n  reset()...")
    obs, info = env.reset(seed=42)
    print(f"  obs shape: {obs.shape}, range=[{obs.min():.2f}, {obs.max():.2f}]")
    print(f"  info: {info}")

    print("\n  step(random_action)...")
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    print(f"  reward (ROI): {reward:.2f}%")
    print(f"  terminated: {terminated}, truncated: {truncated}")
    print(f"  info: round={info['round']}, roi={info['roi']:.2f}%, "
          f"op_profit={info['operating_profit']:,.0f}")

    env.close()
    print("  [OK] Single Agent mode works")

    # ── Multi Agent 模式 ──
    print("\n[2] Multi Agent 模式")
    env = TFCEnv(mode="multi", n_rounds=1)

    for aid in env.AGENT_IDS:
        print(f"  [{aid}] action={env.action_spaces[aid]}, "
              f"obs={env.observation_spaces[aid]}")

    print("\n  reset()...")
    obs_dict, info = env.reset(seed=42)
    for aid in env.AGENT_IDS:
        print(f"  [{aid}] obs shape: {obs_dict[aid].shape}")

    print("\n  step(random_actions)...")
    actions = {aid: env.action_spaces[aid].sample() for aid in env.AGENT_IDS}
    obs_dict, rewards, terminated, truncated, info = env.step(actions)
    for aid in env.AGENT_IDS:
        print(f"  [{aid}] reward={rewards[aid]:.2f}%")
    print(f"  terminated: {terminated}")

    env.close()
    print("  [OK] Multi Agent mode works")

    # ── 随机动作冒烟测试 ──
    print("\n[3] 随机动作冒烟测试 (100 次 step)...")
    env = TFCEnv(mode="single", n_rounds=1)
    env.reset(seed=42)

    roi_values = []
    n_steps = 100
    for i in range(n_steps):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        roi_values.append(reward)
        env.reset(seed=42 + i + 1)  # 每次 new episode

    roi_arr = np.array(roi_values)
    print(f"  ROI stats over {n_steps} random episodes:")
    print(f"    mean={roi_arr.mean():.2f}%, std={roi_arr.std():.2f}%, "
          f"min={roi_arr.min():.2f}%, max={roi_arr.max():.2f}%")

    env.close()
    print("  [OK] Random smoke test passed")

    print("\n" + "=" * 70)
    print("[OK] marl_env.py self-check completed")
