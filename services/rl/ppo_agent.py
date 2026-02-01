"""
Proximal Policy Optimization (PPO) Agent.

PPO is the recommended algorithm for this problem because:
- Stable training (less hyperparameter sensitivity)
- Works well with discrete action spaces
- Sample efficient for curriculum learning
- Industry standard (used by OpenAI, DeepMind)

Architecture:
- Policy Network: MLP [state_dim → 64 → 64 → action_dim] (actor)
- Value Network: MLP [state_dim → 64 → 64 → 1] (critic)
- State dim: Dynamic based on curriculum (default: 38D with 5 languages, 8 topics)
- Action dim: Dynamic based on curriculum (default: 40 = 8 topics × 5 difficulties)
- Activation: Tanh
- Optimizer: Adam (lr=3e-4)

Hardware Optimization:
- Configured for 4GB VRAM (T1200 GPU)
- Smaller network (64 hidden units vs 128)
- Smaller batch size (32-64)
- Works on CPU if GPU unavailable
"""

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, StopTrainingOnNoModelImprovement
from stable_baselines3.common.vec_env import DummyVecEnv
import torch
import numpy as np
from pathlib import Path
from typing import Optional, Union


class PPOAgent:
    """
    PPO-based RL agent for adaptive curriculum sequencing.
    
    This agent learns to select optimal (topic, difficulty) pairs by
    maximizing long-term learning outcomes (mastery improvement).
    
    Example Usage:
        >>> from services.rl.student_simulator import StudentSimulator
        >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
        >>> from services.rl.ppo_agent import PPOAgent
        >>> 
        >>> sim = StudentSimulator(seed=42)
        >>> env = AdaptiveLearningEnv(sim)
        >>> agent = PPOAgent(env)
        >>> 
        >>> # Training
        >>> agent.train(total_timesteps=100000)
        >>> 
        >>> # Inference
        >>> state, info = env.reset()
        >>> action, _ = agent.predict(state)
        >>> topic, difficulty = env.decode_action(action)
    
    Attributes:
        model: Stable-Baselines3 PPO model
        device: Device used for training ('cuda' or 'cpu')
    """
    
    def __init__(
        self,
        env,
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: float = 0.2,
        ent_coef: float = 0.01,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        tensorboard_log: str = "./tensorboard/ppo/",
        device: str = "auto"
    ):
        """
        Initialize PPO agent with optimized hyperparameters.
        
        Args:
            env: Gymnasium environment (AdaptiveLearningEnv)
            learning_rate: Adam optimizer learning rate (default: 3e-4)
            n_steps: Number of steps to collect per rollout (default: 2048)
            batch_size: Minibatch size for gradient updates (default: 64)
            n_epochs: Number of epochs to train on collected data (default: 10)
            gamma: Discount factor for future rewards (default: 0.99)
            gae_lambda: GAE lambda parameter (default: 0.95)
            clip_range: PPO clipping parameter (default: 0.2)
            ent_coef: Entropy coefficient for exploration (default: 0.01)
            vf_coef: Value function loss coefficient (default: 0.5)
            max_grad_norm: Gradient clipping threshold (default: 0.5)
            tensorboard_log: Path for TensorBoard logs (default: './tensorboard/ppo/')
            device: Device to use - 'cuda', 'cpu', or 'auto' (default: 'auto')
        
        Note:
            Hyperparameters are optimized for 4GB VRAM (T1200 GPU).
            Smaller batch_size and net_arch reduce memory usage.
        """
        
        # Wrap in vectorized environment (Stable-Baselines3 requirement)
        if not isinstance(env, DummyVecEnv):
            env = DummyVecEnv([lambda: env])
        
        # Network architecture (optimized for 4GB VRAM)
        policy_kwargs = {
            "net_arch": [64, 64],  # 2-layer MLP (smaller than default 256)
            "activation_fn": torch.nn.Tanh  # Tanh activation
        }
        
        # Create PPO model
        self.model = PPO(
            policy="MlpPolicy",
            env=env,
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
            # DummyVecEnv stores environments in .envs list
            unwrapped_env = env.envs[0]
        else:
            unwrapped_env = env
        
        state_dim = unwrapped_env.observation_space.shape[0]
        action_dim = unwrapped_env.action_space.n
        
        print(f"✅ PPO Agent initialized on device: {actual_device}")
        print(f"   Network architecture: {state_dim}D → 64 → 64 → {action_dim} (policy)")
        print(f"   Network architecture: {state_dim}D → 64 → 64 → 1 (value)")
        print(f"   ⚠️  State locked to: {state_dim}D (from curriculum)")
    
    def train(
        self,
        total_timesteps: int = 100000,
        eval_env=None,
        eval_freq: int = 5000,
        save_path: str = "./models/ppo/",
        checkpoint_freq: int = 10000,
        log_interval: int = 10
    ):
        """
        Train the PPO agent.
        
        Args:
            total_timesteps: Total number of training timesteps (default: 100K)
            eval_env: Optional evaluation environment (default: None)
            eval_freq: Evaluate every N steps (default: 5000)
            save_path: Directory to save models (default: './models/ppo/')
            checkpoint_freq: Save checkpoint every N steps (default: 10000)
            log_interval: Log training info every N updates (default: 10)
        
        Example:
            >>> agent.train(total_timesteps=100000)
            # Training with TensorBoard logging
            # Checkpoints saved every 10K steps
            # Final model saved to ./models/ppo/final_model.zip
        
        Returns:
            None (model is trained in-place)
        
        Note:
            Training progress can be monitored with:
            $ tensorboard --logdir=./tensorboard/ppo/
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
            
            # Early stopping: stop if no improvement for 50K steps
            stop_callback = StopTrainingOnNoModelImprovement(
                max_no_improvement_evals=10,  # 10 evals × 5000 steps = 50K steps patience
                min_evals=20,  # Wait at least 100K steps before early stopping
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
                callback_after_eval=stop_callback  # Add early stopping
            )
            callbacks.append(eval_callback)
            print(f"✅ Evaluation enabled (every {eval_freq} steps)")
            print(f"✅ Early stopping enabled (patience: 50K steps, min: 100K steps)")
        
        # Checkpoint callback
        checkpoint_callback = CheckpointCallback(
            save_freq=checkpoint_freq,
            save_path=f"{save_path}/checkpoints/",
            name_prefix="ppo_model",
            save_replay_buffer=False,
            save_vecnormalize=False
        )
        callbacks.append(checkpoint_callback)
        print(f"✅ Checkpointing enabled (every {checkpoint_freq} steps)")
        
        # Training info
        print("\n" + "=" * 70)
        print("STARTING PPO TRAINING")
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
            state: 36D state vector (numpy array)
            deterministic: If True, use mean action; if False, sample from policy
        
        Returns:
            Tuple of (action, value_estimate):
            - action: Integer 0-39 representing (topic, difficulty)
            - value_estimate: Estimated state value (not used in inference)
        
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
            >>> agent.load("models/ppo/best/best_model")
            # Loads from models/ppo/best/best_model.zip
        """
        self.model = PPO.load(path, device=self.device)
        print(f"✅ Model loaded from {path}")
    
    @classmethod
    def load_pretrained(cls, path: str, env, device: str = "auto"):
        """
        Load a pre-trained PPO model.
        
        Args:
            path: Path to saved model
            env: Environment to use with loaded model
            device: Device to load model on ('cuda', 'cpu', or 'auto')
        
        Returns:
            PPOAgent instance with loaded model
        
        Example:
            >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
            >>> env = AdaptiveLearningEnv(sim)
            >>> agent = PPOAgent.load_pretrained("models/ppo/best/best_model", env)
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
            "policy_type": "MlpPolicy",
            "network_architecture": str(self.model.policy),
            "device": str(self.model.device),
            "learning_rate": self.model.learning_rate,
            "n_steps": self.model.n_steps,
            "batch_size": self.model.batch_size,
            "gamma": self.model.gamma,
            "clip_range": self.model.clip_range
        }
