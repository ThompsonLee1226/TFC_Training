"""
单智能体 PPO 训练脚本
======================
使用 Stable-Baselines3 PPO 训练单个供应链角色的 RL 策略。

用法:
  # 训练 SupplyChain Agent
  py marl/training/train_single_agent.py --agent supplychain --timesteps 100000

  # 训练 Purchasing Agent
  py marl/training/train_single_agent.py --agent purchasing --timesteps 200000

  # 训练所有 Agent（依次）
  py marl/training/train_single_agent.py --agent all --timesteps 100000

依赖:
  pip install stable-baselines3 gymnasium torch tensorboard
"""

import argparse
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# 确保 TFC_Training 在 Python 路径中
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from marl.training.single_agent_wrapper import SingleAgentWrapper, _AGENT_IDS, _AGENT_INFO
from marl.env.marl_env import TFCEnv  # noqa: F401 — 确保 marl 包初始化


# ═══════════════════════════════════════════════════════════════════════════════
# 默认路径
# ═══════════════════════════════════════════════════════════════════════════════

_MARL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_DIR = os.path.join(_MARL_DIR, "models")
DEFAULT_LOG_DIR = os.path.join(_MARL_DIR, "logs")


# ═══════════════════════════════════════════════════════════════════════════════
# 训练
# ═══════════════════════════════════════════════════════════════════════════════

