"""
Component 4: RL Training Pipeline

Orchestrates full training process for RL agents.

Usage:
    # Train PPO for 100K timesteps (recommended)
    python train_rl_model.py --algorithm ppo --timesteps 100000
    
    # Quick test (1K steps)
    python train_rl_model.py --algorithm ppo --timesteps 1000
    
    # Train both PPO and DQN
    python train_rl_model.py --algorithm all --timesteps 100000
    
    # Force CPU training
    python train_rl_model.py --algorithm ppo --device cpu

Features:
    - Automatic directory creation
    - Checkpoint saving (every 10K steps)
    - Evaluation during training (every 5K steps)
    - TensorBoard logging
    - Progress tracking
    - Training time measurement
"""

import argparse
from pathlib import Path
import time
import sys

from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
from services.rl.ppo_agent import PPOAgent
from services.rl.dqn_agent import DQNAgent
from services.rl.a2c_agent import A2CAgent
from services.config import get_config


def train_ppo(timesteps: int = 100000, device: str = "auto"):
    """
    Train PPO agent with full monitoring and checkpointing.
    
    Args:
        timesteps: Total training timesteps (default: 100K)
        device: "cuda", "cpu", or "auto"
    
    Returns:
        Trained PPO agent
    """
    
    print("=" * 70)
    print("🤖 TRAINING PPO AGENT")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Algorithm: Proximal Policy Optimization (PPO)")
    print(f"  Timesteps: {timesteps:,}")
    print(f"  Device: {device}")
    print(f"  Expected episodes: ~{timesteps // 20:,} (20 steps/episode)")
    
    # Estimate training time
    if device == "cuda":
        estimated_minutes = timesteps / 1000 * 0.035  # Based on demo: 1K steps = 2 seconds
    else:
        estimated_minutes = timesteps / 1000 * 0.5  # CPU is slower
    
    print(f"  Estimated time: ~{estimated_minutes:.1f} minutes")
    print()
    
    # Create environments
    print("1. Initializing components...")
    
    # Load curriculum config to show dynamic info
    config = get_config()
    num_topics = len(config.universal_mappings)
    num_languages = len(config.valid_languages)
    
    simulator = StudentSimulator(seed=42)
    
    train_env = AdaptiveLearningEnv(
        simulator=simulator,
        max_steps_per_episode=100
    )
    
    eval_env = AdaptiveLearningEnv(
        simulator=StudentSimulator(seed=123),  # Different seed for evaluation
        max_steps_per_episode=100
    )
    
    print("   ✅ Simulator: 100 diverse students (30% beginner, 40% intermediate, 30% advanced)")
    print(f"   ✅ Curriculum: {num_topics} topics across {num_languages} languages (from final_curriculum.json)")
    print(f"   ✅ State space: {train_env.observation_space.shape[0]}D vector [LOCKED to current curriculum]")
    print(f"   ✅ Action space: {train_env.action_space.n} actions ({num_topics} topics × {len(train_env.difficulty_tiers)} difficulties)")
    print("   ✅ Training environment ready")
    print("   ✅ Evaluation environment ready")
    
    # Create PPO agent
    print("\n2. Creating PPO agent...")
    agent = PPOAgent(
        env=train_env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        tensorboard_log="./tensorboard/ppo/",
        device=device
    )
    
    print("\n3. Starting training...")
    print("=" * 70)
    
    # Train
    start_time = time.time()
    
    agent.train(
        total_timesteps=timesteps,
        eval_env=eval_env,
        eval_freq=5000,
        save_path="./models/ppo/",
        checkpoint_freq=10000
    )
    
    elapsed = time.time() - start_time
    
    # Print summary
    print("\n" + "=" * 70)
    print("✅ PPO TRAINING COMPLETE!")
    print("=" * 70)
    print(f"\n📊 Training Summary:")
    print(f"   Total timesteps: {timesteps:,}")
    print(f"   Training time: {elapsed/60:.1f} minutes ({elapsed:.0f} seconds)")
    print(f"   Speed: {timesteps/elapsed:.1f} steps/second")
    print(f"\n💾 Saved Models:")
    print(f"   Final model: ./models/ppo/final_model.zip")
    print(f"   Best model: ./models/ppo/best/best_model.zip")
    print(f"   Checkpoints: ./models/ppo/checkpoints/")
    print(f"\n📈 Visualize Training:")
    print(f"   tensorboard --logdir=./tensorboard/ppo/")
    print(f"   Then open: http://localhost:6006")
    print("=" * 70)
    
    return agent


