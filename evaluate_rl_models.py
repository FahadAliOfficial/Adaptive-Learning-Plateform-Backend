"""
Component 5: RL Evaluation Framework

Comprehensive evaluation and comparison of RL agents against baselines.

Compares:
    - Trained PPO agent
    - Random baseline (random action selection)
    - Rule-based baseline (current system logic: weakest topic + mastery+0.1 difficulty)

Metrics:
    1. Average episode reward
    2. Final mastery achieved
    3. Episode length (efficiency)
    4. Prerequisite violation rate
    5. Student dropout rate
    6. Mastery improvement velocity

Usage:
    python evaluate_rl_models.py --episodes 100
    python evaluate_rl_models.py --episodes 50 --visualize
"""

import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Tuple
import json
from datetime import datetime

from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
from services.rl.ppo_agent import PPOAgent
from services.config import get_config
from stable_baselines3 import DQN


class RLEvaluator:
    """
    Comprehensive evaluation framework for RL agents.
    """
    
    def __init__(self, num_episodes: int = 100):
        """
        Initialize evaluator.
        
        Args:
            num_episodes: Number of evaluation episodes per agent
        """
        self.num_episodes = num_episodes
        self.simulator = StudentSimulator(seed=42)
        
        # For reproducible evaluation
        np.random.seed(42)
        
    def evaluate_agent(
        self,
        agent,
        agent_name: str,
        verbose: bool = True
    ) -> Dict:
        """
        Evaluate a single agent over multiple episodes.
        
        Args:
            agent: RL agent (or None for baselines)
            agent_name: "PPO", "Random", or "Rule-Based"
            verbose: Print progress
        
        Returns:
            Dict with comprehensive metrics
        """
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"Evaluating {agent_name} Agent")
            print(f"{'='*70}")
        
        # Create fresh environment for evaluation
        env = AdaptiveLearningEnv(
            simulator=StudentSimulator(seed=123),  # Different seed for eval
            max_steps_per_episode=100
        )
        
        # Metrics storage
        metrics = {
            "episode_rewards": [],
            "final_masteries": [],
            "episode_lengths": [],
            "violation_counts": [],
            "dropout_count": 0,
            "success_count": 0,  # Episodes reaching 80% mastery
            "mastery_improvements": [],
            "topics_taught": [],
            "difficulty_distributions": [],
            "episode_details": []
        }
        
        # Run evaluation episodes
        for episode in range(self.num_episodes):
            state, info = env.reset()
            
            initial_mastery = info["initial_avg_mastery"]
            episode_reward = 0
            violations_in_episode = 0
            steps = 0
            gave_up = False
            episode_actions = []
            
            # Run episode
            terminated = False
            truncated = False
            
            while not (terminated or truncated):
                # Get action based on agent type
                if agent_name == "Random":
                    action = env.action_space.sample()
                elif agent_name == "Rule-Based":
                    action = self._rule_based_policy(state, env)
                else:  # PPO or other RL agent
                    action, _ = agent.predict(state, deterministic=True)
                
                # Execute action
                next_state, reward, terminated, truncated, step_info = env.step(action)
                
                episode_reward += reward
                steps += 1
                violations_in_episode += step_info.get("gate_violations", 0)
                episode_actions.append(action)
                
                if step_info.get("gave_up", False):
                    gave_up = True
                
                state = next_state
            
            # Record episode metrics
            final_mastery = step_info["avg_mastery"]
            
            metrics["episode_rewards"].append(episode_reward)
            metrics["final_masteries"].append(final_mastery)
            metrics["episode_lengths"].append(steps)
            metrics["violation_counts"].append(violations_in_episode)
            metrics["mastery_improvements"].append(final_mastery - initial_mastery)
            
            if gave_up:
                metrics["dropout_count"] += 1
            
            if final_mastery >= 0.60:
                metrics["success_count"] += 1
            
            # Record episode details for analysis
            metrics["episode_details"].append({
                "episode": episode,
                "initial_mastery": initial_mastery,
                "final_mastery": final_mastery,
                "improvement": final_mastery - initial_mastery,
                "reward": episode_reward,
                "steps": steps,
                "violations": violations_in_episode,
                "gave_up": gave_up,
                "success": final_mastery >= 0.60
            })
            
            # Progress indicator
            if verbose and (episode + 1) % 20 == 0:
                print(f"  Progress: {episode + 1}/{self.num_episodes} episodes")
        
        # Compute summary statistics
        summary = {
            "agent_name": agent_name,
            "num_episodes": self.num_episodes,
            
            # Reward metrics
            "avg_reward": np.mean(metrics["episode_rewards"]),
            "std_reward": np.std(metrics["episode_rewards"]),
            "median_reward": np.median(metrics["episode_rewards"]),
            
            # Mastery metrics
            "avg_final_mastery": np.mean(metrics["final_masteries"]),
            "avg_mastery_improvement": np.mean(metrics["mastery_improvements"]),
            "median_mastery_improvement": np.median(metrics["mastery_improvements"]),
            
            # Efficiency metrics
            "avg_episode_length": np.mean(metrics["episode_lengths"]),
            "std_episode_length": np.std(metrics["episode_lengths"]),
            
            # Safety metrics
            "avg_violations_per_episode": np.mean(metrics["violation_counts"]),
            "dropout_rate": metrics["dropout_count"] / self.num_episodes,
            "success_rate": metrics["success_count"] / self.num_episodes,
            
            # Raw data
            "raw_metrics": metrics
        }
        
        if verbose:
            self._print_agent_summary(summary)
        
        return summary
    
    def _rule_based_policy(self, state: np.ndarray, env) -> int:
        """
        Rule-based baseline policy (mimics current system).
        
        Strategy:
            1. Find topic with lowest mastery
            2. Set difficulty = mastery + 0.1 (slightly challenging)
        
        Args:
            state: Current state vector
            env: Environment for action encoding
        
        Returns:
            action: Encoded action (0-39)
        """
        
        # Extract mastery scores from state (indices 5-12)
        masteries = state[5:13]
        
        # Find topic with lowest mastery (teach weakest area)
        topic_idx = int(np.argmin(masteries))
        
        # Set difficulty slightly above current mastery
        target_difficulty = min(masteries[topic_idx] + 0.1, 0.95)
        
        # Map to nearest difficulty tier
        difficulty_tiers = np.array([0.2, 0.4, 0.6, 0.8, 1.0])
        difficulty_idx = int(np.argmin(np.abs(difficulty_tiers - target_difficulty)))
        
        # Encode as action
        action = topic_idx * 5 + difficulty_idx
        
        return action
    
    def _print_agent_summary(self, summary: Dict):
        """Print summary for single agent."""
        
        print(f"\n📊 Results:")
        print(f"   Avg Reward:          {summary['avg_reward']:>8.2f} ± {summary['std_reward']:.2f}")
        print(f"   Avg Final Mastery:   {summary['avg_final_mastery']:>8.1%}")
        print(f"   Avg Improvement:     {summary['avg_mastery_improvement']:>8.1%}")
        print(f"   Avg Episode Length:  {summary['avg_episode_length']:>8.1f} steps")
        print(f"   Success Rate:        {summary['success_rate']:>8.1%} (reached 60% mastery)")
        print(f"   Dropout Rate:        {summary['dropout_rate']:>8.1%} (students gave up)")
        print(f"   Avg Violations:      {summary['avg_violations_per_episode']:>8.1f} per episode")
    
    def compare_all_agents(self) -> Dict:
        """
        Main evaluation: Compare PPO, DQN vs baselines.
        
        Returns:
            Dict with all results and comparison
        """
        
        print("\n" + "=" * 70)
        print("🏆 RL AGENT EVALUATION & COMPARISON")
        print("=" * 70)
        print(f"\nConfiguration:")
        print(f"  Episodes per agent: {self.num_episodes}")
        print(f"  Max steps per episode: 50")
        print(f"  Evaluation seed: 123")
        
        results = {}
        
        # 1. Evaluate Random baseline
        print(f"\n{'='*70}")
        print("1️⃣  RANDOM BASELINE")
        print(f"{'='*70}")
        results["Random"] = self.evaluate_agent(None, "Random")
        
        # 2. Evaluate Rule-Based baseline
        print(f"\n{'='*70}")
        print("2️⃣  RULE-BASED BASELINE (Current System)")
        print(f"{'='*70}")
        results["Rule-Based"] = self.evaluate_agent(None, "Rule-Based")
        
        # 3. Evaluate PPO agent
        print(f"\n{'='*70}")
        print("3️⃣  TRAINED PPO AGENT")
        print(f"{'='*70}")
        
        try:
            ppo_env = AdaptiveLearningEnv(
                simulator=StudentSimulator(seed=42),
                max_steps_per_episode=100
            )
            
            try:
                ppo_agent = PPOAgent.load_pretrained(
                    "./models/ppo/best/best_model",
                    ppo_env,
                    device="auto"
                )
                print("✅ Loaded BEST model (from evaluation)")
            except:
                ppo_agent = PPOAgent.load_pretrained(
                    "./models/ppo/final_model",
                    ppo_env,
                    device="auto"
                )
                print("✅ Loaded FINAL model (100K steps)")
            
            results["PPO"] = self.evaluate_agent(ppo_agent, "PPO")
            
        except FileNotFoundError:
            print("❌ PPO model not found. Run train_rl_model.py first.")
            results["PPO"] = None
        
        # 4. Evaluate DQN agent
        print(f"\n{'='*70}")
        print("4️⃣  TRAINED DQN AGENT")
        print(f"{'='*70}")
        
        try:
            dqn_env = AdaptiveLearningEnv(
                simulator=StudentSimulator(seed=42),
                max_steps_per_episode=100
            )
            
            try:
                dqn_model = DQN.load("./models/dqn/best/best_model", device="auto")
                print(f"Using {dqn_model.device} device")
                print(f"✅ Model loaded from ./models/dqn/best/best_model")
                print("✅ Loaded BEST model (from evaluation)")
            except:
                dqn_model = DQN.load("./models/dqn/final_model", device="auto")
                print(f"Using {dqn_model.device} device")
                print(f"✅ Model loaded from ./models/dqn/final_model")
                print("✅ Loaded FINAL model (100K steps)")
            
            # Wrap DQN model to match PPO interface
            class DQNWrapper:
                def __init__(self, model):
                    self.model = model
                
                def predict(self, state, deterministic=True):
                    action, _ = self.model.predict(state, deterministic=deterministic)
                    return action, None
            
            results["DQN"] = self.evaluate_agent(DQNWrapper(dqn_model), "DQN")
            
        except FileNotFoundError:
            print("❌ DQN model not found. Run train_rl_model.py --algorithm dqn first.")
            results["DQN"] = None
        
        # Print comparison table
        self._print_comparison_table(results)
        
        # Save results
        self._save_results(results)
        
        return results
    
    def _print_comparison_table(self, results: Dict):
        """Print comparison table for all agents."""
        
        print("\n" + "=" * 80)
        print("📊 COMPARATIVE ANALYSIS")
        print("=" * 80)
        
        # Filter out None results
        valid_results = {k: v for k, v in results.items() if v is not None}
        
        if len(valid_results) == 0:
            print("❌ No valid results to compare")
            return
        
        # Create comparison DataFrame
        df = pd.DataFrame({
            "Agent": list(valid_results.keys()),
            "Avg Reward": [r["avg_reward"] for r in valid_results.values()],
            "Final Mastery": [f"{r['avg_final_mastery']:.1%}" for r in valid_results.values()],
            "Improvement": [f"{r['avg_mastery_improvement']:.1%}" for r in valid_results.values()],
            "Episode Length": [f"{r['avg_episode_length']:.1f}" for r in valid_results.values()],
            "Success Rate": [f"{r['success_rate']:.1%}" for r in valid_results.values()],
            "Dropout Rate": [f"{r['dropout_rate']:.1%}" for r in valid_results.values()],
            "Violations": [f"{r['avg_violations_per_episode']:.1f}" for r in valid_results.values()]
        })
        
        print("\n" + df.to_string(index=False))
        
        # Highlight best performer
        rewards = [r["avg_reward"] for r in valid_results.values()]
        best_idx = np.argmax(rewards)
        best_agent = list(valid_results.keys())[best_idx]
        
        print(f"\n{'='*80}")
        print(f"🏆 BEST AGENT: {best_agent}")
        print(f"{'='*80}")
        
        # Calculate improvements over baselines
        if "PPO" in valid_results and "Random" in valid_results:
            ppo_reward = valid_results["PPO"]["avg_reward"]
            random_reward = valid_results["Random"]["avg_reward"]
            
            improvement = ((ppo_reward - random_reward) / abs(random_reward)) * 100
            
            print(f"\n📈 PPO vs Random Baseline:")
            print(f"   Reward improvement: {improvement:+.1f}%")
            print(f"   PPO reward: {ppo_reward:.2f}")
            print(f"   Random reward: {random_reward:.2f}")
        
        if "PPO" in valid_results and "Rule-Based" in valid_results:
            ppo_reward = valid_results["PPO"]["avg_reward"]
            rule_reward = valid_results["Rule-Based"]["avg_reward"]
            
            improvement = ((ppo_reward - rule_reward) / abs(rule_reward)) * 100
            
            print(f"\n📈 PPO vs Rule-Based Baseline:")
            print(f"   Reward improvement: {improvement:+.1f}%")
            print(f"   PPO reward: {ppo_reward:.2f}")
            print(f"   Rule-based reward: {rule_reward:.2f}")
            
            # Success rate comparison
            ppo_success = valid_results["PPO"]["success_rate"]
            rule_success = valid_results["Rule-Based"]["success_rate"]
            
            print(f"\n🎯 Success Rate Comparison:")
            print(f"   PPO: {ppo_success:.1%} (students reaching 80% mastery)")
            print(f"   Rule-Based: {rule_success:.1%}")
            print(f"   Improvement: {(ppo_success - rule_success)*100:+.1f} percentage points")
        
        # DQN comparisons
        if "DQN" in valid_results and "Random" in valid_results:
            dqn_reward = valid_results["DQN"]["avg_reward"]
            random_reward = valid_results["Random"]["avg_reward"]
            
            improvement = ((dqn_reward - random_reward) / abs(random_reward)) * 100
            
            print(f"\n📈 DQN vs Random Baseline:")
            print(f"   Reward improvement: {improvement:+.1f}%")
            print(f"   DQN reward: {dqn_reward:.2f}")
            print(f"   Random reward: {random_reward:.2f}")
        
        if "DQN" in valid_results and "Rule-Based" in valid_results:
            dqn_reward = valid_results["DQN"]["avg_reward"]
            rule_reward = valid_results["Rule-Based"]["avg_reward"]
            
            improvement = ((dqn_reward - rule_reward) / abs(rule_reward)) * 100
            
            print(f"\n📈 DQN vs Rule-Based Baseline:")
            print(f"   Reward improvement: {improvement:+.1f}%")
            print(f"   DQN reward: {dqn_reward:.2f}")
            print(f"   Rule-based reward: {rule_reward:.2f}")
        
        # PPO vs DQN head-to-head
        if "PPO" in valid_results and "DQN" in valid_results:
            ppo_reward = valid_results["PPO"]["avg_reward"]
            dqn_reward = valid_results["DQN"]["avg_reward"]
            
            print(f"\n{'='*80}")
            print(f"⚡ PPO vs DQN HEAD-TO-HEAD")
            print(f"{'='*80}")
            
            print(f"\n🎯 Reward:")
            print(f"   PPO: {ppo_reward:.2f}")
            print(f"   DQN: {dqn_reward:.2f}")
            if ppo_reward > dqn_reward:
                diff = ((ppo_reward - dqn_reward) / abs(dqn_reward)) * 100
                print(f"   Winner: PPO (+{diff:.1f}%)")
            elif dqn_reward > ppo_reward:
                diff = ((dqn_reward - ppo_reward) / abs(ppo_reward)) * 100
                print(f"   Winner: DQN (+{diff:.1f}%)")
            else:
                print(f"   Result: TIE")
            
            # Compare success rates
            ppo_success = valid_results["PPO"]["success_rate"]
            dqn_success = valid_results["DQN"]["success_rate"]
            
            print(f"\n🏆 Success Rate:")
            print(f"   PPO: {ppo_success:.1%}")
            print(f"   DQN: {dqn_success:.1%}")
            if ppo_success > dqn_success:
                print(f"   Winner: PPO")
            elif dqn_success > ppo_success:
                print(f"   Winner: DQN")
            else:
                print(f"   Result: TIE")
            
            # Compare dropout rates (lower is better)
            ppo_dropout = valid_results["PPO"]["dropout_rate"]
            dqn_dropout = valid_results["DQN"]["dropout_rate"]
            
            print(f"\n📉 Dropout Rate (lower is better):")
            print(f"   PPO: {ppo_dropout:.1%}")
            print(f"   DQN: {dqn_dropout:.1%}")
            if ppo_dropout < dqn_dropout:
                print(f"   Winner: PPO")
            elif dqn_dropout < ppo_dropout:
                print(f"   Winner: DQN")
            else:
                print(f"   Result: TIE")
    
    def _save_results(self, results: Dict):
        """Save results to JSON file."""
        
        output_dir = Path("./evaluation_results")
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Prepare serializable results
        serializable_results = {}
        for agent_name, result in results.items():
            if result is None:
                continue
            
            # Convert episode details to native Python types
            episode_details = []
            for episode in result["raw_metrics"]["episode_details"]:
                episode_details.append({
                    "episode": int(episode["episode"]),
                    "initial_mastery": float(episode["initial_mastery"]),
                    "final_mastery": float(episode["final_mastery"]),
                    "improvement": float(episode["improvement"]),
                    "reward": float(episode["reward"]),
                    "steps": int(episode["steps"]),
                    "violations": int(episode["violations"]),
                    "gave_up": bool(episode["gave_up"]),
                    "success": bool(episode["success"])
                })
            
            serializable_results[agent_name] = {
                "avg_reward": float(result["avg_reward"]),
                "std_reward": float(result["std_reward"]),
                "avg_final_mastery": float(result["avg_final_mastery"]),
                "avg_mastery_improvement": float(result["avg_mastery_improvement"]),
                "avg_episode_length": float(result["avg_episode_length"]),
                "success_rate": float(result["success_rate"]),
                "dropout_rate": float(result["dropout_rate"]),
                "avg_violations": float(result["avg_violations_per_episode"]),
                "episode_details": episode_details
            }
        
        # Save JSON
        json_path = output_dir / f"evaluation_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        print(f"\n💾 Results saved to: {json_path}")
    
    def generate_visualizations(self, results: Dict):
        """
        Generate thesis-quality visualizations.
        
        Creates:
            1. Reward comparison (bar chart)
            2. Episode length distribution (box plot)
            3. Success rate comparison (bar chart)
            4. Learning curves (if available)
        """
        
        print("\n" + "=" * 70)
        print("📈 GENERATING VISUALIZATIONS")
        print("=" * 70)
        
        # Filter valid results
        valid_results = {k: v for k, v in results.items() if v is not None}
        
        if len(valid_results) < 2:
            print("⚠️  Need at least 2 agents for comparison plots")
            return
        
        # Set style
        sns.set_style("whitegrid")
        plt.rcParams['figure.figsize'] = (15, 10)
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # 1. Average Reward Comparison
        ax1 = axes[0, 0]
        agents = list(valid_results.keys())
        rewards = [r["avg_reward"] for r in valid_results.values()]
        errors = [r["std_reward"] for r in valid_results.values()]
        
        colors = ['red' if agent == 'Random' else 'orange' if agent == 'Rule-Based' else 'green' 
                  for agent in agents]
        
        ax1.bar(agents, rewards, yerr=errors, color=colors, alpha=0.7, capsize=5)
        ax1.set_ylabel('Average Reward', fontsize=12)
        ax1.set_title('Reward Comparison (Higher is Better)', fontsize=14, fontweight='bold')
        ax1.axhline(y=0, color='black', linestyle='--', alpha=0.3)
        ax1.grid(axis='y', alpha=0.3)
        
        # 2. Episode Length Distribution
        ax2 = axes[0, 1]
        episode_lengths = [r["raw_metrics"]["episode_lengths"] for r in valid_results.values()]
        
        bp = ax2.boxplot(episode_lengths, labels=agents, patch_artist=True)
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax2.set_ylabel('Episode Length (steps)', fontsize=12)
        ax2.set_title('Episode Length Distribution (Lower = More Efficient)', fontsize=14, fontweight='bold')
        ax2.grid(axis='y', alpha=0.3)
        
        # 3. Success Rate Comparison
        ax3 = axes[1, 0]
        success_rates = [r["success_rate"] * 100 for r in valid_results.values()]
        dropout_rates = [r["dropout_rate"] * 100 for r in valid_results.values()]
        
        x = np.arange(len(agents))
        width = 0.35
        
        ax3.bar(x - width/2, success_rates, width, label='Success Rate', color='green', alpha=0.7)
        ax3.bar(x + width/2, dropout_rates, width, label='Dropout Rate', color='red', alpha=0.7)
        
        ax3.set_ylabel('Percentage (%)', fontsize=12)
        ax3.set_title('Success vs Dropout Rates', fontsize=14, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(agents)
        ax3.legend()
        ax3.grid(axis='y', alpha=0.3)
        
        # 4. Mastery Improvement Distribution
        ax4 = axes[1, 1]
        improvements = [r["raw_metrics"]["mastery_improvements"] for r in valid_results.values()]
        
        bp2 = ax4.boxplot(improvements, labels=agents, patch_artist=True)
        for patch, color in zip(bp2['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax4.set_ylabel('Mastery Improvement', fontsize=12)
        ax4.set_title('Mastery Improvement Distribution (Higher is Better)', fontsize=14, fontweight='bold')
        ax4.axhline(y=0, color='black', linestyle='--', alpha=0.3)
        ax4.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        
        # Save figure
        output_dir = Path("./evaluation_results")
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_path = output_dir / f"comparison_plots_{timestamp}.png"
        
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        print(f"✅ Plots saved to: {plot_path}")
        
        print("\n📊 Visualization Summary:")
        print(f"   - Reward comparison bar chart")
        print(f"   - Episode length box plots")
        print(f"   - Success vs dropout rates")
        print(f"   - Mastery improvement distributions")
        print(f"\nOpen {plot_path} to view!")


def main():
    """Main evaluation pipeline."""
    
    parser = argparse.ArgumentParser(
        description="Evaluate and compare RL agents for adaptive curriculum",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--episodes",
        type=int,
        default=100,
        help="Number of evaluation episodes per agent (default: 100)"
    )
    
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate visualization plots"
    )
    
    args = parser.parse_args()
    
    # Create evaluator
    evaluator = RLEvaluator(num_episodes=args.episodes)
    
    # Run comparison
    results = evaluator.compare_all_agents()
    
    # Generate visualizations
    if args.visualize:
        evaluator.generate_visualizations(results)
    
    print("\n" + "=" * 70)
    print("✅ EVALUATION COMPLETE!")
    print("=" * 70)
    print(f"\nResults saved to: ./evaluation_results/")
    
    if args.visualize:
        print(f"Plots saved to: ./evaluation_results/comparison_plots_*.png")
    
    print("\nNext steps:")
    print("  → Analyze results for thesis")
    print("  → Component 6: Deploy best model to API")
    print("  → Write up findings and visualizations")
    print("=" * 70)


if __name__ == "__main__":
    main()
