"""
Multi-Agent MAPPO Training Script
==================================
MAPPO (Multi-Agent PPO) with Centralized Critic, Parameter Sharing,
and comprehensive TensorBoard diagnostics.

Architecture (CTDE — Centralized Training Decentralized Execution):
  Training:   Centralized Critic V([obs₁|obs₂|obs₃|obs₄]) → accurate global value
              Shared Encoder + agent-ID embedding → Per-agent Actor Heads
  Execution:  Each agent: local obs → encoder → actor head → action

Key features:
  - Rollout Buffer: collect n_steps before gradient update (standard PPO)
  - Centralized Critic: sees global state → eliminates partial-observability noise
  - Parameter Sharing: shared encoder across agents with agent-ID embeddings
  - Normalization: running mean/std for observations and rewards
  - TensorBoard: loss, clip_frac, approx_kl, explained_var, per-agent entropy

Quickstart:
  # Standard training (200k steps)
  python marl/training/train_multi_agent.py

  # Quick smoke test (~30s)
  python marl/training/train_multi_agent.py --timesteps 2000 --eval-episodes 5 --n-rounds 4

  # Longer episodes, tuned for convergence
  python marl/training/train_multi_agent.py --n-rounds 16 --lr 1e-4 --n-steps 2048

  # Ablation: disable parameter sharing
  python marl/training/train_multi_agent.py --no-share

  # View training curves
  tensorboard --logdir marl/training/training_results/mappo_*/logs

TensorBoard metrics:
  train/       — roi_avg100, best_roi, loss_policy, loss_value, loss_entropy, loss_total
  diag/        — clip_fraction, approx_kl, grad_norm, explained_variance
  entropy/     — per-agent entropy (purchasing, sales, operations, supplychain)
  eval/        — random_roi_mean, trained_roi_mean, improvement

Diagnostic guide:
  clip_fraction > 0.1  → increase n_steps or reduce lr (too much policy change)
  approx_kl > 0.01     → reduce clip_range or lr (policy unstable)
  explained_var < 0    → critic is worse than mean prediction (needs tuning)
  entropy → 0          → policy collapsed (increase ent_coef)
  grad_norm saturates  → gradients are being clipped heavily (check max_grad_norm)
"""

import argparse
import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam

# ── Path config ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from marl.env.marl_env import TFCEnv
from marl.training.single_agent_wrapper import _AGENT_IDS, _AGENT_INFO

_AGENT_ORDER = _AGENT_IDS  # ["purchasing", "sales", "operations", "supplychain"]
_TRAINING_DIR = os.path.dirname(os.path.abspath(__file__))
_TRAINING_RESULT_DIR = os.path.join(_TRAINING_DIR, "training_results")


# ═══════════════════════════════════════════════════════════════════════════════
# Running Normalizer (Welford-style EMA)
# ═══════════════════════════════════════════════════════════════════════════════

class RunningNormalizer:
    """Running mean/std normalization with exponential moving average.

    Uses a momentum-based update that gracefully handles both single
    observations (ndim=1) and batches (ndim=2).
    """

    def __init__(self, shape: tuple, eps: float = 1e-5, momentum: float = 0.01):
        self.mean = np.zeros(shape, dtype=np.float32)
        self.var = np.ones(shape, dtype=np.float32)
        self.std = np.ones(shape, dtype=np.float32)
        self.eps = eps
        self.momentum = momentum
        self._first_update = True

    def update(self, x: np.ndarray):
        """Update running statistics. Accepts 1-D or 2-D arrays."""
        if x.ndim == 1:
            x = x.reshape(1, -1)
        batch_mean = x.mean(axis=0)
        batch_var = x.var(axis=0)

        if self._first_update:
            self.mean = batch_mean.astype(np.float32)
            self.var = batch_var.astype(np.float32)
            self._first_update = False
        else:
            self.mean = (1 - self.momentum) * self.mean + self.momentum * batch_mean.astype(np.float32)
            self.var = (1 - self.momentum) * self.var + self.momentum * batch_var.astype(np.float32)

        self.std = np.sqrt(self.var + self.eps)

    def normalize(self, x: np.ndarray) -> np.ndarray:
        """Normalize input. Preserves input dimensionality."""
        squeeze = x.ndim == 1
        if squeeze:
            x = x.reshape(1, -1)
        normalized = (x - self.mean) / (self.std + self.eps)
        return normalized.squeeze(0) if squeeze else normalized


# ═══════════════════════════════════════════════════════════════════════════════
# MultiDiscrete Actor Head — per-agent action output layer
# ═══════════════════════════════════════════════════════════════════════════════