def train_dqn(timesteps: int = 100000, device: str = "auto"):
    """
    Train DQN agent (for comparison with PPO).
    
    Args:
        timesteps: Total training timesteps
        device: "cuda", "cpu", or "auto"
    
    Returns:
        Trained DQN agent
    """
    
    print("=" * 70)
    print("🤖 TRAINING DQN AGENT")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Algorithm: Deep Q-Network (DQN)")
    print(f"  Timesteps: {timesteps:,}")
    print(f"  Device: {device}")
    print(f"  Expected episodes: ~{timesteps // 20:,} (20 steps/episode)")
    
    # Estimate training time
    if device == "cuda":
        estimated_minutes = timesteps / 1000 * 0.04  # DQN slightly slower than PPO
    else:
        estimated_minutes = timesteps / 1000 * 0.6
    
    print(f"  Estimated time: ~{estimated_minutes:.1f} minutes")
    print()
    
    # Create environments
    print("1. Initializing components...")
    
    config = get_config()
    num_topics = len(config.universal_mappings)
    num_languages = len(config.valid_languages)
    
    simulator = StudentSimulator(seed=42)
    
    train_env = AdaptiveLearningEnv(
        simulator=simulator,
        max_steps_per_episode=100
    )
    
    eval_env = AdaptiveLearningEnv(
        simulator=StudentSimulator(seed=123),
        max_steps_per_episode=100
    )
    
    print("   ✅ Simulator: 100 diverse students (30% beginner, 40% intermediate, 30% advanced)")
    print(f"   ✅ Curriculum: {num_topics} topics across {num_languages} languages (from final_curriculum.json)")
    print(f"   ✅ State space: {train_env.observation_space.shape[0]}D vector [LOCKED to current curriculum]")
    print(f"   ✅ Action space: {train_env.action_space.n} actions ({num_topics} topics × {len(train_env.difficulty_tiers)} difficulties)")
    print("   ✅ Training environment ready")
    print("   ✅ Evaluation environment ready")
    
    # Create DQN agent
    print("\n2. Creating DQN agent...")
    
    agent = DQNAgent(
        env=train_env,
        learning_rate=1e-4,
        buffer_size=50000,
        learning_starts=1000,
        batch_size=64,
        gamma=0.99,
        tensorboard_log="./tensorboard/dqn/",
        device=device
    )
    
    print("\n3. Starting training...")
    print("=" * 70)
    
    # Train
    start_time = time.time()
    
    agent.train(
        total_timesteps=timesteps,
        eval_env=eval_env,
        eval_freq=5000,
        save_path="./models/dqn/",
        checkpoint_freq=10000
    )
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 70)
    print("✅ DQN TRAINING COMPLETE!")
    print("=" * 70)
    print(f"\n📊 Training Summary:")
    print(f"   Total timesteps: {timesteps:,}")
    print(f"   Training time: {elapsed/60:.1f} minutes ({elapsed:.0f} seconds)")
    print(f"   Speed: {timesteps/elapsed:.1f} steps/second")
    print(f"\n💾 Saved Models:")
    print(f"   Final model: ./models/dqn/final_model.zip")
    print(f"   Best model: ./models/dqn/best/best_model.zip")
    print(f"   Checkpoints: ./models/dqn/checkpoints/")
    print(f"\n📈 Visualize Training:")
    print(f"   tensorboard --logdir=./tensorboard/dqn/")
    print(f"   Then open: http://localhost:6006")
    print("=" * 70)
    
    return agent


def train_a2c(timesteps: int = 100000, device: str = "auto"):
    """
    Train A2C agent (for comparison with PPO and DQN).
    
    Args:
        timesteps: Total training timesteps
        device: "cuda", "cpu", or "auto"
    
    Returns:
        Trained A2C agent
    """
    
    print("=" * 70)
    print("🤖 TRAINING A2C AGENT")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Algorithm: Advantage Actor-Critic (A2C)")
    print(f"  Timesteps: {timesteps:,}")
    print(f"  Device: {device}")
    print(f"  Expected episodes: ~{timesteps // 50:,} (50 steps/episode)")
    
    # Estimate training time
    if device == "cuda":
        estimated_minutes = timesteps / 1000 * 0.03  # A2C is fast
    else:
        estimated_minutes = timesteps / 1000 * 0.4
    
    print(f"  Estimated time: ~{estimated_minutes:.1f} minutes")
    print()
    
    # Create environments
    print("1. Initializing components...")
    
    config = get_config()
    num_topics = len(config.universal_mappings)
    num_languages = len(config.valid_languages)
    
    simulator = StudentSimulator(seed=42)
    
    train_env = AdaptiveLearningEnv(
        simulator=simulator,
        max_steps_per_episode=100
    )
    
    eval_env = AdaptiveLearningEnv(
        simulator=StudentSimulator(seed=123),
        max_steps_per_episode=100
    )
    
    print("   ✅ Simulator: 100 diverse students (30% beginner, 40% intermediate, 30% advanced)")
    print(f"   ✅ Curriculum: {num_topics} topics across {num_languages} languages (from final_curriculum.json)")
    print(f"   ✅ State space: {train_env.observation_space.shape[0]}D vector [LOCKED to current curriculum]")
    print(f"   ✅ Action space: {train_env.action_space.n} actions ({num_topics} topics × {len(train_env.difficulty_tiers)} difficulties)")
    print("   ✅ Training environment ready")
    print("   ✅ Evaluation environment ready")
    
    # Create A2C agent
    print("\n2. Creating A2C agent...")
    
    agent = A2CAgent(
        env=train_env,
        learning_rate=7e-4,
        n_steps=5,
        gamma=0.99,
        tensorboard_log="./tensorboard/a2c/",
        device=device
    )
    
    print("\n3. Starting training...")
    print("=" * 70)
    
    # Train
    start_time = time.time()
    
    agent.train(
        total_timesteps=timesteps,
        eval_env=eval_env,
        eval_freq=5000,
        save_path="./models/a2c/",
        checkpoint_freq=10000
    )
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 70)
    print("✅ A2C TRAINING COMPLETE!")
    print("=" * 70)
    print(f"\n📊 Training Summary:")
    print(f"   Total timesteps: {timesteps:,}")
    print(f"   Training time: {elapsed/60:.1f} minutes ({elapsed:.0f} seconds)")
    print(f"   Speed: {timesteps/elapsed:.1f} steps/second")
    print(f"\n💾 Saved Models:")
    print(f"   Final model: ./models/a2c/final_model.zip")
    print(f"   Best model: ./models/a2c/best/best_model.zip")
    print(f"   Checkpoints: ./models/a2c/checkpoints/")
    print(f"\n📈 Visualize Training:")
    print(f"   tensorboard --logdir=./tensorboard/a2c/")
    print(f"   Then open: http://localhost:6006")
    print("=" * 70)
    
    return agent


