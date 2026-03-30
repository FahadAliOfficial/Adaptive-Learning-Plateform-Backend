#!/usr/bin/env python3
"""
Optuna hyperparameter optimization for RL agents (PPO / DQN / A2C).

Usage:
    # Optimize a single algorithm (50 trials, 300K steps each)
    python optuna_optimize.py --algorithm ppo --trials 50 --timesteps 300000

    # Resume an interrupted study
    python optuna_optimize.py --algorithm ppo --trials 50 --timesteps 300000 --resume

    # Optimize all three algorithms sequentially
    python optuna_optimize.py --algorithm all --trials 50 --timesteps 300000

    # Force CPU (recommended for MLP policies)
    python optuna_optimize.py --algorithm ppo --trials 50 --timesteps 300000 --device cpu

Outputs:
    optuna_results/<algo>_study.db        – SQLite study (resumable in Colab)
    optuna_results/<algo>_best_params.json – Best hyperparameters found
    optuna_results/<algo>/trial_<n>/      – Model checkpoints for each trial
"""

import os
import sys
import json
import argparse
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler

import torch
from stable_baselines3 import PPO, DQN, A2C
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.monitor import Monitor

# ── project-local imports ───────────────────────────────────────────────────
# Always run from inside backend/ so these relative imports work.
sys.path.insert(0, str(Path(__file__).parent))
from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv

# ── silence noisy SB3 device warnings ───────────────────────────────────────
warnings.filterwarnings("ignore", message=".*recommend using a GPU.*")

# ── paths ────────────────────────────────────────────────────────────────────
RESULTS_DIR = Path("./optuna_results")
BASELINE_DIR = Path("./fyp_baseline_training")

# ── tuning budget constants ───────────────────────────────────────────────────
N_EVAL_EPISODES = 20        # episodes per intermediate evaluation
EVAL_FREQ = 10_000          # evaluate every 10K steps (30 reports per 300K trial)
N_STARTUP_TRIALS = 5        # random exploration before TPE kicks in
N_WARMUP_STEPS = 5          # pruner: wait this many evals before pruning
PRUNER_INTERVAL = 1         # check for pruning every eval


# ════════════════════════════════════════════════════════════════════════════
#  ENVIRONMENT FACTORY
# ════════════════════════════════════════════════════════════════════════════

def make_env(seed: int = 0):
    """Create a fresh AdaptiveLearningEnv wrapped in Monitor."""
    sim = StudentSimulator(seed=seed)
    env = AdaptiveLearningEnv(sim)
    env = Monitor(env)
    return env


def make_vec_env(seed: int = 0) -> DummyVecEnv:
    return DummyVecEnv([lambda: make_env(seed)])


# ════════════════════════════════════════════════════════════════════════════
#  PRUNING CALLBACK
# ════════════════════════════════════════════════════════════════════════════

