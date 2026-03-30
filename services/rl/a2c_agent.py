"""
Advantage Actor-Critic (A2C) Agent.

A2C is a synchronous variant of A3C for curriculum sequencing:
- On-policy learning (like PPO, but simpler)
- Combines value-based and policy-based methods
- Faster training than PPO (fewer hyperparameters)
- Good baseline comparison for PPO

Architecture:
- Policy Network: MLP [state_dim → 64 → 64 → action_dim] (actor)
- Value Network: MLP [state_dim → 64 → 64 → 1] (critic)
- State dim: Dynamic based on curriculum (default: 38D with 5 languages, 8 topics)
- Action dim: Dynamic based on curriculum (default: 40 = 8 topics × 5 difficulties)
- Activation: Tanh
- Optimizer: RMSprop (lr=7e-4)

Hardware Optimization:
- Configured for 4GB VRAM (T1200 GPU)
- Smaller network (64 hidden units vs 128)
- Works on CPU if GPU unavailable
"""

from stable_baselines3 import A2C
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, StopTrainingOnNoModelImprovement
from stable_baselines3.common.vec_env import DummyVecEnv
import torch
import numpy as np
from pathlib import Path
from typing import Optional, Union
from .accessibility_callback import AccessibilityMetricsCallback


class A2CAgent:
    """
    A2C-based RL agent for adaptive curriculum sequencing.
    
    This agent learns to select optimal (topic, difficulty) pairs using
    advantage actor-critic with synchronous updates.
    
    Example Usage:
        >>> from services.rl.student_simulator import StudentSimulator
        >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
        >>> from services.rl.a2c_agent import A2CAgent
        >>> 
        >>> sim = StudentSimulator(seed=42)
        >>> env = AdaptiveLearningEnv(sim)
        >>> agent = A2CAgent(env)
        >>> 
        >>> # Training
        >>> agent.train(total_timesteps=100000)
        >>> 
        >>> # Inference
        >>> state, info = env.reset()
        >>> action, _ = agent.predict(state)
        >>> topic, difficulty = env.decode_action(action)
    
    Attributes:
        model: Stable-Baselines3 A2C model
        device: Device used for training ('cuda' or 'cpu')
    """
    
    def __init__(
        self,
        env,
        learning_rate: float = 7e-4,
        n_steps: int = 8,   # FIX: was 50 — with avg 15-step episodes, n_steps=50 means
                              # A2C never completes a full trajectory before updating.
                              # n_steps=8 ensures updates happen within short episodes.
        gamma: float = 0.99,
        gae_lambda: float = 1.0,
        ent_coef: float = 0.01,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        rms_prop_eps: float = 1e-5,
        use_rms_prop: bool = True,
        normalize_advantage: bool = False,
        tensorboard_log: str = "./tensorboard/a2c/",
        device: str = "auto"
    ):
        """
        Initialize A2C agent with optimized hyperparameters.
        
        Args:
            env: Gymnasium environment (AdaptiveLearningEnv)
            learning_rate: Optimizer learning rate (default: 7e-4)
            n_steps: Number of steps per rollout (default: 50, was 5)
            gamma: Discount factor for future rewards (default: 0.99)
            gae_lambda: GAE lambda for advantage estimation (default: 1.0)
            ent_coef: Entropy coefficient for exploration (default: 0.01)
            vf_coef: Value function loss coefficient (default: 0.5)
            max_grad_norm: Gradient clipping threshold (default: 0.5)
            rms_prop_eps: RMSprop epsilon (default: 1e-5)
            use_rms_prop: Use RMSprop instead of Adam (default: True)
            normalize_advantage: Normalize advantages (default: False)
            tensorboard_log: Path for TensorBoard logs (default: './tensorboard/a2c/')
            device: Device to use - 'cuda', 'cpu', or 'auto' (default: 'auto')
        
        Note:
            Hyperparameters are optimized for 4GB VRAM (T1200 GPU).
            Smaller net_arch reduces memory usage.
        """
        
        # Wrap in vectorized environment (Stable-Baselines3 requirement)
        if not isinstance(env, DummyVecEnv):
            env = DummyVecEnv([lambda: env])
        
        # Network architecture (optimized for 4GB VRAM)
        policy_kwargs = {
            "net_arch": [64, 64],  # 2-layer MLP (smaller than default 256)
            "activation_fn": torch.nn.Tanh  # Tanh activation
        }
        
        # Create A2C model
        self.model = A2C(
            policy="MlpPolicy",
            env=env,
            learning_rate=learning_rate,
            n_steps=n_steps,
            gamma=gamma,
            gae_lambda=gae_lambda,
            ent_coef=ent_coef,
            vf_coef=vf_coef,
            max_grad_norm=max_grad_norm,
            rms_prop_eps=rms_prop_eps,
            use_rms_prop=use_rms_prop,
            normalize_advantage=normalize_advantage,
            verbose=1,
            tensorboard_log=tensorboard_log,
            device=device,
            policy_kwargs=policy_kwargs
        )
        
        self.device = device
        
        # Print device info
        if device == "auto":
            actual_device = self.model.device
        else:
            actual_device = device
        
        # Get environment dimensions (handle DummyVecEnv wrapper)
        if hasattr(env, 'envs'):
            unwrapped_env = env.envs[0]
        else:
            unwrapped_env = env
        
        state_dim = unwrapped_env.observation_space.shape[0]
        action_dim = unwrapped_env.action_space.n
        
        print(f"✅ A2C Agent initialized on device: {actual_device}")
        print(f"   Network architecture: {state_dim}D → 64 → 64 → {action_dim} (policy)")
        print(f"   Network architecture: {state_dim}D → 64 → 64 → 1 (value)")
        print(f"   ⚠️  State locked to: {state_dim}D (from curriculum)")
    
    def train(
        self,
        total_timesteps: int = 100000,
        eval_env=None,
        eval_freq: int = 5000,
        save_path: str = "./models/a2c/",
        checkpoint_freq: int = 10000,
        log_interval: int = 100
    ):
        """
        Train the A2C agent.
        
        Args:
            total_timesteps: Total number of training timesteps (default: 100K)
            eval_env: Optional evaluation environment (default: None)
            eval_freq: Evaluate every N steps (default: 5000)
            save_path: Directory to save models (default: './models/a2c/')
            checkpoint_freq: Save checkpoint every N steps (default: 10000)
            log_interval: Log training info every N updates (default: 100)
        
        Example:
            >>> agent.train(total_timesteps=100000)
            # Training with TensorBoard logging
            # Checkpoints saved every 10K steps
            # Final model saved to ./models/a2c/final_model.zip
        
        Returns:
            None (model is trained in-place)
        
        Note:
            Training progress can be monitored with:
            $ tensorboard --logdir=./tensorboard/a2c/
        """
        
        # Create save directories
        Path(save_path).mkdir(parents=True, exist_ok=True)
        Path(f"{save_path}/best/").mkdir(parents=True, exist_ok=True)
        Path(f"{save_path}/checkpoints/").mkdir(parents=True, exist_ok=True)
        
        # Setup callbacks
        callbacks = []
        
        # Evaluation callback (if eval env provided)
        if eval_env is not None:
            # Wrap eval env if needed
            if not isinstance(eval_env, DummyVecEnv):
                eval_env = DummyVecEnv([lambda: eval_env])
            
            # Early stopping re-enabled with safer parameters
            # With clipped rewards [-10, +10], convergence signal is stable enough
            # max_no_improvement_evals=20 → 200K steps patience (at eval_freq=10K)
            # min_evals=40 → wait 400K steps minimum before early stopping kicks in
            # This prevents BLOCKER #1 regression (was: patience=50K, min=100K — too aggressive)
            stop_callback = StopTrainingOnNoModelImprovement(
                max_no_improvement_evals=20,  # 20 evals × 10000 steps = 200K steps patience
                min_evals=40,  # Wait at least 400K steps before early stopping
                verbose=1
            )
            
            eval_callback = EvalCallback(
                eval_env,
                best_model_save_path=f"{save_path}/best/",
                log_path=f"{save_path}/eval_logs/",
                eval_freq=eval_freq,
                deterministic=True,
                render=False,
                verbose=1,
                callback_after_eval=stop_callback
            )
            callbacks.append(eval_callback)
            print(f"✅ Evaluation enabled (every {eval_freq} steps)")
            print(f"✅ Early stopping enabled (patience: 200K steps, min: 400K steps)")
        
        # Checkpoint callback
        checkpoint_callback = CheckpointCallback(
            save_freq=checkpoint_freq,
            save_path=f"{save_path}/checkpoints/",
            name_prefix="a2c_model",
            save_replay_buffer=False,
            save_vecnormalize=False
        )
        callbacks.append(checkpoint_callback)
        print(f"✅ Checkpointing enabled (every {checkpoint_freq} steps)")
        
        # Accessibility metrics callback
        accessibility_callback = AccessibilityMetricsCallback(
            check_freq=5000,  # Log every 5K steps
            verbose=1
        )
        callbacks.append(accessibility_callback)
        print(f"✅ Accessibility tracking enabled (curriculum constraint monitoring)")
        
        # Training info
        print("\n" + "=" * 70)
        print("STARTING A2C TRAINING")
        print("=" * 70)
        print(f"Total timesteps: {total_timesteps:,}")
        print(f"Episodes: ~{total_timesteps // 50:,} (assuming 50 steps/episode)")
        print(f"TensorBoard: {self.model.tensorboard_log}")
        print(f"Save path: {save_path}")
        print("=" * 70 + "\n")
        
        # Train
        self.model.learn(
            total_timesteps=total_timesteps,
            callback=callbacks,
            log_interval=log_interval,
            progress_bar=True
        )
        
        # Save final model
        final_path = f"{save_path}/final_model"
        self.model.save(final_path)
        
        print("\n" + "=" * 70)
        print("✅ TRAINING COMPLETE!")
        print("=" * 70)
        print(f"Final model saved to: {final_path}.zip")
        print(f"Best model saved to: {save_path}/best/best_model.zip")
        print(f"Checkpoints saved to: {save_path}/checkpoints/")
        print(f"\nTo visualize training:")
        print(f"  tensorboard --logdir={self.model.tensorboard_log}")
        print("=" * 70)
    
    def predict(
        self,
        state: np.ndarray,
        deterministic: bool = True
    ) -> tuple:
        """
        Predict next action given current state.
        
        Args:
            state: State vector (numpy array)
            deterministic: If True, use mean action; if False, sample from policy
        
        Returns:
            Tuple of (action, value_estimate):
            - action: Integer 0-39 representing (topic, difficulty)
            - value_estimate: None (for API compatibility)
        
        Example:
            >>> state = env.reset()
            >>> action, _ = agent.predict(state)
            >>> print(f"Action: {action}")
            >>> topic, difficulty = env.decode_action(action)
            >>> print(f"Teach {topic} at {difficulty} difficulty")
        """
        action, _states = self.model.predict(state, deterministic=deterministic)
        return int(action), None
    
    def save(self, path: str):
        """
        Save model to disk.
        
        Args:
            path: Path to save model (without .zip extension)
        
        Example:
            >>> agent.save("my_trained_model")
            # Saves to my_trained_model.zip
        """
        self.model.save(path)
        print(f"✅ Model saved to {path}.zip")
    
    def load(self, path: str):
        """
        Load model from disk.
        
        Args:
            path: Path to model file (with or without .zip extension)
        
        Example:
            >>> agent.load("models/a2c/best/best_model")
            # Loads from models/a2c/best/best_model.zip
        """
        self.model = A2C.load(path, device=self.device)
        print(f"✅ Model loaded from {path}")
    
    @classmethod
    def load_pretrained(cls, path: str, env, device: str = "auto"):
        """
        Load a pre-trained A2C model.
        
        Args:
            path: Path to saved model
            env: Environment to use with loaded model
            device: Device to load model on ('cuda', 'cpu', or 'auto')
        
        Returns:
            A2CAgent instance with loaded model
        
        Example:
            >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
            >>> env = AdaptiveLearningEnv(sim)
            >>> agent = A2CAgent.load_pretrained("models/a2c/best/best_model", env)
            >>> action, _ = agent.predict(state)
        """
        agent = cls(env, device=device)
        agent.load(path)
        return agent
    
    def get_policy_info(self) -> dict:
        """
        Get information about the policy network.
        
        Returns:
            Dictionary with network architecture details
        """
        return {
            "policy_type": "MlpPolicy (A2C)",
            "network_architecture": str(self.model.policy),
            "device": str(self.model.device),
            "learning_rate": self.model.learning_rate,
            "n_steps": self.model.n_steps,
            "gamma": self.model.gamma,
            "ent_coef": self.model.ent_coef,
            "vf_coef": self.model.vf_coef
        }