class MultiDiscreteActorHead(nn.Module):
    """Actor head for gym.spaces.MultiDiscrete.

    Each action dimension gets its own categorical distribution.
    Supports sampling, log-prob evaluation, entropy, and deterministic mode.
    """

    def __init__(self, input_dim: int, nvec: List[int]):
        """
        Args:
            input_dim: Dimension of input feature vector.
            nvec: List of category counts, one per action dimension.
        """
        super().__init__()
        self.nvec = nvec
        self.n_dims = len(nvec)
        self.heads = nn.ModuleList([
            nn.Linear(input_dim, n) for n in nvec
        ])

    def forward(self, features: torch.Tensor) -> List[torch.Tensor]:
        return [head(features) for head in self.heads]

    def _dists(self, logits_list: List[torch.Tensor]) -> List[torch.distributions.Categorical]:
        return [torch.distributions.Categorical(logits=logits) for logits in logits_list]

    def sample(self, logits_list: List[torch.Tensor]) -> Tuple[torch.Tensor, torch.Tensor]:
        """Sample actions and return (actions, log_probs)."""
        dists = self._dists(logits_list)
        actions = torch.stack([d.sample() for d in dists], dim=-1)
        log_probs = torch.stack(
            [d.log_prob(actions[:, i]) for i, d in enumerate(dists)], dim=-1
        )
        return actions, log_probs.sum(dim=-1)

    def evaluate(
        self, logits_list: List[torch.Tensor], actions: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Evaluate log_probs and per-dimension entropy for given actions.

        Returns:
            log_probs: (batch,) summed across action dims
            entropy:   (batch,) mean across action dims
        """
        dists = self._dists(logits_list)
        log_probs = torch.stack(
            [d.log_prob(actions[:, i]) for i, d in enumerate(dists)], dim=-1
        )
        entropy = torch.stack([d.entropy() for d in dists], dim=-1)
        return log_probs.sum(dim=-1), entropy.mean(dim=-1)

    def deterministic(self, logits_list: List[torch.Tensor]) -> torch.Tensor:
        """Return argmax action (deterministic policy)."""
        return torch.stack([logits.argmax(dim=-1) for logits in logits_list], dim=-1)


# ═══════════════════════════════════════════════════════════════════════════════
# MAPPO Network — Shared Encoder + Per-agent Actor Heads + Centralized Critic
# ═══════════════════════════════════════════════════════════════════════════════

class MAPPONetwork(nn.Module):
    """MAPPO network with optional parameter sharing and centralized critic.

    ┌─ Actor side (decentralized execution) ─────────────────────┐
    │  obsᵢ → pad+embed(agent_id) → SharedEncoder → ActorHeadᵢ → aᵢ  │
    └────────────────────────────────────────────────────────────┘
    ┌─ Critic side (centralized training) ───────────────────────┐
    │  [obs₁|obs₂|obs₃|obs₄] → CriticNet → V(global_state)        │
    └────────────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        agent_obs_dims: Dict[str, int],
        agent_nvecs: Dict[str, List[int]],
        hidden_dim: int = 256,
        share_encoder: bool = True,
    ):
        super().__init__()
        self.agent_ids = list(agent_obs_dims.keys())
        self.share_encoder = share_encoder
        self.agent_obs_dims = agent_obs_dims

        self.max_obs_dim = max(agent_obs_dims.values())
        self.global_obs_dim = sum(agent_obs_dims.values())

        # ── Agent ID embedding ──
        self.agent_id_to_idx = {aid: i for i, aid in enumerate(self.agent_ids)}
        self.agent_embedding = nn.Embedding(len(self.agent_ids), 16)

        # ── Encoder(s) ──
        encoder_input_dim = self.max_obs_dim + 16  # padded obs + id embedding
        if share_encoder:
            self.encoder = nn.Sequential(
                nn.Linear(encoder_input_dim, hidden_dim),
                nn.Tanh(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.Tanh(),
            )
            self.encoders = None
        else:
            self.encoders = nn.ModuleDict({
                aid: nn.Sequential(
                    nn.Linear(dim + 16, hidden_dim),
                    nn.Tanh(),
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.Tanh(),
                )
                for aid, dim in agent_obs_dims.items()
            })
            self.encoder = None

        # ── Per-agent actor heads ──
        self.actor_heads = nn.ModuleDict({
            aid: MultiDiscreteActorHead(hidden_dim, agent_nvecs[aid])
            for aid in self.agent_ids
        })

        # ── Centralized critic ──
        self.critic = nn.Sequential(
            nn.Linear(self.global_obs_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )

        self._init_weights()

    def _init_weights(self):
        """Orthogonal init for linear layers (standard for PPO)."""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2))
                nn.init.zeros_(m.bias)

    # ── Forward helpers ──

    def _pad_obs(self, obs: torch.Tensor, agent_id: str) -> torch.Tensor:
        """Pad observation to max_obs_dim and append agent-ID embedding."""
        batch_size = obs.shape[0]
        obs_dim = self.agent_obs_dims[agent_id]

        padded = torch.zeros(batch_size, self.max_obs_dim, device=obs.device)
        padded[:, :obs_dim] = obs

        idx = self.agent_id_to_idx[agent_id]
        idx_tensor = torch.full((batch_size,), idx, dtype=torch.long, device=obs.device)
        agent_emb = self.agent_embedding(idx_tensor)

        return torch.cat([padded, agent_emb], dim=-1)

    def get_features(self, obs: torch.Tensor, agent_id: str) -> torch.Tensor:
        """Encode a local observation into shared feature space."""
        x = self._pad_obs(obs, agent_id)
        if self.share_encoder:
            return self.encoder(x)
        else:
            return self.encoders[agent_id](x)

    # ── Public API ──

    @torch.no_grad()
    def get_action(
        self, obs: np.ndarray, agent_id: str, deterministic: bool = False,
    ) -> Tuple[np.ndarray, float]:
        """Get action and log_prob for a single agent.

        Args:
            obs: (obs_dim,) numpy array
            agent_id: agent identifier
            deterministic: if True, use argmax instead of sampling

        Returns:
            action: (n_dims,) int64 numpy array
            log_prob: float
        """
        obs_t = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
        features = self.get_features(obs_t, agent_id)
        logits = self.actor_heads[agent_id](features)

        if deterministic:
            action = self.actor_heads[agent_id].deterministic(logits)
            log_prob = 0.0
        else:
            action, log_prob = self.actor_heads[agent_id].sample(logits)
            log_prob = log_prob.item()

        return action.squeeze(0).cpu().numpy(), log_prob

    @torch.no_grad()
    def get_value(self, global_obs: np.ndarray) -> float:
        """Compute centralized value V(global_state)."""
        g_t = torch.as_tensor(global_obs, dtype=torch.float32).unsqueeze(0)
        return self.critic(g_t).squeeze().item()

    def evaluate_actions(
        self,
        obs_dict: Dict[str, np.ndarray],
        actions_dict: Dict[str, np.ndarray],
        global_obs: np.ndarray,
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str, torch.Tensor], torch.Tensor]:
        """Evaluate all agents' actions (used during PPO update).

        Args:
            obs_dict: {aid: (batch, obs_dim)} — already normalized
            actions_dict: {aid: (batch, n_dims)}
            global_obs: (batch, global_obs_dim)

        Returns:
            log_probs: {aid: (batch,)}
            entropies: {aid: (batch,)}
            values: (batch,)
        """
        log_probs = {}
        entropies = {}

        for aid in self.agent_ids:
            obs_t = torch.as_tensor(obs_dict[aid], dtype=torch.float32)
            features = self.get_features(obs_t, aid)
            logits = self.actor_heads[aid](features)

            act_t = torch.as_tensor(actions_dict[aid], dtype=torch.int64)
            lp, ent = self.actor_heads[aid].evaluate(logits, act_t)
            log_probs[aid] = lp
            entropies[aid] = ent

        g_t = torch.as_tensor(global_obs, dtype=torch.float32)
        values = self.critic(g_t).squeeze(-1)

        return log_probs, entropies, values