class TrialEvalCallback(EvalCallback):
    """
    EvalCallback extended to report intermediate values to an Optuna trial.

    At each evaluation, the mean reward is reported so Optuna's MedianPruner
    can terminate unpromising trials early.  When a trial is pruned, the
    callback raises ``optuna.exceptions.TrialPruned`` which SB3 propagates
    as a ``StopIteration`` (harmless — we catch it in the objective).
    """

    def __init__(self, trial: optuna.Trial, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trial = trial
        self.eval_idx = 0
        self.is_pruned = False

    def _on_step(self) -> bool:
        # Snapshot how many evaluations have run before calling parent
        n_evals_before = len(self.evaluations_results)
        continue_training = super()._on_step()
        n_evals_after = len(self.evaluations_results)

        if n_evals_after > n_evals_before:
            # A new evaluation just completed — report actual mean (not best)
            mean_reward = float(np.mean(self.evaluations_results[-1]))
            self.eval_idx += 1
            self.trial.report(mean_reward, step=self.eval_idx)

            if self.trial.should_prune():
                self.is_pruned = True
                return False  # signals SB3 to stop training

        return continue_training


# ════════════════════════════════════════════════════════════════════════════
#  NET-ARCH HELPER
# ════════════════════════════════════════════════════════════════════════════

def parse_net_arch(arch_str: str) -> list:
    """Convert arch string like '128x128' → [128, 128]."""
    return [int(x) for x in arch_str.split("x")]


# ════════════════════════════════════════════════════════════════════════════
#  OBJECTIVE FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def ppo_objective(trial: optuna.Trial, timesteps: int, device: str) -> float:
    """Optuna objective for PPO hyperparameter search."""
    # ── sample hyperparameters ────────────────────────────────────────────
    learning_rate = trial.suggest_float("learning_rate", 1e-5, 1e-3, log=True)
    n_steps = trial.suggest_categorical("n_steps", [256, 512, 1024, 2048, 4096])
    batch_size = trial.suggest_categorical("batch_size", [32, 64, 128, 256])
    n_epochs = trial.suggest_int("n_epochs", 3, 20)
    gamma = trial.suggest_float("gamma", 0.95, 0.999)
    gae_lambda = trial.suggest_float("gae_lambda", 0.9, 1.0)
    clip_range = trial.suggest_float("clip_range", 0.1, 0.4)
    ent_coef = trial.suggest_float("ent_coef", 0.0, 0.1)
    vf_coef = trial.suggest_float("vf_coef", 0.1, 1.0)
    max_grad_norm = trial.suggest_float("max_grad_norm", 0.3, 1.0)
    net_arch_str = trial.suggest_categorical(
        "net_arch", ["64x64", "128x128", "256x256", "64x64x64", "128x128x128"]
    )

    # ── constraint: batch_size must be <= n_steps (PPO requirement) ──────
    if batch_size > n_steps:
        batch_size = n_steps  # clamp; also tell Optuna via set_user_attr
        trial.set_user_attr("batch_size_clamped", True)

    net_arch = parse_net_arch(net_arch_str)
    policy_kwargs = {
        "net_arch": net_arch,
        "activation_fn": torch.nn.Tanh,
    }

    # ── build environments ────────────────────────────────────────────────
    trial_seed = trial.number * 13
    train_env = make_vec_env(seed=trial_seed)
    eval_env = make_vec_env(seed=trial_seed + 1)

    # ── save path for this trial ──────────────────────────────────────────
    trial_dir = RESULTS_DIR / "ppo" / f"trial_{trial.number}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    # ── build model ───────────────────────────────────────────────────────
    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=learning_rate,
        n_steps=n_steps,
        batch_size=batch_size,
        n_epochs=n_epochs,
        gamma=gamma,
        gae_lambda=gae_lambda,
        clip_range=clip_range,
        ent_coef=ent_coef,
        vf_coef=vf_coef,
        max_grad_norm=max_grad_norm,
        verbose=0,
        device=device,
        policy_kwargs=policy_kwargs,
    )

    # ── callbacks ─────────────────────────────────────────────────────────
    eval_callback = TrialEvalCallback(
        trial=trial,
        eval_env=eval_env,
        best_model_save_path=str(trial_dir / "best"),
        log_path=str(trial_dir / "eval_logs"),
        eval_freq=EVAL_FREQ,
        n_eval_episodes=N_EVAL_EPISODES,
        deterministic=True,
        render=False,
        verbose=0,
    )

    # ── train ─────────────────────────────────────────────────────────────
    try:
        model.learn(total_timesteps=timesteps, callback=eval_callback, progress_bar=True)
    except (AssertionError, ValueError) as e:
        # SB3 can raise on bad param combos (e.g., batch > rollout buffer)
        print(f"  [Trial {trial.number}] Training error: {e}")
        raise optuna.exceptions.TrialPruned()

    if eval_callback.is_pruned:
        raise optuna.exceptions.TrialPruned()

    if not eval_callback.evaluations_results:
        return -float("inf")
    return float(np.mean(eval_callback.evaluations_results[-1]))