def main():
    """
    Main training pipeline with CLI arguments.
    """
    
    parser = argparse.ArgumentParser(
        description="Train RL agents for adaptive curriculum sequencing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full training (100K steps, ~3-5 minutes on GPU)
  python train_rl_model.py --algorithm ppo --timesteps 100000
  
  # Quick test (1K steps, ~2 seconds)
  python train_rl_model.py --algorithm ppo --timesteps 1000
  
  # Long training for best results (500K steps, ~20 minutes)
  python train_rl_model.py --algorithm ppo --timesteps 500000
  
  # Force CPU (if GPU has issues)
  python train_rl_model.py --algorithm ppo --device cpu
        """
    )
    
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["ppo", "dqn", "a2c", "all"],
        default="ppo",
        help="Which algorithm to train: ppo, dqn, a2c, or all (default: ppo)"
    )
    
    parser.add_argument(
        "--timesteps",
        type=int,
        default=500000,
        help="Number of training timesteps (default: 500000)"
    )
    
    parser.add_argument(
        "--device",
        type=str,
        choices=["cpu", "cuda", "auto"],
        default="auto",
        help="Device to use for training (default: auto)"
    )
    
    args = parser.parse_args()
    
    # Print header
    print("\n" + "=" * 70)
    print("PHASE 4: RL TRAINING PIPELINE")
    print("Adaptive Curriculum Sequencing via Reinforcement Learning")
    print("=" * 70)
    print(f"\nDate: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Algorithm: {args.algorithm.upper()}")
    print(f"Timesteps: {args.timesteps:,}")
    print(f"Device: {args.device}")
    print()
    
    # Create output directories
    print("Setting up directories...")
    Path("./models").mkdir(exist_ok=True)
    Path("./tensorboard").mkdir(exist_ok=True)
    print("✅ Directories ready\n")
    
    # Train based on algorithm choice
    if args.algorithm == "ppo":
        train_ppo(args.timesteps, args.device)
        
    elif args.algorithm == "dqn":
        train_dqn(args.timesteps, args.device)
        
    elif args.algorithm == "a2c":
        train_a2c(args.timesteps, args.device)
        
    elif args.algorithm == "all":
        print("🚀 Training all algorithms sequentially...\n")
        
        # Train PPO first
        train_ppo(args.timesteps, args.device)
        
        print("\n" + "=" * 70)
        print("Moving to next algorithm...")
        print("=" * 70 + "\n")
        
        # Train DQN
        train_dqn(args.timesteps, args.device)
        
        print("\n" + "=" * 70)
        print("Moving to next algorithm...")
        print("=" * 70 + "\n")
        
        # Train A2C
        train_a2c(args.timesteps, args.device)
        
        print("\n" + "=" * 70)
        print("✅ ALL ALGORITHMS TRAINED!")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Compare algorithms: python evaluate_all_agents.py --visualize")
        print("  2. View training logs: tensorboard --logdir=./tensorboard/")
        print("  3. Deploy best model to API (Component 6)")
        print("=" * 70)
    
    print("\n✅ Training pipeline complete!")
    print("\nYour trained model is ready for:")
    print("  → Component 5: Evaluation & Comparison")
    print("  → Component 6: API Integration")
    print("  → Thesis analysis and visualization\n")


if __name__ == "__main__":
    main()
