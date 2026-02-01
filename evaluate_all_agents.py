"""
Comprehensive RL Agent Evaluation Framework

Evaluates and compares ALL RL agents against baselines:
    - PPO (Proximal Policy Optimization)
    - DQN (Deep Q-Network)
    - A2C (Advantage Actor-Critic)
    - Random baseline
    - Rule-based baseline (current system logic)

Metrics:
    1. Average episode reward
    2. Final mastery achieved
    3. Mastery improvement (learning effectiveness)
    4. Episode length (efficiency)
    5. Prerequisite violation rate (curriculum safety)
    6. Student dropout rate (retention)
    7. Success rate (reaching 60% mastery)

Usage:
    python evaluate_all_agents.py --episodes 100
    python evaluate_all_agents.py --episodes 50 --visualize
    python evaluate_all_agents.py --agents ppo dqn --episodes 100
"""

import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
from datetime import datetime

from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
from services.rl.ppo_agent import PPOAgent
from services.rl.dqn_agent import DQNAgent
from services.rl.a2c_agent import A2CAgent
from services.config import get_config
from stable_baselines3 import PPO, DQN, A2C


class ComprehensiveEvaluator:
    """
    Comprehensive evaluation framework for all RL agents.
    
    Supports PPO, DQN, A2C, and baseline comparisons with
    detailed metrics and visualizations.
    """
    
    def __init__(self, num_episodes: int = 100, seed: int = 123):
        """
        Initialize evaluator.
        
        Args:
            num_episodes: Number of evaluation episodes per agent
            seed: Random seed for reproducibility
        """
        self.num_episodes = num_episodes
        self.seed = seed
        self.simulator = StudentSimulator(seed=seed)
        
        # For reproducible evaluation
        np.random.seed(seed)
        
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
            agent_name: Agent identifier
            verbose: Print progress
        
        Returns:
            Dict with comprehensive metrics
        """
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"Evaluating {agent_name} Agent")
            print(f"{'='*70}")
        
        # Create fresh environment for evaluation
        # Use consistent seed for fair comparison across all agents
        env = AdaptiveLearningEnv(
            simulator=StudentSimulator(seed=self.seed),
            max_steps_per_episode=100
        )
        
        # Metrics storage
        metrics = {
            "episode_rewards": [],
            "final_masteries": [],
            "episode_lengths": [],
            "violation_counts": [],
            "dropout_count": 0,
            "success_count": 0,
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
                else:  # PPO, DQN, A2C or other RL agent
                    # Validate state dimensions
                    if len(state) != env.observation_space.shape[0]:
                        raise ValueError(
                            f"State dimension mismatch! Expected {env.observation_space.shape[0]}, "
                            f"got {len(state)}. Model may be incompatible with current curriculum."
                        )
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
            "min_reward": np.min(metrics["episode_rewards"]),
            "max_reward": np.max(metrics["episode_rewards"]),
            
            # Mastery metrics
            "avg_final_mastery": np.mean(metrics["final_masteries"]),
            "std_final_mastery": np.std(metrics["final_masteries"]),
            "avg_mastery_improvement": np.mean(metrics["mastery_improvements"]),
            "std_mastery_improvement": np.std(metrics["mastery_improvements"]),
            "median_mastery_improvement": np.median(metrics["mastery_improvements"]),
            
            # Efficiency metrics
            "avg_episode_length": np.mean(metrics["episode_lengths"]),
            "std_episode_length": np.std(metrics["episode_lengths"]),
            
            # Safety metrics
            "total_violations": sum(metrics["violation_counts"]),
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
        """
        # Extract mastery scores from state (indices 5-12)
        masteries = state[5:13]
        
        # Find topic with lowest mastery
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
        print(f"   Avg Improvement:     {summary['avg_mastery_improvement']:>+8.1%}")
        print(f"   Avg Episode Length:  {summary['avg_episode_length']:>8.1f} steps")
        print(f"   Success Rate:        {summary['success_rate']:>8.1%} (reached 60% mastery)")
        print(f"   Dropout Rate:        {summary['dropout_rate']:>8.1%} (students gave up)")
        print(f"   Total Violations:    {summary['total_violations']:>8d}")
    
    def _load_agent(self, agent_type: str, env) -> Optional[object]:
        """
        Load a trained agent by type.
        
        Args:
            agent_type: 'ppo', 'dqn', or 'a2c'
            env: Environment for the agent
        
        Returns:
            Loaded agent or None if not found
        """
        agent_type = agent_type.lower()
        
        try:
            if agent_type == "ppo":
                try:
                    agent = PPO.load(f"./models/ppo/best/best_model", device="auto")
                    print(f"✅ Loaded PPO BEST model")
                except:
                    agent = PPO.load(f"./models/ppo/final_model", device="auto")
                    print(f"✅ Loaded PPO FINAL model")
                return agent
                
            elif agent_type == "dqn":
                try:
                    agent = DQN.load(f"./models/dqn/best/best_model", device="auto")
                    print(f"✅ Loaded DQN BEST model")
                except:
                    agent = DQN.load(f"./models/dqn/final_model", device="auto")
                    print(f"✅ Loaded DQN FINAL model")
                return agent
                
            elif agent_type == "a2c":
                try:
                    agent = A2C.load(f"./models/a2c/best/best_model", device="auto")
                    print(f"✅ Loaded A2C BEST model")
                except:
                    agent = A2C.load(f"./models/a2c/final_model", device="auto")
                    print(f"✅ Loaded A2C FINAL model")
                return agent
                
        except Exception as e:
            print(f"❌ {agent_type.upper()} model not found: {e}")
            return None
    
    def compare_all_agents(self, agents: List[str] = None) -> Dict:
        """
        Main evaluation: Compare specified agents vs baselines.
        
        Args:
            agents: List of agent types to evaluate ['ppo', 'dqn', 'a2c']
                   If None, evaluates all available agents
        
        Returns:
            Dict with all results and comparison
        """
        
        if agents is None:
            agents = ['ppo', 'dqn', 'a2c']
        
        print("\n" + "=" * 70)
        print("🏆 COMPREHENSIVE RL AGENT EVALUATION")
        print("=" * 70)
        print(f"\nConfiguration:")
        print(f"  Episodes per agent: {self.num_episodes}")
        print(f"  Max steps per episode: 100")
        print(f"  Evaluation seed: {self.seed}")
        print(f"  Agents to evaluate: {', '.join(agents)}")
        
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
        
        # 3. Evaluate requested RL agents
        agent_counter = 3
        
        # Create shared environment for loading models (seed doesn't matter for loading)
        load_env = AdaptiveLearningEnv(
            simulator=StudentSimulator(seed=42),
            max_steps_per_episode=100
        )
        
        for agent_type in agents:
            print(f"\n{'='*70}")
            print(f"{agent_counter}️⃣  TRAINED {agent_type.upper()} AGENT")
            print(f"{'='*70}")
            
            agent = self._load_agent(agent_type, load_env)
            
            if agent is not None:
                results[agent_type.upper()] = self.evaluate_agent(agent, agent_type.upper())
            else:
                results[agent_type.upper()] = None
            
            agent_counter += 1
        
        # Print comparison table
        self._print_comparison_table(results)
        
        # Save results
        self._save_results(results)
        
        return results
    
    def _print_comparison_table(self, results: Dict):
        """Print comparison table for all agents."""
        
        print("\n" + "=" * 90)
        print("📊 COMPARATIVE ANALYSIS")
        print("=" * 90)
        
        # Filter out None results
        valid_results = {k: v for k, v in results.items() if v is not None}
        
        if len(valid_results) == 0:
            print("❌ No valid results to compare")
            return
        
        # Create comparison DataFrame
        df = pd.DataFrame({
            "Agent": list(valid_results.keys()),
            "Avg Reward": [f"{r['avg_reward']:.2f}" for r in valid_results.values()],
            "Final Mastery": [f"{r['avg_final_mastery']:.1%}" for r in valid_results.values()],
            "Improvement": [f"{r['avg_mastery_improvement']:+.1%}" for r in valid_results.values()],
            "Episode Len": [f"{r['avg_episode_length']:.1f}" for r in valid_results.values()],
            "Success %": [f"{r['success_rate']:.1%}" for r in valid_results.values()],
            "Dropout %": [f"{r['dropout_rate']:.1%}" for r in valid_results.values()],
            "Violations": [f"{r['total_violations']}" for r in valid_results.values()]
        })
        
        print("\n" + df.to_string(index=False))
        
        # Find best performer by different metrics
        print(f"\n{'='*90}")
        print("🏆 BEST PERFORMERS BY METRIC")
        print(f"{'='*90}")
        
        # Best by reward
        rewards = {k: v["avg_reward"] for k, v in valid_results.items()}
        best_reward = max(rewards, key=rewards.get)
        print(f"   📈 Highest Reward: {best_reward} ({rewards[best_reward]:.2f})")
        
        # Best by improvement
        improvements = {k: v["avg_mastery_improvement"] for k, v in valid_results.items()}
        best_improvement = max(improvements, key=improvements.get)
        print(f"   📚 Best Learning: {best_improvement} ({improvements[best_improvement]:+.1%})")
        
        # Best by success rate
        success_rates = {k: v["success_rate"] for k, v in valid_results.items()}
        best_success = max(success_rates, key=success_rates.get)
        print(f"   ✅ Highest Success: {best_success} ({success_rates[best_success]:.1%})")
        
        # Best by safety (lowest violations)
        violations = {k: v["total_violations"] for k, v in valid_results.items()}
        best_safety = min(violations, key=violations.get)
        print(f"   🛡️ Safest (fewest violations): {best_safety} ({violations[best_safety]})")
        
        # RL vs Baselines comparison
        rl_agents = [k for k in valid_results.keys() if k not in ["Random", "Rule-Based"]]
        
        if rl_agents and "Rule-Based" in valid_results:
            print(f"\n{'='*90}")
            print("📈 RL AGENTS vs RULE-BASED BASELINE")
            print(f"{'='*90}")
            
            rule_improvement = valid_results["Rule-Based"]["avg_mastery_improvement"]
            
            for agent in rl_agents:
                agent_improvement = valid_results[agent]["avg_mastery_improvement"]
                diff = agent_improvement - rule_improvement
                
                if diff > 0:
                    symbol = "✅"
                    comparison = "BETTER"
                elif diff < 0:
                    symbol = "❌"
                    comparison = "WORSE"
                else:
                    symbol = "➖"
                    comparison = "SAME"
                
                print(f"   {symbol} {agent}: {agent_improvement:+.1%} vs {rule_improvement:+.1%} ({comparison}, diff: {diff:+.1%})")
    
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
                "total_violations": int(result["total_violations"]),
                "avg_violations": float(result["avg_violations_per_episode"]),
                "episode_details": episode_details
            }
        
        # Save JSON
        json_path = output_dir / f"comprehensive_eval_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        print(f"\n💾 Results saved to: {json_path}")
    
    def generate_visualizations(self, results: Dict):
        """
        Generate thesis-quality visualizations.
        
        Creates:
            1. Reward comparison (bar chart with error bars)
            2. Mastery improvement distribution (box plot)
            3. Success vs Dropout rates (grouped bar)
            4. Episode length distribution (violin plot)
            5. Learning progression (if available)
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
        plt.rcParams['figure.figsize'] = (16, 12)
        plt.rcParams['font.size'] = 10
        
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        agents = list(valid_results.keys())
        
        # Color scheme
        color_map = {
            'Random': '#E74C3C',      # Red
            'Rule-Based': '#F39C12',  # Orange
            'PPO': '#27AE60',         # Green
            'DQN': '#3498DB',         # Blue
            'A2C': '#9B59B6'          # Purple
        }
        colors = [color_map.get(a, '#95A5A6') for a in agents]
        
        # 1. Average Reward Comparison
        ax1 = axes[0, 0]
        rewards = [r["avg_reward"] for r in valid_results.values()]
        errors = [r["std_reward"] for r in valid_results.values()]
        
        bars = ax1.bar(agents, rewards, yerr=errors, color=colors, alpha=0.8, capsize=5)
        ax1.set_ylabel('Average Reward', fontsize=12)
        ax1.set_title('Reward Comparison', fontsize=14, fontweight='bold')
        ax1.axhline(y=0, color='black', linestyle='--', alpha=0.3)
        ax1.grid(axis='y', alpha=0.3)
        ax1.tick_params(axis='x', rotation=45)
        
        # Add value labels
        for bar, val in zip(bars, rewards):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                    f'{val:.1f}', ha='center', va='bottom', fontsize=9)
        
        # 2. Mastery Improvement Distribution
        ax2 = axes[0, 1]
        improvements = [np.array(r["raw_metrics"]["mastery_improvements"]) * 100 
                       for r in valid_results.values()]
        
        bp = ax2.boxplot(improvements, labels=agents, patch_artist=True)
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax2.set_ylabel('Mastery Improvement (%)', fontsize=12)
        ax2.set_title('Learning Effectiveness', fontsize=14, fontweight='bold')
        ax2.axhline(y=0, color='black', linestyle='--', alpha=0.3)
        ax2.grid(axis='y', alpha=0.3)
        ax2.tick_params(axis='x', rotation=45)
        
        # 3. Success vs Dropout Rates
        ax3 = axes[0, 2]
        success_rates = [r["success_rate"] * 100 for r in valid_results.values()]
        dropout_rates = [r["dropout_rate"] * 100 for r in valid_results.values()]
        
        x = np.arange(len(agents))
        width = 0.35
        
        bars1 = ax3.bar(x - width/2, success_rates, width, label='Success Rate', 
                       color='#27AE60', alpha=0.8)
        bars2 = ax3.bar(x + width/2, dropout_rates, width, label='Dropout Rate', 
                       color='#E74C3C', alpha=0.8)
        
        ax3.set_ylabel('Percentage (%)', fontsize=12)
        ax3.set_title('Success vs Dropout Rates', fontsize=14, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(agents, rotation=45)
        ax3.legend()
        ax3.grid(axis='y', alpha=0.3)
        
        # 4. Episode Length Distribution
        ax4 = axes[1, 0]
        episode_lengths = [r["raw_metrics"]["episode_lengths"] for r in valid_results.values()]
        
        parts = ax4.violinplot(episode_lengths, positions=range(len(agents)), 
                              showmeans=True, showmedians=True)
        
        for i, pc in enumerate(parts['bodies']):
            pc.set_facecolor(colors[i])
            pc.set_alpha(0.7)
        
        ax4.set_xticks(range(len(agents)))
        ax4.set_xticklabels(agents, rotation=45)
        ax4.set_ylabel('Episode Length (steps)', fontsize=12)
        ax4.set_title('Episode Length Distribution', fontsize=14, fontweight='bold')
        ax4.grid(axis='y', alpha=0.3)
        
        # 5. Final Mastery Distribution
        ax5 = axes[1, 1]
        final_masteries = [np.array(r["raw_metrics"]["final_masteries"]) * 100 
                         for r in valid_results.values()]
        
        bp2 = ax5.boxplot(final_masteries, labels=agents, patch_artist=True)
        for patch, color in zip(bp2['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax5.set_ylabel('Final Mastery (%)', fontsize=12)
        ax5.set_title('Final Mastery Achievement', fontsize=14, fontweight='bold')
        ax5.axhline(y=60, color='green', linestyle='--', alpha=0.5, label='60% threshold')
        ax5.grid(axis='y', alpha=0.3)
        ax5.tick_params(axis='x', rotation=45)
        ax5.legend()
        
        # 6. Violations Comparison
        ax6 = axes[1, 2]
        violations = [r["total_violations"] for r in valid_results.values()]
        
        bars = ax6.bar(agents, violations, color=colors, alpha=0.8)
        ax6.set_ylabel('Total Violations', fontsize=12)
        ax6.set_title('Curriculum Safety (Lower = Better)', fontsize=14, fontweight='bold')
        ax6.grid(axis='y', alpha=0.3)
        ax6.tick_params(axis='x', rotation=45)
        
        # Add value labels
        for bar, val in zip(bars, violations):
            ax6.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, 
                    f'{val}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        
        # Save figure
        output_dir = Path("./evaluation_results")
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_path = output_dir / f"comprehensive_comparison_{timestamp}.png"
        
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        print(f"✅ Plots saved to: {plot_path}")
        
        # Also create a summary radar chart
        self._create_radar_chart(valid_results, output_dir, timestamp)
        
        print("\n📊 Visualization Summary:")
        print(f"   - Reward comparison bar chart")
        print(f"   - Mastery improvement box plots")
        print(f"   - Success vs dropout rates")
        print(f"   - Episode length violin plots")
        print(f"   - Final mastery distributions")
        print(f"   - Curriculum safety comparison")
        print(f"   - Radar chart comparison")
        print(f"\nOpen {plot_path} to view!")
    
    def _create_radar_chart(self, results: Dict, output_dir: Path, timestamp: str):
        """Create radar chart comparing all agents across metrics."""
        
        agents = list(results.keys())
        
        # Metrics to compare (normalized to 0-1 scale)
        metrics = ['Reward', 'Improvement', 'Success', 'Safety', 'Efficiency']
        
        # Calculate normalized scores
        max_reward = max(abs(r["avg_reward"]) for r in results.values())
        max_improvement = max(abs(r["avg_mastery_improvement"]) for r in results.values())
        
        values = []
        for agent in agents:
            r = results[agent]
            scores = [
                (r["avg_reward"] + max_reward) / (2 * max_reward) if max_reward > 0 else 0.5,  # Reward
                (r["avg_mastery_improvement"] + max_improvement) / (2 * max_improvement) if max_improvement > 0 else 0.5,  # Improvement
                r["success_rate"],  # Success rate
                1 - min(r["total_violations"] / 100, 1),  # Safety (inverted)
                1 - min(r["avg_episode_length"] / 50, 1),  # Efficiency (inverted)
            ]
            values.append(scores)
        
        # Create radar chart
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        
        angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
        angles += angles[:1]  # Complete the circle
        
        color_map = {
            'Random': '#E74C3C',
            'Rule-Based': '#F39C12',
            'PPO': '#27AE60',
            'DQN': '#3498DB',
            'A2C': '#9B59B6'
        }
        
        for agent, vals in zip(agents, values):
            vals = vals + vals[:1]  # Complete the circle
            color = color_map.get(agent, '#95A5A6')
            ax.plot(angles, vals, 'o-', linewidth=2, label=agent, color=color)
            ax.fill(angles, vals, alpha=0.25, color=color)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(metrics, size=12)
        ax.set_ylim(0, 1)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
        ax.set_title('Multi-Metric Agent Comparison', size=16, fontweight='bold', y=1.08)
        
        radar_path = output_dir / f"radar_comparison_{timestamp}.png"
        plt.savefig(radar_path, dpi=300, bbox_inches='tight')
        print(f"✅ Radar chart saved to: {radar_path}")


def main():
    """Main evaluation pipeline."""
    
    parser = argparse.ArgumentParser(
        description="Comprehensive evaluation of all RL agents",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--episodes",
        type=int,
        default=100,
        help="Number of evaluation episodes per agent (default: 100)"
    )
    
    parser.add_argument(
        "--agents",
        nargs='+',
        choices=['ppo', 'dqn', 'a2c'],
        default=['ppo', 'dqn', 'a2c'],
        help="RL agents to evaluate (default: all)"
    )
    
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate visualization plots"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Random seed for reproducibility (default: 123)"
    )
    
    args = parser.parse_args()
    
    # Create evaluator
    evaluator = ComprehensiveEvaluator(num_episodes=args.episodes, seed=args.seed)
    
    # Run comparison
    results = evaluator.compare_all_agents(agents=args.agents)
    
    # Generate visualizations
    if args.visualize:
        evaluator.generate_visualizations(results)
    
    print("\n" + "=" * 70)
    print("✅ EVALUATION COMPLETE!")
    print("=" * 70)
    print(f"\nResults saved to: ./evaluation_results/")
    
    if args.visualize:
        print(f"Plots saved to: ./evaluation_results/comprehensive_comparison_*.png")
    
    print("\nNext steps:")
    print("  → Analyze results in evaluation_results/")
    print("  → Compare agents for thesis")
    print("  → Deploy best model to production API")
    print("=" * 70)


if __name__ == "__main__":
    main()