def dqn_objective(trial: optuna.Trial, timesteps: int, device: str) -> float:
    """Optuna objective for DQN hyperparameter search."""
    # ── sample hyperparameters ────────────────────────────────────────────
    learning_rate = trial.suggest_float("learning_rate", 1e-5, 1e-3, log=True)
    buffer_size = trial.suggest_categorical(
        "buffer_size", [10_000, 50_000, 100_000, 200_000, 500_000]
    )
    learning_starts = trial.suggest_categorical("learning_starts", [500, 1000, 5000])
    batch_size = trial.suggest_categorical("batch_size", [32, 64, 128, 256])
    tau = trial.suggest_float("tau", 0.005, 1.0)
    gamma = trial.suggest_float("gamma", 0.95, 0.999)
    train_freq = trial.suggest_categorical("train_freq", [1, 4, 8, 16])
    gradient_steps = trial.suggest_categorical("gradient_steps", [1, 4])
    target_update_interval = trial.suggest_categorical(
        "target_update_interval", [500, 1000, 2500, 5000]
    )
    exploration_fraction = trial.suggest_float("exploration_fraction", 0.05, 0.3)
    exploration_final_eps = trial.suggest_float("exploration_final_eps", 0.01, 0.1)
    net_arch_str = trial.suggest_categorical(
        "net_arch", ["64x64", "128x128", "256x256", "64x64x64", "128x128x128"]
    )

    net_arch = parse_net_arch(net_arch_str)
    policy_kwargs = {
        "net_arch": net_arch,
        "activation_fn": torch.nn.ReLU,
    }

    trial_seed = trial.number * 17
    train_env = make_vec_env(seed=trial_seed)
    eval_env = make_vec_env(seed=trial_seed + 1)

    trial_dir = RESULTS_DIR / "dqn" / f"trial_{trial.number}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    model = DQN(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=learning_rate,
        buffer_size=buffer_size,
        learning_starts=learning_starts,
        batch_size=batch_size,
        tau=tau,
        gamma=gamma,
        train_freq=train_freq,
        gradient_steps=gradient_steps,
        target_update_interval=target_update_interval,
        exploration_fraction=exploration_fraction,
        exploration_final_eps=exploration_final_eps,
        verbose=0,
        device=device,
        policy_kwargs=policy_kwargs,
    )

    eval_callback = TrialEvalCallback(
        trial=trial,
        eval_env=eval_env,
        best_model_save_path=str(trial_dir / "best"),
        log_path=str(trial_dir / "eval_logs"),
        eval_freq=EVAL_FREQ,
        n_eval_episodes=N_EVAL_EPISODES,
        deterministic=True,
        render=False,
        verbose=0,
    )

    try:
        model.learn(total_timesteps=timesteps, callback=eval_callback, progress_bar=True)
    except (AssertionError, ValueError) as e:
        print(f"  [Trial {trial.number}] Training error: {e}")
        raise optuna.exceptions.TrialPruned()

    if eval_callback.is_pruned:
        raise optuna.exceptions.TrialPruned()

    if not eval_callback.evaluations_results:
        return -float("inf")
    return float(np.mean(eval_callback.evaluations_results[-1]))