def train_agent(
    agent_id: str,
    total_timesteps: int = 100_000,
    learning_rate: float = 3e-4,
    n_steps: int = 1024,
    ent_coef: float = 0.01,
    seed: int = 42,
    model_dir: str = DEFAULT_MODEL_DIR,
    log_dir: str = DEFAULT_LOG_DIR,
    eval_episodes: int = 20,
    verbose: int = 1,
) -> dict:
    """训练单个 Agent 并返回结果摘要。

    Args:
        agent_id: 要训练的 Agent ID
        total_timesteps: 总训练步数
        learning_rate: PPO 学习率
        n_steps: 每次 rollout 的步数
        ent_coef: 熵正则化系数
        seed: 随机种子
        model_dir: 模型保存目录
        log_dir: TensorBoard 日志目录
        eval_episodes: 最终评估的 episode 数
        verbose: SB3 verbose level

    Returns:
        训练结果摘要 dict
    """
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import EvalCallback
    from stable_baselines3.common.monitor import Monitor

    info = _AGENT_INFO[agent_id]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"{agent_id}_{timestamp}"

    print(f"\n{'=' * 70}")
    print(f"Training: {agent_id} — {info['description']}")
    print(f"  Action dims:  {info['action_dims']}")
    print(f"  Observation dims: {info['obs_dims']}")
    print(f"  Timesteps:    {total_timesteps:,}")
    print(f"  Learning rate: {learning_rate}")
    print(f"  Seed:          {seed}")
    print(f"  Log dir:       {log_dir}")
    print(f"{'=' * 70}\n")

    # 创建环境
    env = SingleAgentWrapper(agent_id=agent_id, n_rounds=1, use_noise=False)
    env = Monitor(env)  # 记录 episode 统计

    # ── 训练前基线评估 ──
    print("Evaluating random baseline...")
    pre_roi_list = []
    for i in range(eval_episodes):
        obs, _ = env.reset(seed=seed + i)
        done = False
        while not done:
            action = env.action_space.sample()
            obs, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
        pre_roi_list.append(reward)
    pre_mean = np.mean(pre_roi_list)
    pre_std = np.std(pre_roi_list)
    print(f"  Random baseline: ROI = {pre_mean:.2f}% ± {pre_std:.2f}% "
          f"(over {eval_episodes} episodes)")

    # ── PPO 训练 ──
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=learning_rate,
        n_steps=n_steps,
        ent_coef=ent_coef,
        seed=seed,
        verbose=verbose,
        tensorboard_log=log_dir,
    )

    print(f"\nTraining PPO for {total_timesteps:,} timesteps...")
    start_time = time.time()

    model.learn(total_timesteps=total_timesteps, progress_bar=True)

    train_time = time.time() - start_time
    print(f"Training completed in {train_time:.0f}s ({train_time/60:.1f} min)")

    # ── 训练后评估 ──
    print(f"\nEvaluating trained policy ({eval_episodes} episodes)...")
    post_roi_list = []
    obs, _ = env.reset(seed=seed + 9999)  # 不同 seed
    for i in range(eval_episodes):
        obs, _ = env.reset(seed=seed + 10000 + i)
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
        post_roi_list.append(reward)
    post_mean = np.mean(post_roi_list)
    post_std = np.std(post_roi_list)
    improvement = post_mean - pre_mean
    print(f"  Trained policy:  ROI = {post_mean:.2f}% ± {post_std:.2f}%")
    print(f"  Improvement:     {improvement:+.2f}% over random baseline")

    # ── 保存模型 ──
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, run_name)
    model.save(model_path)
    print(f"\nModel saved to: {model_path}.zip")

    env.close()

    return {
        "agent_id": agent_id,
        "run_name": run_name,
        "timesteps": total_timesteps,
        "train_time_seconds": train_time,
        "pre_random_roi_mean": pre_mean,
        "pre_random_roi_std": pre_std,
        "post_trained_roi_mean": post_mean,
        "post_trained_roi_std": post_std,
        "improvement": improvement,
        "model_path": model_path,
        "seed": seed,
        "hyperparams": {
            "learning_rate": learning_rate,
            "n_steps": n_steps,
            "ent_coef": ent_coef,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Train a single TFC agent with SB3 PPO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available agents:
  purchasing   — {_AGENT_INFO['purchasing']['description']}
  sales        — {_AGENT_INFO['sales']['description']}
  operations   — {_AGENT_INFO['operations']['description']}
  supplychain  — {_AGENT_INFO['supplychain']['description']}
  all          — Train all 4 agents sequentially

Examples:
  py marl/training/train_single_agent.py --agent supplychain
  py marl/training/train_single_agent.py --agent purchasing --timesteps 200000
  py marl/training/train_single_agent.py --agent all --timesteps 50000
        """,
    )
    parser.add_argument(
        "--agent", type=str, required=True,
        help=f"Agent ID to train. Choices: {', '.join(_AGENT_IDS)}, all",
    )
    parser.add_argument(
        "--timesteps", type=int, default=100_000,
        help="Total training timesteps (default: 100,000)",
    )
    parser.add_argument(
        "--lr", type=float, default=3e-4,
        help="PPO learning rate (default: 3e-4)",
    )
    parser.add_argument(
        "--n-steps", type=int, default=1024,
        help="Rollout steps per update (default: 1024)",
    )
    parser.add_argument(
        "--ent-coef", type=float, default=0.01,
        help="Entropy coefficient (default: 0.01)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--model-dir", type=str, default=DEFAULT_MODEL_DIR,
        help=f"Model save directory (default: {DEFAULT_MODEL_DIR})",
    )
    parser.add_argument(
        "--log-dir", type=str, default=DEFAULT_LOG_DIR,
        help=f"TensorBoard log directory (default: {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--eval-episodes", type=int, default=20,
        help="Evaluation episodes (default: 20)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress SB3 training output",
    )

    args = parser.parse_args()

    # 确定要训练的 Agent 列表
    if args.agent == "all":
        agent_list = _AGENT_IDS
    elif args.agent in _AGENT_IDS:
        agent_list = [args.agent]
    else:
        print(f"Error: Unknown agent '{args.agent}'. "
              f"Choose from: {', '.join(_AGENT_IDS)}, all")
        sys.exit(1)

    # 训练
    results = {}
    for agent_id in agent_list:
        result = train_agent(
            agent_id=agent_id,
            total_timesteps=args.timesteps,
            learning_rate=args.lr,
            n_steps=args.n_steps,
            ent_coef=args.ent_coef,
            seed=args.seed,
            model_dir=args.model_dir,
            log_dir=args.log_dir,
            eval_episodes=args.eval_episodes,
            verbose=0 if args.quiet else 1,
        )
        results[agent_id] = result

    # 汇总
    if len(agent_list) > 1:
        print(f"\n{'=' * 70}")
        print("Summary")
        print(f"{'=' * 70}")
        print(f"{'Agent':<15} {'Random ROI':>12} {'Trained ROI':>12} {'Improvement':>12}")
        print(f"{'-' * 15} {'-' * 12} {'-' * 12} {'-' * 12}")
        for agent_id in agent_list:
            r = results[agent_id]
            print(f"{agent_id:<15} {r['pre_random_roi_mean']:>8.2f}% ±{r['pre_random_roi_std']:.2f}"
                  f"  {r['post_trained_roi_mean']:>8.2f}% ±{r['post_trained_roi_std']:.2f}"
                  f"  {r['improvement']:>+10.2f}%")

    # 保存结果 JSON
    results_path = os.path.join(
        args.log_dir,
        f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    os.makedirs(args.log_dir, exist_ok=True)
    # 转换 numpy 类型以便 JSON 序列化
    serializable = {}
    for aid, r in results.items():
        serializable[aid] = {
            k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
            for k, v in r.items()
        }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {results_path}")


if __name__ == "__main__":
    main()
