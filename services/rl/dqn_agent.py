"""
Deep Q-Network (DQN) Agent.

DQN is an alternative algorithm for curriculum sequencing:
- Value-based learning (learns Q-values directly)
- Works well with discrete action spaces
- Uses experience replay for sample efficiency
- Target network for stable training

Architecture:
- Q-Network: MLP [state_dim → 64 → 64 → action_dim]
- State dim: Dynamic based on curriculum (default: 38D with 5 languages, 8 topics)
- Action dim: Dynamic based on curriculum (default: 40 = 8 topics × 5 difficulties)
- Activation: ReLU
- Optimizer: Adam (lr=1e-4)

Hardware Optimization:
- Configured for 4GB VRAM (T1200 GPU)
- Smaller network (64 hidden units vs 128)
- Smaller buffer size (50K vs 1M)
- Works on CPU if GPU unavailable
"""

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, StopTrainingOnNoModelImprovement
from stable_baselines3.common.vec_env import DummyVecEnv
import torch
import numpy as np
from pathlib import Path
from typing import Optional, Union
from .accessibility_callback import AccessibilityMetricsCallback


class DQNAgent:
    """
    DQN-based RL agent for adaptive curriculum sequencing.
    
    This agent learns to select optimal (topic, difficulty) pairs by
    learning action-value (Q) functions.
    
    Example Usage:
        >>> from services.rl.student_simulator import StudentSimulator
        >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
        >>> from services.rl.dqn_agent import DQNAgent
        >>> 
        >>> sim = StudentSimulator(seed=42)
        >>> env = AdaptiveLearningEnv(sim)
        >>> agent = DQNAgent(env)
        >>> 
        >>> # Training
        >>> agent.train(total_timesteps=100000)
        >>> 
        >>> # Inference
        >>> state, info = env.reset()
        >>> action, _ = agent.predict(state)
        >>> topic, difficulty = env.decode_action(action)
    
    Attributes:
        model: Stable-Baselines3 DQN model
        device: Device used for training ('cuda' or 'cpu')
    """
    
    def __init__(
        self,
        env,
        learning_rate: float = 1e-4,
        buffer_size: int = 50000,
        learning_starts: int = 1000,
        batch_size: int = 64,
        tau: float = 1.0,
        gamma: float = 0.99,
        train_freq: int = 4,
        gradient_steps: int = 1,
        target_update_interval: int = 1000,
        exploration_fraction: float = 0.2,
        exploration_initial_eps: float = 1.0,
        exploration_final_eps: float = 0.05,
        tensorboard_log: str = "./tensorboard/dqn/",
        device: str = "auto"
    ):
        """
        Initialize DQN agent with optimized hyperparameters.
        
        Args:
            env: Gymnasium environment (AdaptiveLearningEnv)
            learning_rate: Adam optimizer learning rate (default: 1e-4)
            buffer_size: Size of replay buffer (default: 50K for 4GB VRAM)
            learning_starts: Steps before learning starts (default: 1000)
            batch_size: Minibatch size for gradient updates (default: 64)
            tau: Target network soft update coefficient (default: 1.0 = hard update)
            gamma: Discount factor for future rewards (default: 0.99)
            train_freq: Train every N steps (default: 4)
            gradient_steps: Gradient updates per training step (default: 1)
            target_update_interval: Steps between target network updates (default: 1000)
            exploration_fraction: Fraction of training for epsilon decay (default: 0.2)
            exploration_initial_eps: Initial exploration rate (default: 1.0)
            exploration_final_eps: Final exploration rate (default: 0.05)
            tensorboard_log: Path for TensorBoard logs (default: './tensorboard/dqn/')
            device: Device to use - 'cuda', 'cpu', or 'auto' (default: 'auto')
        
        Note:
            Hyperparameters are optimized for 4GB VRAM (T1200 GPU).
            Smaller buffer_size and net_arch reduce memory usage.
        """
        
        # Wrap in vectorized environment (Stable-Baselines3 requirement)
        if not isinstance(env, DummyVecEnv):
            env = DummyVecEnv([lambda: env])
        
        # Network architecture (optimized for 4GB VRAM)
        policy_kwargs = {
            "net_arch": [64, 64],  # 2-layer MLP (smaller than default 256)
            "activation_fn": torch.nn.ReLU  # ReLU activation for DQN
        }
        
        # Create DQN model
        self.model = DQN(
            policy="MlpPolicy",
            env=env,
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
            exploration_initial_eps=exploration_initial_eps,
            exploration_final_eps=exploration_final_eps,
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
        
        print(f"✅ DQN Agent initialized on device: {actual_device}")
        print(f"   Network architecture: {state_dim}D → 64 → 64 → {action_dim} (Q-network)")
        print(f"   Replay buffer size: {buffer_size:,}")
        print(f"   ⚠️  State locked to: {state_dim}D (from curriculum)")
    
    def train(
        self,
        total_timesteps: int = 100000,
        eval_env=None,
        eval_freq: int = 5000,
        save_path: str = "./models/dqn/",
        checkpoint_freq: int = 10000,
        log_interval: int = 100
    ):
        """
        Train the DQN agent.
        
        Args:
            total_timesteps: Total number of training timesteps (default: 100K)
            eval_env: Optional evaluation environment (default: None)
            eval_freq: Evaluate every N steps (default: 5000)
            save_path: Directory to save models (default: './models/dqn/')
            checkpoint_freq: Save checkpoint every N steps (default: 10000)
            log_interval: Log training info every N episodes (default: 100)
        
        Example:
            >>> agent.train(total_timesteps=100000)
            # Training with TensorBoard logging
            # Checkpoints saved every 10K steps
            # Final model saved to ./models/dqn/final_model.zip
        
        Returns:
            None (model is trained in-place)
        
        Note:
            Training progress can be monitored with:
            $ tensorboard --logdir=./tensorboard/dqn/
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
            name_prefix="dqn_model",
            save_replay_buffer=False,  # Don't save buffer (too large)
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
        print("STARTING DQN TRAINING")
        print("=" * 70)
        print(f"Total timesteps: {total_timesteps:,}")
        print(f"Episodes: ~{total_timesteps // 50:,} (assuming 50 steps/episode)")
        print(f"TensorBoard: {self.model.tensorboard_log}")
        print(f"Save path: {save_path}")
        print(f"Exploration: {self.model.exploration_initial_eps:.0%} → {self.model.exploration_final_eps:.0%}")
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
            deterministic: If True, use greedy action; if False, use epsilon-greedy
        
        Returns:
            Tuple of (action, q_value):
            - action: Integer 0-39 representing (topic, difficulty)
            - q_value: None (for API compatibility with PPO)
        
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
            >>> agent.load("models/dqn/best/best_model")
            # Loads from models/dqn/best/best_model.zip
        """
        self.model = DQN.load(path, device=self.device)
        print(f"✅ Model loaded from {path}")
    
    @classmethod
    def load_pretrained(cls, path: str, env, device: str = "auto"):
        """
        Load a pre-trained DQN model.
        
        Args:
            path: Path to saved model
            env: Environment to use with loaded model
            device: Device to load model on ('cuda', 'cpu', or 'auto')
        
        Returns:
            DQNAgent instance with loaded model
        
        Example:
            >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
            >>> env = AdaptiveLearningEnv(sim)
            >>> agent = DQNAgent.load_pretrained("models/dqn/best/best_model", env)
            >>> action, _ = agent.predict(state)
        """
        agent = cls(env, device=device)
        agent.load(path)
        return agent
    
    def get_policy_info(self) -> dict:
        """
        Get information about the Q-network.
        
        Returns:
            Dictionary with network architecture details
        """
        return {
            "policy_type": "MlpPolicy (DQN)",
            "network_architecture": str(self.model.policy),
            "device": str(self.model.device),
            "learning_rate": self.model.learning_rate,
            "buffer_size": self.model.buffer_size,
            "batch_size": self.model.batch_size,
            "gamma": self.model.gamma,
            "exploration_rate": self.model.exploration_rate
        }