def a2c_objective(trial: optuna.Trial, timesteps: int, device: str) -> float:
    """Optuna objective for A2C hyperparameter search."""
    # ── sample hyperparameters ────────────────────────────────────────────
    learning_rate = trial.suggest_float("learning_rate", 1e-5, 1e-2, log=True)
    n_steps = trial.suggest_categorical("n_steps", [5, 8, 16, 32, 50])
    gamma = trial.suggest_float("gamma", 0.95, 0.999)
    gae_lambda = trial.suggest_float("gae_lambda", 0.9, 1.0)
    ent_coef = trial.suggest_float("ent_coef", 0.0, 0.1)
    vf_coef = trial.suggest_float("vf_coef", 0.1, 1.0)
    max_grad_norm = trial.suggest_float("max_grad_norm", 0.3, 1.0)
    net_arch_str = trial.suggest_categorical(
        "net_arch", ["64x64", "128x128", "256x256", "64x64x64", "128x128x128"]
    )

    net_arch = parse_net_arch(net_arch_str)
    policy_kwargs = {
        "net_arch": net_arch,
        "activation_fn": torch.nn.Tanh,
    }

    trial_seed = trial.number * 11
    train_env = make_vec_env(seed=trial_seed)
    eval_env = make_vec_env(seed=trial_seed + 1)

    trial_dir = RESULTS_DIR / "a2c" / f"trial_{trial.number}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    model = A2C(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=learning_rate,
        n_steps=n_steps,
        gamma=gamma,
        gae_lambda=gae_lambda,
        ent_coef=ent_coef,
        vf_coef=vf_coef,
        max_grad_norm=max_grad_norm,
        verbose=0,
        device=device,
        policy_kwargs=policy_kwargs,
    )

    eval_callback = TrialEvalCallback(
        trial=trial,
        eval_env=eval_env,
        best_model_save_path=str(trial_dir / "best"),
        log_path=str(trial_dir / "eval_logs"),
        eval_freq=EVAL_FREQ,
        n_eval_episodes=N_EVAL_EPISODES,
        deterministic=True,
        render=False,
        verbose=0,
    )

    try:
        model.learn(total_timesteps=timesteps, callback=eval_callback, progress_bar=True)
    except (AssertionError, ValueError) as e:
        print(f"  [Trial {trial.number}] Training error: {e}")
        raise optuna.exceptions.TrialPruned()

    if eval_callback.is_pruned:
        raise optuna.exceptions.TrialPruned()

    if not eval_callback.evaluations_results:
        return -float("inf")
    return float(np.mean(eval_callback.evaluations_results[-1]))


# ════════════════════════════════════════════════════════════════════════════
#  STUDY RUNNER
# ════════════════════════════════════════════════════════════════════════════

OBJECTIVE_MAP = {
    "ppo": ppo_objective,
    "dqn": dqn_objective,
    "a2c": a2c_objective,
}


def load_baseline_score(algo: str) -> Optional[float]:
    """
    Load the best mean reward from the baseline training run's eval log.
    Returns None if the log is not found (non-fatal).
    """
    npz_path = BASELINE_DIR / algo / "eval_logs" / "evaluations.npz"
    if not npz_path.exists():
        return None
    try:
        data = np.load(str(npz_path))
        # evaluations.npz stores results shape (n_evals, n_episodes)
        mean_rewards = data["results"].mean(axis=1)
        return float(np.max(mean_rewards))
    except Exception as e:
        print(f"  [warn] Could not read baseline score for {algo}: {e}")
        return None