# ═══════════════════════════════════════════════════════════════════════════════
# Rollout Buffer — fixed-size storage for on-policy data
# ═══════════════════════════════════════════════════════════════════════════════

class RolloutBuffer:
    """Collects n_steps of multi-agent experience before PPO update.

    Data layout (per timestep t):
      obs[t]:        {aid: (obs_dim[aid],)}
      actions[t]:    {aid: (n_act_dims[aid],)}
      log_probs[t]:  {aid: float}
      old_values[t]: float           # centralized critic value
      global_obs[t]: (global_dim,)   # concatenated obs
      rewards[t]:    float
      dones[t]:      bool

    After collection, compute_gae() fills advantages[t] and returns[t].
    """

    def __init__(
        self,
        n_steps: int,
        agent_obs_dims: Dict[str, int],
        agent_nvecs: Dict[str, List[int]],
        global_obs_dim: int,
    ):
        self.n_steps = n_steps
        self.agent_ids = list(agent_obs_dims.keys())
        self.agent_obs_dims = agent_obs_dims
        self.agent_nvecs = agent_nvecs
        self.global_obs_dim = global_obs_dim
        self._allocate()

    def _allocate(self):
        n = self.n_steps
        aids = self.agent_ids

        self.obs = {aid: np.zeros((n, self.agent_obs_dims[aid]), dtype=np.float32) for aid in aids}
        self.actions = {aid: np.zeros((n, len(self.agent_nvecs[aid])), dtype=np.int64) for aid in aids}
        self.log_probs = {aid: np.zeros(n, dtype=np.float32) for aid in aids}
        self.global_obs = np.zeros((n, self.global_obs_dim), dtype=np.float32)
        self.old_values = np.zeros(n, dtype=np.float32)
        self.rewards = np.zeros(n, dtype=np.float32)
        self.dones = np.zeros(n, dtype=np.float32)

        # Filled by compute_gae()
        self.advantages = np.zeros(n, dtype=np.float32)
        self.returns = np.zeros(n, dtype=np.float32)

        self._ptr = 0

    def add(
        self,
        obs_dict: Dict[str, np.ndarray],
        actions_dict: Dict[str, np.ndarray],
        log_probs_dict: Dict[str, float],
        global_obs: np.ndarray,
        value: float,
        reward: float,
        done: bool,
    ):
        """Append one timestep. No-op if buffer is full."""
        if self._ptr >= self.n_steps:
            return

        idx = self._ptr
        for aid in self.agent_ids:
            self.obs[aid][idx] = obs_dict[aid]
            self.actions[aid][idx] = actions_dict[aid]
            self.log_probs[aid][idx] = log_probs_dict[aid]

        self.global_obs[idx] = global_obs
        self.old_values[idx] = value
        self.rewards[idx] = reward
        self.dones[idx] = float(done)
        self._ptr += 1

    def compute_gae(self, last_value: float, gamma: float, gae_lambda: float):
        """Compute GAE advantages and returns in-place.

        Args:
            last_value: V(s_{T+1}) — value of state after last collected step.
                        0 if episode terminated.
        """
        n = self._ptr
        last_gae = 0.0

        for t in reversed(range(n)):
            if t == n - 1:
                next_val = last_value
            else:
                next_val = 0.0 if self.dones[t] else self.old_values[t + 1]

            delta = self.rewards[t] + gamma * next_val - self.old_values[t]
            mask = 1.0 - self.dones[t]
            last_gae = delta + gamma * gae_lambda * mask * last_gae
            self.advantages[t] = last_gae
            self.returns[t] = last_gae + self.old_values[t]

    def iterate_batches(self, batch_size: int, n_epochs: int):
        """Generator yielding (batch_dict, adv_normalized) for each minibatch.

        Advantages are normalized once per epoch (standard PPO practice).
        """
        n = self._ptr
        indices = np.arange(n)

        for _ in range(n_epochs):
            # Normalize advantages per epoch
            adv = self.advantages[:n].copy()
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)

            np.random.shuffle(indices)
            for start in range(0, n, batch_size):
                batch_idx = indices[start:start + batch_size]
                yield self._make_batch(batch_idx, adv[batch_idx])

    def _make_batch(self, indices: np.ndarray, advantages: np.ndarray) -> dict:
        return {
            "obs": {aid: self.obs[aid][indices] for aid in self.agent_ids},
            "actions": {aid: self.actions[aid][indices] for aid in self.agent_ids},
            "old_log_probs": {aid: self.log_probs[aid][indices] for aid in self.agent_ids},
            "old_values": self.old_values[indices],
            "global_obs": self.global_obs[indices],
            "advantages": advantages,
            "returns": self.returns[indices],
        }

    @property
    def is_full(self) -> bool:
        return self._ptr >= self.n_steps

    @property
    def size(self) -> int:
        return self._ptr


