"""
Multi-Agent PPO 训练脚本 — 4 Agent 同时训练
============================================
使用 Independent PPO (IPPO) 训练 4 个供应链角色:
  purchasing / sales / operations / supplychain

所有 Agent 共享全局奖励 ROI%，每轮同时决策后各自独立更新策略。

用法:
  # 训练所有 Agent
  py marl/training/train_multi_agent.py --timesteps 200000

  # 快速测试
  py marl/training/train_multi_agent.py --timesteps 5000 --eval-episodes 5

  # 指定超参数
  py marl/training/train_multi_agent.py --lr 1e-4 --n-steps 2048 --ent-coef 0.005

输出:
  所有结果输出到 marl/training/training_result/multi_<HHMMSS>/
  ├── models/          # 模型文件 (.zip)
  ├── logs/            # TensorBoard 日志
  └── multi_results.json  # 训练结果 JSON

架构:
  CTDE (Centralized Training Decentralized Execution)
  - 训练时: 4 Agent 共享 Global Reward (ROI)
  - 执行时: 每个 Agent 只看自己的局部观测
  - 算法: Independent PPO (SB3)
"""

import argparse
import os
import sys
import json
import time
import copy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

import numpy as np
import torch

# ── 路径配置 ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import gymnasium as gym
from marl.env.marl_env import TFCEnv, make_env
from marl.training.single_agent_wrapper import _AGENT_IDS, _AGENT_INFO

_AGENT_ORDER = _AGENT_IDS  # ["purchasing", "sales", "operations", "supplychain"]

# ── 目录 ──
_TRAINING_DIR = os.path.dirname(os.path.abspath(__file__))
_TRAINING_RESULT_DIR = os.path.join(_TRAINING_DIR, "training_result")


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Agent PPO Trainer
# ═══════════════════════════════════════════════════════════════════════════════