def run_study(
    algo: str,
    n_trials: int,
    timesteps: int,
    device: str,
    resume: bool,
) -> optuna.Study:
    """Create (or resume) an Optuna study and run optimisation."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    db_path = RESULTS_DIR / f"{algo}_study.db"
    storage = f"sqlite:///{db_path}"
    study_name = f"{algo}_adaptive_learning"

    sampler = TPESampler(seed=42, n_startup_trials=N_STARTUP_TRIALS)
    pruner = MedianPruner(
        n_startup_trials=N_STARTUP_TRIALS,
        n_warmup_steps=N_WARMUP_STEPS,
        interval_steps=PRUNER_INTERVAL,
    )

    # load_if_exists=True enables seamless Colab resume
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
        load_if_exists=resume or db_path.exists(),
    )

    # ── show baseline score for context ───────────────────────────────────
    baseline = load_baseline_score(algo)
    completed = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    remaining = max(0, n_trials - completed)

    print(f"\n{'='*65}")
    print(f"  {algo.upper()} Hyperparameter Optimisation")
    print(f"{'='*65}")
    print(f"  Study:       {study_name}")
    print(f"  Storage:     {db_path}")
    print(f"  Trials:      {completed} completed, {remaining} remaining (target: {n_trials})")
    print(f"  Budget:      {timesteps:,} steps / trial  ×  {remaining} trials")
    print(f"  Eval every:  {EVAL_FREQ:,} steps  ({N_EVAL_EPISODES} episodes)")
    if baseline is not None:
        print(f"  Baseline:    {baseline:.4f} mean reward (from fyp_baseline_training)")
    print(f"{'='*65}\n")

    if remaining == 0:
        print(f"  ✅ {algo.upper()} already has {completed}/{n_trials} completed trials — skipping.\n")
        save_best_params(algo, study)
        print_study_summary(algo, study, baseline)
        return study

    objective = OBJECTIVE_MAP[algo]

    def wrapped_objective(trial: optuna.Trial) -> float:
        print(f"▶  Trial {trial.number:3d} | {algo.upper()} | "
              f"{timesteps//1000}K steps", flush=True)
        result = objective(trial, timesteps=timesteps, device=device)
        print(f"✓  Trial {trial.number:3d} | reward = {result:.4f}", flush=True)
        return result

    study.optimize(
        wrapped_objective,
        n_trials=remaining,
        gc_after_trial=True,         # free GPU memory between trials
        show_progress_bar=False,
    )

    # ── save best params ───────────────────────────────────────────────────
    save_best_params(algo, study)
    print_study_summary(algo, study, baseline)

    return study


# ════════════════════════════════════════════════════════════════════════════
#  REPORTING & PERSISTENCE
# ════════════════════════════════════════════════════════════════════════════

def save_best_params(algo: str, study: optuna.Study) -> None:
    """Write best hyperparameters to JSON."""
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        print(f"  [warn] No completed trials for {algo} — nothing to save.")
        return

    best = study.best_trial
    out_path = RESULTS_DIR / f"{algo}_best_params.json"

    payload = {
        "algorithm": algo,
        "best_trial_number": best.number,
        "best_mean_reward": best.value,
        "hyperparameters": best.params,
        "n_completed_trials": len(completed),
        "n_pruned_trials": len(
            [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]
        ),
    }

    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n  ✅ Best params saved to: {out_path}")


def print_study_summary(
    algo: str, study: optuna.Study, baseline: Optional[float]
) -> None:
    """Print a concise summary table after optimisation."""
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]

    if not completed:
        print(f"\n  [!] No completed trials for {algo}.")
        return

    best = study.best_trial

    print(f"\n{'='*65}")
    print(f"  {algo.upper()} Optimisation Complete")
    print(f"{'='*65}")
    print(f"  Completed trials : {len(completed)}")
    print(f"  Pruned trials    : {len(pruned)}")
    print(f"  Best mean reward : {best.value:.4f}  (trial #{best.number})")
    if baseline is not None:
        delta = best.value - baseline
        pct = (delta / abs(baseline) * 100) if baseline != 0 else 0.0
        sign = "+" if delta >= 0 else ""
        print(f"  vs. baseline     : {sign}{delta:.4f}  ({sign}{pct:.1f}%)")
    print(f"\n  Best hyperparameters:")
    for k, v in best.params.items():
        print(f"    {k:<30s} = {v}")
    print(f"{'='*65}\n")


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optuna hyperparameter optimisation for adaptive-learning RL agents.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        default="ppo",
        choices=["ppo", "dqn", "a2c", "all"],
        help="Which RL algorithm to optimise.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=50,
        help="Number of Optuna trials to run.",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=300_000,
        help="SB3 training timesteps per trial.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda", "auto"],
        help="PyTorch device.  MLP policies run fastest on CPU.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume an existing study (load_if_exists=True).",
    )
    parser.add_argument(
        "--verbosity",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Optuna log verbosity (0=WARNING, 1=INFO, 2=DEBUG).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── configure Optuna logging ───────────────────────────────────────────
    verbosity_map = {
        0: optuna.logging.WARNING,
        1: optuna.logging.INFO,
        2: optuna.logging.DEBUG,
    }
    optuna.logging.set_verbosity(verbosity_map[args.verbosity])

    algos = ["ppo", "dqn", "a2c"] if args.algorithm == "all" else [args.algorithm]

    for algo in algos:
        run_study(
            algo=algo,
            n_trials=args.trials,
            timesteps=args.timesteps,
            device=args.device,
            resume=args.resume,
        )

    print("\n🏁 All optimisation runs complete.")
    print(f"   Results directory : {RESULTS_DIR.resolve()}")
    print(f"   Best params files :")
    for algo in algos:
        p = RESULTS_DIR / f"{algo}_best_params.json"
        if p.exists():
            print(f"     {p}")


if __name__ == "__main__":
    main()