# ═══════════════════════════════════════════════════════════════════════════════
# MAPPO Trainer
# ═══════════════════════════════════════════════════════════════════════════════

class MAPPTrainer:
    """MAPPO trainer with centralized critic, parameter sharing, and normalization.

    Training loop:
      1. Collect n_steps of joint experience (across episode boundaries)
      2. Compute GAE advantages using centralized critic
      3. Update shared encoder + per-agent actor heads + centralized critic
         via mini-batch PPO (all agents updated simultaneously)
      4. Repeat
    """

    def __init__(
        self,
        n_rounds: int = 8,
        use_noise: bool = True,
        learning_rate: float = 3e-4,
        n_steps: int = 1024,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: float = 0.2,
        ent_coef: float = 0.01,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        normalize_obs: bool = True,
        normalize_reward: bool = True,
        share_encoder: bool = True,
        seed: int = 42,
        model_dir: str = "",
        log_dir: str = "",
    ):
        # ── Store config ──
        self.n_rounds = n_rounds
        self.use_noise = use_noise
        self.lr = learning_rate
        self.n_steps = n_steps
        self.batch_size = batch_size
        self.n_epochs = n_epochs
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_range = clip_range
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.max_grad_norm = max_grad_norm
        self.normalize_obs = normalize_obs
        self.normalize_reward = normalize_reward
        self.share_encoder = share_encoder
        self.seed = seed
        self.model_dir = model_dir
        self.log_dir = log_dir

        torch.manual_seed(seed)
        np.random.seed(seed)

        # ── Environment ──
        self.env = TFCEnv(
            mode="multi",
            n_rounds=n_rounds,
            use_noise=use_noise,
            reward_scale=1.0,
        )

        # ── Action / observation metadata ──
        self.agent_obs_dims = {}
        self.agent_nvecs = {}
        for aid in _AGENT_ORDER:
            self.agent_obs_dims[aid] = self.env.observation_spaces[aid].shape[0]
            self.agent_nvecs[aid] = list(self.env.action_spaces[aid].nvec)

        self.global_obs_dim = sum(self.agent_obs_dims.values())

        # ── Network ──
        self.network = MAPPONetwork(
            agent_obs_dims=self.agent_obs_dims,
            agent_nvecs=self.agent_nvecs,
            hidden_dim=256,
            share_encoder=share_encoder,
        )
        self.optimizer = Adam(self.network.parameters(), lr=learning_rate, eps=1e-5)

        # ── Normalizers ──
        self.obs_normalizers: Dict[str, RunningNormalizer] = {}
        if normalize_obs:
            for aid in _AGENT_ORDER:
                self.obs_normalizers[aid] = RunningNormalizer(
                    shape=(self.agent_obs_dims[aid],), momentum=0.01,
                )
        self.reward_normalizer = RunningNormalizer(shape=(1,), momentum=0.01) if normalize_reward else None

        # ── Buffer ──
        self.buffer = RolloutBuffer(
            n_steps=n_steps,
            agent_obs_dims=self.agent_obs_dims,
            agent_nvecs=self.agent_nvecs,
            global_obs_dim=self.global_obs_dim,
        )

        # ── Global step counter (monotonic across all rollouts) ──
        self.global_step = 0
        self.rollout_log_interval = 100  # log every N env steps during collection

        # ── TensorBoard ──
        self.writer = None
        if log_dir:
            from torch.utils.tensorboard import SummaryWriter
            self.writer = SummaryWriter(log_dir=log_dir)

        # ── Print info ──
        n_params = sum(p.numel() for p in self.network.parameters()) / 1e6
        print(f"  Architecture: MAPPO {'+ParamShare' if share_encoder else '(per-agent encoders)'}")
        print(f"  Global obs dim: {self.global_obs_dim}")
        for aid in _AGENT_ORDER:
            print(f"    [{aid:<14}] obs={self.agent_obs_dims[aid]:>3}, "
                  f"act_dims={len(self.agent_nvecs[aid]):>2}  "
                  f"nvec={self.agent_nvecs[aid][:3]}...")
        print(f"  Total params: {n_params:.2f}M")
        print(f"  Normalization: obs={normalize_obs}, reward={normalize_reward}")

    # ═══════════════════════════════════════════════════════════════════
    # Training
    # ═══════════════════════════════════════════════════════════════════

    def train(
        self,
        total_timesteps: int = 200_000,
        save_interval: int = 50_000,
        eval_episodes: int = 20,
        verbose: bool = True,
    ) -> dict:
        """Run full training loop.

        Returns:
            results dict with pre/post ROI, loss history, config, etc.
        """
        print(f"\n{'=' * 70}")
        print("MAPPO Training — Centralized Critic + Parameter Sharing")
        print(f"{'=' * 70}")
        print(f"  Agents:        {', '.join(_AGENT_ORDER)}")
        print(f"  Timesteps:     {total_timesteps:,}")
        print(f"  n_rounds:      {self.n_rounds}  (episode = {self.n_rounds}×26 weeks)")
        print(f"  n_steps/update:{self.n_steps}")
        print(f"  LR:            {self.lr}")
        print(f"  Entropy coef:  {self.ent_coef}")
        print(f"  Seed:          {self.seed}")
        print(f"{'=' * 70}\n")

        # ── Pre-training baseline ──
        if verbose:
            print("Evaluating random baseline...")
        pre_roi = self._evaluate(n_episodes=eval_episodes, use_trained=False)
        if verbose:
            print(f"  Random baseline: ROI = {pre_roi['mean']:.2f}% ± {pre_roi['std']:.2f}%\n")

        # ── Main loop ──
        start_time = time.time()
        total_steps = 0
        n_updates = 0
        roi_history = deque(maxlen=100)
        best_roi = -float("inf")

        try:
            from tqdm import tqdm as tqdm_cls
            pbar = tqdm_cls(total=total_timesteps, desc="Training", unit="steps",
                            disable=not verbose)
        except ImportError:
            pbar = None
            if verbose:
                print("(tqdm not installed — using bare progress)")

        # Store pbar so _collect_rollout() can update it at 100-step intervals
        self._pbar = pbar

        while total_steps < total_timesteps:
            # Phase 1: Collect rollout
            #   - pbar updated every 100 steps inside _collect_rollout()
            #   - rollout/* TensorBoard metrics written every 100 steps
            ep_rois, n_collected = self._collect_rollout()
            self.global_step += n_collected
            total_steps += n_collected
            n_updates += 1

            for r in ep_rois:
                roi_history.append(r)
            if ep_rois:
                best_roi = max(best_roi, max(ep_rois))

            # Phase 2: PPO update
            loss_info = self._update()

            # ── Progress bar: refresh postfix with latest diagnostics ──
            avg_roi = np.mean(roi_history) if roi_history else 0.0

            if pbar is not None:
                # pbar already advanced +1 per step during collection;
                # here just refresh the postfix with full diagnostics
                pbar.set_postfix({
                    "ROI": f"{avg_roi:+.1f}%",
                    "Best": f"{best_roi:+.1f}%",
                    "U": n_updates,
                    "loss": f"{loss_info.get('total', 0):.3f}",
                    "kl": f"{loss_info.get('approx_kl', 0):.4f}",
                    "ev": f"{loss_info.get('explained_var', 0):.2f}",
                })
            elif verbose and n_updates % 10 == 0:
                print(f"  Step {total_steps:,} | ROI={avg_roi:+.1f}% | "
                      f"Best={best_roi:+.1f}% | loss={loss_info.get('total', 0):.3f} | "
                      f"Updates={n_updates}")

            # ── TensorBoard: per-update diagnostics (every n_steps) ──
            if self.writer:
                step = self.global_step
                # Core training curves
                self.writer.add_scalar("train/roi_avg100", avg_roi, step)
                self.writer.add_scalar("train/best_roi", best_roi, step)

                if loss_info:
                    # Loss components
                    self.writer.add_scalar("train/loss_policy", loss_info["policy"], step)
                    self.writer.add_scalar("train/loss_value", loss_info["value"], step)
                    self.writer.add_scalar("train/loss_entropy", loss_info["entropy"], step)
                    self.writer.add_scalar("train/loss_total", loss_info["total"], step)

                    # PPO diagnostics — critical for debugging convergence
                    self.writer.add_scalar("diag/clip_fraction", loss_info["clip_frac"], step)
                    self.writer.add_scalar("diag/approx_kl", loss_info["approx_kl"], step)
                    self.writer.add_scalar("diag/grad_norm", loss_info["grad_norm"], step)
                    self.writer.add_scalar("diag/explained_variance", loss_info["explained_var"], step)

                    # Per-agent entropy (detect policy collapse per agent)
                    for aid in _AGENT_ORDER:
                        key = f"ent_{aid}"
                        if key in loss_info:
                            self.writer.add_scalar(f"entropy/{aid}", loss_info[key], step)

            # ── Checkpoint ──
            if total_steps % save_interval == 0 and total_steps > 0:
                self._save("checkpoint", total_steps)

        if pbar is not None:
            pbar.close()

        train_time = time.time() - start_time

        # ── Post-training evaluation ──
        if verbose:
            print(f"\nTraining complete ({train_time:.0f}s). Evaluating...")
        post_roi = self._evaluate(n_episodes=eval_episodes, use_trained=True)
        improvement = post_roi["mean"] - pre_roi["mean"]
        if verbose:
            print(f"  Trained:   ROI = {post_roi['mean']:.2f}% ± {post_roi['std']:.2f}%")
            print(f"  vs random: {improvement:+.2f}%")

        # ── Final save ──
        self._save("final", total_steps)

        # ── TensorBoard final ──
        if self.writer:
            self.writer.add_scalar("eval/random_roi_mean", pre_roi["mean"], total_steps)
            self.writer.add_scalar("eval/trained_roi_mean", post_roi["mean"], total_steps)
            self.writer.add_scalar("eval/improvement", improvement, total_steps)
            self.writer.add_hparams(
                {
                    "lr": self.lr, "n_steps": self.n_steps,
                    "ent_coef": self.ent_coef, "gamma": self.gamma,
                    "n_rounds": self.n_rounds, "share_enc": self.share_encoder,
                },
                {"final_roi": post_roi["mean"], "improvement": improvement},
            )
            self.writer.close()

        return {
            "algorithm": "MAPPO",
            "train_config": {
                "agents": _AGENT_ORDER,
                "n_rounds": self.n_rounds,
                "total_timesteps": total_timesteps,
                "learning_rate": self.lr,
                "n_steps": self.n_steps,
                "n_epochs": self.n_epochs,
                "batch_size": self.batch_size,
                "gamma": self.gamma,
                "gae_lambda": self.gae_lambda,
                "clip_range": self.clip_range,
                "ent_coef": self.ent_coef,
                "vf_coef": self.vf_coef,
                "share_encoder": self.share_encoder,
                "normalize_obs": self.normalize_obs,
                "normalize_reward": self.normalize_reward,
                "seed": self.seed,
            },
            "pre_random_roi": pre_roi,
            "post_trained_roi": post_roi,
            "improvement": improvement,
            "best_roi": best_roi,
            "n_updates": n_updates,
            "train_time_seconds": train_time,
            "roi_history": list(roi_history),
        }

    # ═══════════════════════════════════════════════════════════════════
    # Rollout collection
    # ═══════════════════════════════════════════════════════════════════

    def _collect_rollout(self) -> Tuple[List[float], int, List[dict]]:
        """Run joint policy for n_steps, storing experience in self.buffer.

        Also logs dense rollout metrics to TensorBoard every
        self.rollout_log_interval steps (default 100).

        Returns:
            episode_rois: list of ROI for each completed episode
            n_collected:  number of steps collected
            rollout_logs: list of {step, reward_mean, value_mean, roi} snapshots
        """
        self.buffer._allocate()  # reset
        episode_rois = []
        n_collected = 0

        obs_dict, _ = self.env.reset()
        episode_roi = 0.0
        done = False

        # Running windows + trigger for TensorBoard logging
        from collections import deque as _deque
        reward_window = _deque(maxlen=self.rollout_log_interval)
        value_window = _deque(maxlen=self.rollout_log_interval)
        next_tb_log_at = self.global_step + self.rollout_log_interval

        while not self.buffer.is_full:
            # Normalize observations
            norm_obs = {}
            for aid in _AGENT_ORDER:
                raw = obs_dict[aid].copy()
                if self.normalize_obs and aid in self.obs_normalizers:
                    self.obs_normalizers[aid].update(raw)
                    raw = self.obs_normalizers[aid].normalize(raw)
                norm_obs[aid] = raw

            # Build global observation for centralized critic
            global_obs = np.concatenate([obs_dict[aid] for aid in _AGENT_ORDER])

            # Get actions and centralized value
            actions = {}
            log_probs = {}
            for aid in _AGENT_ORDER:
                act, lp = self.network.get_action(norm_obs[aid], aid, deterministic=False)
                actions[aid] = act
                log_probs[aid] = lp
            value = self.network.get_value(global_obs)

            # Step environment
            next_obs_dict, rewards, terminated, truncated, info = self.env.step(actions)
            done = terminated or truncated
            raw_reward = rewards[_AGENT_ORDER[0]]
            episode_roi += raw_reward

            # Track for dense logging
            reward_window.append(raw_reward)
            value_window.append(value)

            # Normalize reward
            if self.normalize_reward:
                self.reward_normalizer.update(np.array([raw_reward]))
                norm_reward = self.reward_normalizer.normalize(np.array([raw_reward])).item()
            else:
                norm_reward = raw_reward

            # Store
            self.buffer.add(
                obs_dict=norm_obs,
                actions_dict=actions,
                log_probs_dict=log_probs,
                global_obs=global_obs,
                value=value,
                reward=norm_reward,
                done=done,
            )
            n_collected += 1

            # ── Progress bar: update every step ──
            step = self.global_step + n_collected
            if self._pbar is not None:
                self._pbar.update(1)
                # Refresh postfix every 10 steps to keep overhead minimal
                if step % 10 == 0 and len(reward_window) > 1:
                    self._pbar.set_postfix({
                        "ROI": f"{episode_roi:+.1f}%",
                        "rew": f"{np.mean(reward_window):+.2f}",
                    })

            # ── TensorBoard: log rollout metrics every N env steps ──
            if step >= next_tb_log_at and len(reward_window) > 1:
                if self.writer:
                    self.writer.add_scalar("rollout/reward_mean",
                        np.mean(reward_window), step)
                    self.writer.add_scalar("rollout/value_mean",
                        np.mean(value_window), step)
                    self.writer.add_scalar("rollout/reward_std",
                        np.std(reward_window), step)
                    self.writer.add_scalar("rollout/value_reward_gap",
                        np.mean(value_window) - np.mean(reward_window), step)
                next_tb_log_at += self.rollout_log_interval

            if done:
                episode_rois.append(episode_roi)
                episode_roi = 0.0
                obs_dict, _ = self.env.reset()
            else:
                obs_dict = next_obs_dict

        # Compute GAE advantages
        if not done:
            # Bootstrap from last observation
            last_global = np.concatenate([obs_dict[aid] for aid in _AGENT_ORDER])
            last_value = self.network.get_value(last_global)
        else:
            last_value = 0.0

        self.buffer.compute_gae(last_value, self.gamma, self.gae_lambda)
        return episode_rois, n_collected

    # ═══════════════════════════════════════════════════════════════════
    # PPO update
    # ═══════════════════════════════════════════════════════════════════

    def _update(self) -> Dict[str, float]:
        """Perform PPO update using the filled rollout buffer.

        All agents + centralized critic are updated together in each
        mini-batch, ensuring consistent gradient flow through the
        shared encoder.

        Returns diagnostics:
          policy, value, entropy, total — loss components
          clip_frac               — fraction of ratios hitting PPO clip boundary
          approx_kl               — estimated KL divergence (old→new policy)
          grad_norm               — global gradient norm before clipping
          explained_var           — value function explained variance
          ent_{agent_id}          — per-agent entropy (for collapse detection)
        """
        accum = {
            "policy": 0.0, "value": 0.0, "entropy": 0.0, "total": 0.0,
            "clip_frac": 0.0, "approx_kl": 0.0, "grad_norm": 0.0,
        }
        per_agent_ent = {aid: 0.0 for aid in _AGENT_ORDER}
        n_batches = 0

        for batch in self.buffer.iterate_batches(self.batch_size, self.n_epochs):
            # ── Evaluate current policy on old data ──
            log_probs, entropies, new_values = self.network.evaluate_actions(
                batch["obs"], batch["actions"], batch["global_obs"],
            )

            advantages = torch.as_tensor(batch["advantages"], dtype=torch.float32)
            returns = torch.as_tensor(batch["returns"], dtype=torch.float32)
            old_values = torch.as_tensor(batch["old_values"], dtype=torch.float32)

            # ── Policy loss (per-agent, averaged) ──
            policy_loss = 0.0
            entropy_sum = 0.0
            batch_clip_frac = 0.0
            batch_approx_kl = 0.0

            for aid in _AGENT_ORDER:
                old_lp = torch.as_tensor(batch["old_log_probs"][aid], dtype=torch.float32)
                ratio = torch.exp(log_probs[aid] - old_lp)

                surr1 = ratio * advantages
                surr2 = torch.clamp(ratio, 1 - self.clip_range, 1 + self.clip_range) * advantages
                policy_loss += -torch.min(surr1, surr2).mean()
                entropy_sum += entropies[aid].mean()

                # Per-agent diagnostics
                per_agent_ent[aid] += entropies[aid].mean().item()

                # Clip fraction: ratio of samples outside [1-ε, 1+ε]
                clip_mask = ((ratio < 1 - self.clip_range) | (ratio > 1 + self.clip_range)).float()
                batch_clip_frac += clip_mask.mean().item()

                # Approximate KL: 0.5 * (log π_new - log π_old)² averaged
                log_diff = log_probs[aid] - old_lp
                batch_approx_kl += 0.5 * (log_diff ** 2).mean().item()

            policy_loss = policy_loss / len(_AGENT_ORDER)
            entropy = entropy_sum / len(_AGENT_ORDER)
            clip_frac = batch_clip_frac / len(_AGENT_ORDER)
            approx_kl = batch_approx_kl / len(_AGENT_ORDER)

            # ── Value loss (centralized critic, with clipping) ──
            value_pred_clipped = old_values + torch.clamp(
                new_values - old_values, -self.clip_range, self.clip_range,
            )
            value_loss_1 = (new_values - returns) ** 2
            value_loss_2 = (value_pred_clipped - returns) ** 2
            value_loss = 0.5 * torch.max(value_loss_1, value_loss_2).mean()

            # ── Total loss ──
            loss = policy_loss + self.vf_coef * value_loss - self.ent_coef * entropy

            # ── Gradient step ──
            self.optimizer.zero_grad()
            loss.backward()

            # Record gradient norm before clipping
            total_norm = 0.0
            for p in self.network.parameters():
                if p.grad is not None:
                    param_norm = p.grad.data.norm(2).item()
                    total_norm += param_norm ** 2
            total_norm = total_norm ** 0.5

            nn.utils.clip_grad_norm_(self.network.parameters(), self.max_grad_norm)
            self.optimizer.step()

            # ── Accumulate ──
            accum["policy"] += policy_loss.item()
            accum["value"] += value_loss.item()
            accum["entropy"] += entropy.item()
            accum["total"] += loss.item()
            accum["clip_frac"] += clip_frac
            accum["approx_kl"] += approx_kl
            accum["grad_norm"] += total_norm
            n_batches += 1

        if n_batches == 0:
            return {}

        # Average over batches
        result = {k: v / n_batches for k, v in accum.items()}
        # Add per-agent entropy
        for aid in _AGENT_ORDER:
            result[f"ent_{aid}"] = per_agent_ent[aid] / n_batches
        # Add explained variance (post-update, over full buffer)
        result["explained_var"] = self._compute_explained_variance()

        return result

    @torch.no_grad()
    def _compute_explained_variance(self) -> float:
        """Compute explained variance of the centralized critic.

        explained_variance = 1 - Var(returns - values) / Var(returns)

        Returns:
            Scalar in (-∞, 1].  1.0 = perfect fit, 0.0 = mean prediction,
            negative = worse than predicting the mean.
        """
        n = self.buffer.size
        if n < 2:
            return 0.0

        global_t = torch.as_tensor(self.buffer.global_obs[:n], dtype=torch.float32)
        new_values = self.network.critic(global_t).squeeze(-1).numpy()
        returns = self.buffer.returns[:n]

        var_returns = np.var(returns)
        if var_returns < 1e-8:
            return 1.0  # constant returns → perfect fit

        var_residual = np.var(returns - new_values)
        return float(1.0 - var_residual / var_returns)

    # ═══════════════════════════════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════════════════════════════

    @torch.no_grad()
    def _evaluate(self, n_episodes: int = 20, use_trained: bool = True) -> dict:
        """Evaluate current policies over n_episodes.

        Args:
            n_episodes: Number of evaluation episodes.
            use_trained: If True, use trained policy; if False, random actions.

        Returns:
            {"mean", "std", "min", "max", "values"}
        """
        roi_values = []
        for i in range(n_episodes):
            obs_dict, _ = self.env.reset(seed=self.seed + 10000 + i)
            done = False
            while not done:
                actions = {}
                for aid in _AGENT_ORDER:
                    if use_trained:
                        raw = obs_dict[aid].copy()
                        if self.normalize_obs and aid in self.obs_normalizers:
                            raw = self.obs_normalizers[aid].normalize(raw)
                        act, _ = self.network.get_action(raw, aid, deterministic=True)
                    else:
                        act = self.env.action_spaces[aid].sample()
                    actions[aid] = act
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

    # ═══════════════════════════════════════════════════════════════════
    # Save / Load
    # ═══════════════════════════════════════════════════════════════════

    def _save(self, tag: str, step: int):
        save_dir = os.path.join(self.model_dir, tag)
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, "mappo_network.pt")
        torch.save({
            "step": step,
            "network": self.network.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "config": {
                "agent_obs_dims": self.agent_obs_dims,
                "agent_nvecs": self.agent_nvecs,
                "global_obs_dim": self.global_obs_dim,
                "share_encoder": self.share_encoder,
            },
        }, path)
        print(f"  [save] {path}")

    def load(self, tag: str):
        load_dir = os.path.join(self.model_dir, tag)
        path = os.path.join(load_dir, "mappo_network.pt")
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        self.network.load_state_dict(ckpt["network"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        print(f"  [load] {path}  (step={ckpt['step']})")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="MAPPO Training for TFC Supply Chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard training (200k steps, ~8 rounds/episode)
  py marl/training/train_multi_agent.py --timesteps 200000

  # Quick smoke test (~30s, minimal compute)
  py marl/training/train_multi_agent.py --timesteps 2000 --eval-episodes 5 --n-rounds 4

  # High-quality: longer episodes, more rollout steps, lower entropy
  py marl/training/train_multi_agent.py --n-rounds 16 --n-steps 2048 --lr 1e-4 --ent-coef 0.005

  # Ablation: disable parameter sharing (per-agent independent encoders)
  py marl/training/train_multi_agent.py --no-share

  # Ablation: disable all normalization
  py marl/training/train_multi_agent.py --no-norm-obs --no-norm-reward

  # Resume from checkpoint
  # (models are saved to training_results/mappo_<time>/models/)

  # View TensorBoard
  tensorboard --logdir marl/training/training_results/

Diagnostic thresholds (check TensorBoard):
  clip_fraction > 0.10  → reduce lr or increase n-steps
  approx_kl > 0.01      → reduce clip-range or lr
  explained_var < 0     → critic failing; increase vf-coef or n-epochs
  entropy → 0           → policy collapsed; increase ent-coef
        """,
    )
    # ── Core ──
    parser.add_argument("--timesteps", type=int, default=200_000,
                        help="Total training timesteps (default: 200,000)")
    parser.add_argument("--n-rounds", type=int, default=8,
                        help="Rounds per episode, each round = 26 weeks (default: 8)")
    parser.add_argument("--eval-episodes", type=int, default=20,
                        help="Evaluation episodes (default: 20)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")

    # ── PPO hyperparams ──
    parser.add_argument("--lr", type=float, default=3e-4,
                        help="Learning rate (default: 3e-4)")
    parser.add_argument("--n-steps", type=int, default=1024,
                        help="Rollout steps per PPO update (default: 1024)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Mini-batch size (default: 64)")
    parser.add_argument("--n-epochs", type=int, default=10,
                        help="PPO epochs per update (default: 10)")
    parser.add_argument("--gamma", type=float, default=0.99,
                        help="Discount factor (default: 0.99)")
    parser.add_argument("--gae-lambda", type=float, default=0.95,
                        help="GAE lambda (default: 0.95)")
    parser.add_argument("--clip-range", type=float, default=0.2,
                        help="PPO clip range (default: 0.2)")
    parser.add_argument("--ent-coef", type=float, default=0.01,
                        help="Entropy bonus coefficient (default: 0.01)")
    parser.add_argument("--vf-coef", type=float, default=0.5,
                        help="Value loss weight (default: 0.5)")
    parser.add_argument("--max-grad-norm", type=float, default=0.5,
                        help="Max gradient norm for clipping (default: 0.5)")

    # ── Features ──
    parser.add_argument("--no-noise", action="store_true",
                        help="Disable simulation noise (deterministic env)")
    parser.add_argument("--no-norm-obs", action="store_true",
                        help="Disable observation normalization")
    parser.add_argument("--no-norm-reward", action="store_true",
                        help="Disable reward normalization")
    parser.add_argument("--no-share", action="store_true",
                        help="Disable parameter sharing (per-agent independent encoders)")

    # ── Paths ──
    parser.add_argument("--model-dir", type=str, default="",
                        help="Model save directory (default: training_result/mappo_<time>/models)")
    parser.add_argument("--log-dir", type=str, default="",
                        help="TensorBoard log directory")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")

    args = parser.parse_args()

    # ── Paths ──
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.model_dir or os.path.join(_TRAINING_RESULT_DIR, f"mappo_{run_ts}")
    model_dir = os.path.join(run_dir, "models")
    log_dir = args.log_dir or os.path.join(run_dir, "logs")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    print(f"\n{'=' * 70}")
    print("TFC Multi-Agent MAPPO Trainer")
    print(f"{'=' * 70}")
    print(f"Run dir:     {run_dir}")
    print(f"Model dir:   {model_dir}")
    print(f"Log dir:     {log_dir}")

    # ── Create trainer ──
    trainer = MAPPTrainer(
        n_rounds=args.n_rounds,
        use_noise=not args.no_noise,
        learning_rate=args.lr,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        n_epochs=args.n_epochs,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        clip_range=args.clip_range,
        ent_coef=args.ent_coef,
        vf_coef=args.vf_coef,
        max_grad_norm=args.max_grad_norm,
        normalize_obs=not args.no_norm_obs,
        normalize_reward=not args.no_norm_reward,
        share_encoder=not args.no_share,
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
    cfg = results["train_config"]
    print(f"\n{'=' * 70}")
    print("Training Summary")
    print(f"{'=' * 70}")
    print(f"  Algorithm:           {results['algorithm']}")
    print(f"  n_rounds:            {cfg['n_rounds']}")
    print(f"  Param sharing:       {cfg['share_encoder']}")
    print(f"  Random baseline:     {results['pre_random_roi']['mean']:>8.2f}% "
          f"± {results['pre_random_roi']['std']:.2f}%")
    print(f"  Trained policy:      {results['post_trained_roi']['mean']:>8.2f}% "
          f"± {results['post_trained_roi']['std']:.2f}%")
    print(f"  Improvement:         {results['improvement']:>+8.2f}%")
    print(f"  Best episode:        {results['best_roi']:>8.2f}%")
    print(f"  Total updates:       {results['n_updates']:>8}")
    print(f"  Training time:       {results['train_time_seconds']:>8.0f}s")

    # ── Save JSON ──
    results_path = os.path.join(run_dir, "multi_results.json")
    out = {}
    for k, v in results.items():
        if k == "roi_history":
            out[k] = [float(x) if isinstance(x, (np.floating, np.integer)) else x
                       for x in v[-100:]]
        elif isinstance(v, dict):
            out[k] = {kk: (float(vv) if isinstance(vv, (np.floating, np.integer)) else vv)
                       for kk, vv in v.items()}
        elif isinstance(v, (np.floating, np.integer)):
            out[k] = float(v)
        else:
            out[k] = v

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved → {results_path}")

    trainer.env.close()


if __name__ == "__main__":
    main()