class MultiAgentPPOTrainer:
    """Independent PPO trainer for multi-agent TFC environment.

    Each agent has its own PPO policy and collects independent trajectories.
    All agents share the global ROI reward (cooperative CTDE).
    """

    def __init__(
        self,
        n_rounds: int = 1,
        use_noise: bool = False,
        learning_rate: float = 3e-4,
        n_steps: int = 1024,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        ent_coef: float = 0.01,
        seed: int = 42,
        model_dir: str = "",
        log_dir: str = "",
        device: str = "auto",
    ):
        """
        Args:
            n_rounds: Episodes per round
            use_noise: Enable simulation noise
            learning_rate: PPO learning rate
            n_steps: Rollout steps per update
            batch_size: Mini-batch size
            n_epochs: PPO epochs per update
            gamma: Discount factor
            ent_coef: Entropy coefficient
            seed: Random seed
            model_dir: Model save directory
            log_dir: TensorBoard log directory
            device: "auto" / "cpu" / "cuda"
        """
        self.n_rounds = n_rounds
        self.use_noise = use_noise
        self.learning_rate = learning_rate
        self.n_steps = n_steps
        self.batch_size = batch_size
        self.n_epochs = n_epochs
        self.gamma = gamma
        self.ent_coef = ent_coef
        self.seed = seed
        self.model_dir = model_dir
        self.log_dir = log_dir
        self.device = device

        # ── Create multi-agent environment ──
        self.env = TFCEnv(
            mode="multi",
            n_rounds=n_rounds,
            use_noise=use_noise,
            reward_scale=1.0,
        )

        # ── TensorBoard writer ──
        from torch.utils.tensorboard import SummaryWriter
        self.writer = SummaryWriter(log_dir=log_dir) if log_dir else None

        # ── Create PPO models per agent ──
        self.models: Dict[str, "PPO"] = {}
        self._init_models()

    def _init_models(self):
        """Initialize one PPO model per agent."""
        from stable_baselines3 import PPO
        from stable_baselines3.common.monitor import Monitor
        from stable_baselines3.common.vec_env import DummyVecEnv

        for agent_id in _AGENT_ORDER:
            info = _AGENT_INFO[agent_id]
            obs_space = self.env.observation_spaces[agent_id]
            act_space = self.env.action_spaces[agent_id]

            # Create a wrapped env for SB3 compatibility
            # We use a dummy single-agent wrapper for training
            wrapped = _AgentEnvWrapper(
                multi_env=self.env,
                agent_id=agent_id,
            )
            vec_env = DummyVecEnv([lambda w=wrapped: w])

            model = PPO(
                "MlpPolicy",
                vec_env,
                learning_rate=self.learning_rate,
                n_steps=self.n_steps,
                batch_size=self.batch_size,
                n_epochs=self.n_epochs,
                gamma=self.gamma,
                ent_coef=self.ent_coef,
                seed=self.seed,
                verbose=0,
                tensorboard_log=self.log_dir,
                device=self.device,
            )
            self.models[agent_id] = model
            print(f"  [{agent_id}] PPO initialized: "
                  f"obs={obs_space.shape}, act=nvec={act_space.nvec[:3]}..."
                  f"({len(act_space.nvec)} dims)")

    # ── Training ──

    def train(
        self,
        total_timesteps: int = 200_000,
        save_interval: int = 50_000,
        eval_episodes: int = 20,
        verbose: bool = True,
    ) -> Dict[str, dict]:
        """Train all agents with Independent PPO.

        Training loop:
          For each agent (round-robin):
            1. Run n_steps with current policies for all agents
            2. Store experiences for the agent being trained
            3. Update that agent's policy
          Repeat until total_timesteps reached.

        Args:
            total_timesteps: Total training steps per agent
            save_interval: Save model every N steps
            eval_episodes: Evaluation episodes
            verbose: Print progress

        Returns:
            Training results per agent
        """
        print(f"\n{'=' * 70}")
        print(f"Multi-Agent PPO Training")
        print(f"{'=' * 70}")
        print(f"  Agents:       {', '.join(_AGENT_ORDER)}")
        print(f"  Timesteps:    {total_timesteps:,} per agent")
        print(f"  LR:           {self.learning_rate}")
        print(f"  n_steps:      {self.n_steps}")
        print(f"  Entropy:      {self.ent_coef}")
        print(f"  Seed:         {self.seed}")
        print(f"{'=' * 70}\n")

        # ── Pre-training baseline ──
        if verbose:
            print("Evaluating random baseline...")
        pre_roi = self._evaluate(n_episodes=eval_episodes, use_trained=False)
        if verbose:
            print(f"  Random baseline ROI: {pre_roi['mean']:.2f}% "
                  f"+- {pre_roi['std']:.2f}%")

        # ── Training loop ──
        start_time = time.time()
        timesteps_done = 0
        episode_count = 0
        roi_history = []
        best_roi = -float("inf")

        while timesteps_done < total_timesteps:
            # Collect joint experiences for one episode
            ep_roi, ep_steps = self._collect_and_train()

            timesteps_done += ep_steps
            episode_count += 1
            roi_history.append(ep_roi)

            # Progress report
            if episode_count % 10 == 0:
                recent_roi = np.mean(roi_history[-10:])
                elapsed = time.time() - start_time
                if verbose:
                    print(f"  Ep {episode_count:>5} | "
                          f"Steps: {timesteps_done:>8,}/{total_timesteps:,} | "
                          f"ROI (recent 10): {recent_roi:>6.2f}% | "
                          f"Best: {best_roi:>6.2f}% | "
                          f"Time: {elapsed:.0f}s")
                # ── TensorBoard logging ──
                if self.writer:
                    self.writer.add_scalar("train/roi_recent10", recent_roi, timesteps_done)
                    self.writer.add_scalar("train/best_roi", best_roi, timesteps_done)
                    self.writer.add_scalar("train/episodes", episode_count, timesteps_done)

            if ep_roi > best_roi:
                best_roi = ep_roi

            # Save checkpoint
            if timesteps_done % save_interval == 0 and timesteps_done > 0:
                self._save_models(f"checkpoint_{timesteps_done}")

        train_time = time.time() - start_time

        # ── Post-training evaluation ──
        if verbose:
            print(f"\nTraining complete ({train_time:.0f}s). Evaluating...")
        post_roi = self._evaluate(n_episodes=eval_episodes, use_trained=True)
        improvement = post_roi["mean"] - pre_roi["mean"]
        if verbose:
            print(f"  Trained ROI: {post_roi['mean']:.2f}% +- {post_roi['std']:.2f}%")
            print(f"  Improvement: {improvement:+.2f}% over random")

        # ── TensorBoard final metrics ──
        if self.writer:
            self.writer.add_scalar("eval/random_roi_mean", pre_roi["mean"], total_timesteps)
            self.writer.add_scalar("eval/trained_roi_mean", post_roi["mean"], total_timesteps)
            self.writer.add_scalar("eval/improvement", improvement, total_timesteps)
            self.writer.add_hparams(
                {"lr": self.learning_rate, "n_steps": self.n_steps,
                 "ent_coef": self.ent_coef, "gamma": self.gamma},
                {"final_roi": post_roi["mean"], "improvement": improvement},
            )
            self.writer.close()

        # ── Save final models ──
        self._save_models("final")

        # ── Build results ──
        results = {
            "train_config": {
                "agents": _AGENT_ORDER,
                "total_timesteps_per_agent": total_timesteps,
                "learning_rate": self.learning_rate,
                "n_steps": self.n_steps,
                "batch_size": self.batch_size,
                "n_epochs": self.n_epochs,
                "gamma": self.gamma,
                "ent_coef": self.ent_coef,
                "seed": self.seed,
            },
            "pre_random_roi": pre_roi,
            "post_trained_roi": post_roi,
            "improvement": improvement,
            "best_roi": best_roi,
            "episodes": episode_count,
            "train_time_seconds": train_time,
            "roi_history": roi_history,
        }
        return results

    def _collect_and_train(self) -> Tuple[float, int]:
        """Run one episode and train all agents.

        Returns:
            (episode_roi, steps_taken)
        """
        obs_dict, _ = self.env.reset()
        done = False
        total_reward = 0.0
        steps = 0

        # Collect full episode trajectory per agent
        trajectories = {aid: [] for aid in _AGENT_ORDER}  # aid -> [(obs, action, reward, next_obs, done), ...]

        while not done and steps < self.n_steps * 2:
            # Get actions from all agents
            actions = {}
            with torch.no_grad():  # use model predict for deterministic collection
                for aid in _AGENT_ORDER:
                    obs_tensor = torch.as_tensor(obs_dict[aid], dtype=torch.float32)
                    action, _ = self.models[aid].predict(obs_dict[aid], deterministic=False)
                    actions[aid] = action

            # Step environment
            next_obs_dict, rewards, terminated, truncated, info = self.env.step(actions)
            done = terminated or truncated
            reward_val = rewards[_AGENT_ORDER[0]]  # shared reward
            total_reward += reward_val
            steps += 1

            # Store step for each agent
            for aid in _AGENT_ORDER:
                trajectories[aid].append((
                    obs_dict[aid].copy(),
                    actions[aid].copy(),
                    reward_val,
                    next_obs_dict[aid].copy(),
                    done,
                ))

            obs_dict = next_obs_dict

            if done:
                break

        # Train each agent with rollouts
        for aid in _AGENT_ORDER:
            if len(trajectories[aid]) < 4:
                continue
            self._update_agent(aid, trajectories[aid])

        return total_reward, steps

    def _update_agent(self, agent_id: str, trajectory: List[Tuple]):
        """Update one agent's PPO policy from collected trajectory."""
        import torch as torch
        from stable_baselines3.common.utils import explained_variance

        model = self.models[agent_id]

        # Convert trajectory to tensors
        n = len(trajectory)
        obs_arr = np.stack([t[0] for t in trajectory])
        act_arr = np.stack([t[1] for t in trajectory])
        rew_arr = np.array([t[2] for t in trajectory], dtype=np.float32)
        next_obs_arr = np.stack([t[3] for t in trajectory])
        dones = np.array([t[4] for t in trajectory], dtype=np.float32)

        # Compute returns and advantages (simplified GAE)
        with torch.no_grad():
            obs_tensor = torch.as_tensor(obs_arr, dtype=torch.float32)
            next_obs_tensor = torch.as_tensor(next_obs_arr, dtype=torch.float32)

            # Get values from critic
            values = model.policy.predict_values(obs_tensor).squeeze(-1).numpy()
            next_values = model.policy.predict_values(next_obs_tensor).squeeze(-1).numpy()

        # Compute advantages (GAE-lite: 1-step TD)
        advantages = np.zeros(n, dtype=np.float32)
        returns = np.zeros(n, dtype=np.float32)
        last_gae = 0.0
        gae_lambda = 0.95

        for t in reversed(range(n)):
            if t == n - 1:
                next_val = 0.0 if dones[t] else next_values[t]
            else:
                next_val = values[t + 1] if not dones[t] else 0.0

            delta = rew_arr[t] + self.gamma * next_val - values[t]
            last_gae = delta + self.gamma * gae_lambda * (1 - dones[t]) * last_gae
            advantages[t] = last_gae
            returns[t] = advantages[t] + values[t]

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # Prepare rollout buffer data
        log_probs_old = []
        with torch.no_grad():
            obs_tensor = torch.as_tensor(obs_arr, dtype=torch.float32)
            act_tensor = torch.as_tensor(act_arr, dtype=torch.int64)
            dist = model.policy.get_distribution(obs_tensor)
            log_probs_old = dist.log_prob(act_tensor)

            # For MultiDiscrete, log_prob returns per-dimension, sum over dims
            if log_probs_old.ndim > 1:
                log_probs_old = log_probs_old.sum(dim=-1)
            log_probs_old = log_probs_old.numpy()

        # PPO update: mini-batch SGD
        indices = np.arange(n)
        adv_tensor = torch.as_tensor(advantages, dtype=torch.float32)
        ret_tensor = torch.as_tensor(returns, dtype=torch.float32)
        old_lp_tensor = torch.as_tensor(log_probs_old, dtype=torch.float32)

        clip_range = 0.2
        for epoch in range(self.n_epochs):
            np.random.shuffle(indices)
            for start in range(0, n, self.batch_size):
                batch_idx = indices[start:start + self.batch_size]
                if len(batch_idx) < 2:
                    continue

                batch_obs = torch.as_tensor(obs_arr[batch_idx], dtype=torch.float32)
                batch_act = torch.as_tensor(act_arr[batch_idx], dtype=torch.int64)
                batch_adv = adv_tensor[batch_idx]
                batch_ret = ret_tensor[batch_idx]
                batch_old_lp = old_lp_tensor[batch_idx]

                # Evaluate current policy
                dist = model.policy.get_distribution(batch_obs)
                log_prob = dist.log_prob(batch_act)
                if log_prob.ndim > 1:
                    log_prob = log_prob.sum(dim=-1)

                values_pred = model.policy.predict_values(batch_obs).squeeze(-1)
                entropy = dist.entropy()
                if entropy.ndim > 1:
                    entropy = entropy.mean(dim=-1)
                entropy = entropy.mean()

                # PPO loss
                ratio = torch.exp(log_prob - batch_old_lp)
                surr1 = ratio * batch_adv
                surr2 = torch.clamp(ratio, 1 - clip_range, 1 + clip_range) * batch_adv
                policy_loss = -torch.min(surr1, surr2).mean()

                value_loss = 0.5 * ((values_pred - batch_ret) ** 2).mean()

                loss = policy_loss + value_loss - self.ent_coef * entropy

                # Gradient step
                model.policy.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.policy.parameters(), 0.5)
                model.policy.optimizer.step()

    # ── Evaluation ──

    def _evaluate(self, n_episodes: int = 20, use_trained: bool = True) -> dict:
        """Evaluate current policies over n_episodes.

        Returns:
            {"mean": float, "std": float, "min": float, "max": float, "values": list}
        """
        roi_values = []
        for i in range(n_episodes):
            obs_dict, _ = self.env.reset(seed=self.seed + 10000 + i)
            done = False
            while not done:
                actions = {}
                for aid in _AGENT_ORDER:
                    if use_trained:
                        action, _ = self.models[aid].predict(
                            obs_dict[aid], deterministic=True)
                    else:
                        action = self.env.action_spaces[aid].sample()
                    actions[aid] = action
                obs_dict, rewards, terminated, truncated, _ = self.env.step(actions)
                done = terminated or truncated
            roi_values.append(rewards[_AGENT_ORDER[0]])

        arr = np.array(roi_values)
        return {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "values": roi_values,
        }

    # ── Save / Load ──

    def _save_models(self, tag: str):
        """Save all agent models."""
        save_dir = os.path.join(self.model_dir, tag)
        os.makedirs(save_dir, exist_ok=True)
        for aid in _AGENT_ORDER:
            path = os.path.join(save_dir, f"{aid}.zip")
            self.models[aid].save(path)
        print(f"  Models saved to: {save_dir}/")

    def load_models(self, tag: str):
        """Load all agent models."""
        from stable_baselines3 import PPO
        load_dir = os.path.join(self.model_dir, tag)
        for aid in _AGENT_ORDER:
            path = os.path.join(load_dir, f"{aid}.zip")
            if os.path.exists(path + ".zip"):
                self.models[aid] = PPO.load(path, device=self.device)
            elif os.path.exists(path):
                self.models[aid] = PPO.load(path, device=self.device)
        print(f"  Models loaded from: {load_dir}/")


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Env Wrapper — for SB3 compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class _AgentEnvWrapper(gym.Env):
    """Wraps multi-agent env to look like single-agent for SB3 model init.

    SB3 needs an env to define observation/action spaces during PPO init.
    This wrapper delegates to the multi-agent env but only exposes one agent.
    Note: This is ONLY used for SB3 PPO initialization, not for actual training.
    The actual training loop uses the multi-agent env directly.
    """

    def __init__(self, multi_env: TFCEnv, agent_id: str):
        super().__init__()
        self.multi_env = multi_env
        self.agent_id = agent_id
        self.observation_space = multi_env.observation_spaces[agent_id]
        self.action_space = multi_env.action_spaces[agent_id]

    def reset(self, seed=None, options=None):
        obs_dict, info = self.multi_env.reset(seed=seed, options=options)
        return obs_dict[self.agent_id], info

    def step(self, action):
        # Build joint actions: target agent uses 'action', others use random
        actions = {}
        for aid in _AGENT_ORDER:
            if aid == self.agent_id:
                actions[aid] = action
            else:
                # Use current model prediction or random
                actions[aid] = self.multi_env.action_spaces[aid].sample()
        obs_dict, rewards, terminated, truncated, info = self.multi_env.step(actions)
        return (
            obs_dict[self.agent_id],
            rewards[self.agent_id],
            terminated,
            truncated,
            info,
        )

    def close(self):
        self.multi_env.close()

    def render(self):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent PPO Training for TFC Supply Chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py marl/training/train_multi_agent.py --timesteps 200000
  py marl/training/train_multi_agent.py --timesteps 5000 --eval-episodes 5
  py marl/training/train_multi_agent.py --lr 1e-4 --ent-coef 0.005
        """,
    )
    parser.add_argument("--timesteps", type=int, default=200_000,
                        help="Total training timesteps per agent (default: 200,000)")
    parser.add_argument("--lr", type=float, default=3e-4,
                        help="PPO learning rate (default: 3e-4)")
    parser.add_argument("--n-steps", type=int, default=1024,
                        help="Rollout steps per update (default: 1024)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Mini-batch size (default: 64)")
    parser.add_argument("--n-epochs", type=int, default=10,
                        help="PPO epochs per update (default: 10)")
    parser.add_argument("--ent-coef", type=float, default=0.01,
                        help="Entropy coefficient (default: 0.01)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--eval-episodes", type=int, default=20,
                        help="Evaluation episodes (default: 20)")
    parser.add_argument("--noise", action="store_true",
                        help="Enable simulation noise")
    parser.add_argument("--model-dir", type=str, default="",
                        help="Model save directory (default: training_result/multi_<time>/models)")
    parser.add_argument("--log-dir", type=str, default="",
                        help="TensorBoard log directory (default: training_result/multi_<time>/logs)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress detailed output")

    args = parser.parse_args()

    # ── 路径：training_result/multi_<HHMMSS>/ ──
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.model_dir if args.model_dir else os.path.join(
        _TRAINING_RESULT_DIR, f"multi_{run_timestamp}")
    model_dir = os.path.join(run_dir, "models")
    log_dir = args.log_dir if args.log_dir else os.path.join(run_dir, "logs")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    print(f"\n{'=' * 70}")
    print("TFC Multi-Agent PPO Trainer")
    print(f"{'=' * 70}")
    print(f"Run dir:     {run_dir}")
    print(f"Model dir:   {model_dir}")
    print(f"Log dir:     {log_dir}")
    print(f"Agents:")
    for aid in _AGENT_ORDER:
        info = _AGENT_INFO[aid]
        print(f"  {aid:<15} — {info['description']} "
              f"({info['action_dims']} act, {info['obs_dims']} obs)")
    print()

    trainer = MultiAgentPPOTrainer(
        n_rounds=1,
        use_noise=args.noise,
        learning_rate=args.lr,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        n_epochs=args.n_epochs,
        ent_coef=args.ent_coef,
        seed=args.seed,
        model_dir=model_dir,
        log_dir=log_dir,
    )

    # ── Train ──
    results = trainer.train(
        total_timesteps=args.timesteps,
        save_interval=max(args.timesteps // 4, 10_000),
        eval_episodes=args.eval_episodes,
        verbose=not args.quiet,
    )

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("Training Summary")
    print(f"{'=' * 70}")
    print(f"  Random baseline ROI:   {results['pre_random_roi']['mean']:>8.2f}% "
          f"+- {results['pre_random_roi']['std']:.2f}%")
    print(f"  Trained policy ROI:    {results['post_trained_roi']['mean']:>8.2f}% "
          f"+- {results['post_trained_roi']['std']:.2f}%")
    print(f"  Improvement:           {results['improvement']:>+8.2f}%")
    print(f"  Best episode ROI:      {results['best_roi']:>8.2f}%")
    print(f"  Episodes trained:      {results['episodes']:>8}")
    print(f"  Training time:         {results['train_time_seconds']:>8.0f}s")

    # ── Save results JSON ──
    results_path = os.path.join(run_dir, "multi_results.json")
    # Serialize (skip roi_history for JSON size)
    serializable = {
        k: v for k, v in results.items()
        if k != "roi_history"
    }
    serializable["roi_history"] = [
        float(x) if isinstance(x, (np.floating, np.integer)) else x
        for x in results.get("roi_history", [])[-100:]  # last 100 only
    ]
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {results_path}")

    trainer.env.close()


if __name__ == "__main__":
    main()
