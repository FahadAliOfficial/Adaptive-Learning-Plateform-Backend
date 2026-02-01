"""
Demo script for Adaptive Learning Environment (Component 2).

Shows how the Gym environment works with the student simulator.
"""

from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
import numpy as np


def demo_environment():
    """Demonstrate Adaptive Learning Environment functionality."""
    
    print("=" * 70)
    print("ADAPTIVE LEARNING ENVIRONMENT DEMO - Component 2 of Phase 4")
    print("=" * 70)
    
    # Initialize simulator and environment
    print("\n1. Initializing environment...")
    sim = StudentSimulator(seed=42)
    env = AdaptiveLearningEnv(sim, max_steps_per_episode=10, render_mode="human")
    
    print(f"✅ Environment created!")
    print(f"   Action space: {env.action_space} (40 discrete actions)")
    print(f"   State space: {env.observation_space} (36D continuous)")
    print(f"   Max steps per episode: {env.max_steps}")
    
    # Show action encoding/decoding
    print("\n2. Action Space Encoding:")
    print("-" * 70)
    print(f"\nAction encoding: action_id = topic_idx * 5 + difficulty_idx")
    print(f"\nExamples:")
    for action_id in [0, 9, 17, 25, 39]:
        topic, difficulty = env.decode_action(action_id)
        print(f"   Action {action_id:2d} → {topic:12s} @ difficulty {difficulty:.1f}")
    
    # Run one episode with random actions
    print("\n3. Running one episode with RANDOM actions:")
    print("=" * 70)
    
    state, info = env.reset(seed=42)
    
    print(f"\n📊 Episode started:")
    print(f"   Student: {info['student_id']}")
    print(f"   Learning rate: {info['learning_rate']:.2f}")
    print(f"   Initial avg mastery: {info['initial_avg_mastery']:.3f}")
    print(f"   State vector shape: {state.shape}")
    print(f"   State sample (first 13 dims): {state[:13]}")
    
    total_reward = 0
    step_num = 0
    
    print("\n" + "=" * 70)
    print("TEACHING SEQUENCE (Random Actions)")
    print("=" * 70)
    
    while True:
        # Random action (RL agent will replace this)
        action = env.action_space.sample()
        topic, difficulty = env.decode_action(action)
        
        # Execute action
        next_state, reward, terminated, truncated, info = env.step(action)
        
        step_num += 1
        total_reward += reward
        
        # Display step info
        print(f"\nStep {step_num}:")
        print(f"  Action: {action} → Teach {topic} @ {difficulty:.1f} difficulty")
        print(f"  Accuracy: {info['accuracy']:.1%}")
        print(f"  Mastery: {info['mastery_delta']:+.3f} ({info['avg_mastery']:.3f} avg)")
        print(f"  Reward: {reward:+.2f} (total: {total_reward:+.2f})")
        
        if info.get('gate_violations', 0) > 0:
            print(f"  ⚠️  Prerequisite violations: {info['gate_violations']}")
        
        if info.get('gave_up', False):
            print(f"  😫 Student quit (frustrated)!")
        
        # Check termination
        if terminated or truncated:
            reason = "Student quit" if truncated else "Episode complete"
            print(f"\n🏁 {reason}")
            break
        
        state = next_state
    
    # Show episode statistics
    print("\n" + "=" * 70)
    print("EPISODE STATISTICS")
    print("=" * 70)
    
    stats = env.get_episode_stats()
    print(f"\nSteps taken: {stats['total_steps']}")
    print(f"Total reward: {stats['total_reward']:.2f}")
    print(f"Average reward: {stats['avg_reward']:.2f}")
    print(f"Average accuracy: {stats['avg_accuracy']:.1%}")
    print(f"Average mastery delta: {stats['avg_mastery_delta']:+.3f}")
    print(f"Final average mastery: {stats['final_avg_mastery']:.3f}")
    print(f"Gate violations: {stats['gate_violations']}")
    print(f"Student quit: {stats['student_quit']}")
    
    # Show reward components breakdown
    print("\n" + "=" * 70)
    print("REWARD FUNCTION DEMONSTRATION")
    print("=" * 70)
    
    print("\nTesting different scenarios:\n")
    
    # Scenario 1: Good teaching (mastery improvement)
    print("Scenario 1: Good teaching")
    print("  Old mastery: 0.5, New: 0.6 (+0.1)")
    print("  Accuracy: 70% (good challenge)")
    print("  No violations")
    reward = env._calculate_reward(
        old_mastery=0.5, new_mastery=0.6, accuracy=0.7,
        fluency_ratio=1.2, gate_violations=[], difficulty=0.6, topic="UNIV_VAR"
    )
    print(f"  → Reward: {reward:+.2f} ✅\n")
    
    # Scenario 2: Too hard (student struggles)
    print("Scenario 2: Too hard (student struggles)")
    print("  Old mastery: 0.3, New: 0.25 (-0.05)")
    print("  Accuracy: 30% (too difficult)")
    print("  No violations")
    reward = env._calculate_reward(
        old_mastery=0.3, new_mastery=0.25, accuracy=0.3,
        fluency_ratio=0.8, gate_violations=[], difficulty=0.9, topic="UNIV_OOP"
    )
    print(f"  → Reward: {reward:+.2f} ❌\n")
    
    # Scenario 3: Prerequisite violation
    print("Scenario 3: Prerequisite violation")
    print("  Teaching OOP without FUNC mastery")
    print("  Violations: 2")
    reward = env._calculate_reward(
        old_mastery=0.2, new_mastery=0.25, accuracy=0.4,
        fluency_ratio=1.0, gate_violations=["UNIV_VAR", "UNIV_FUNC"],
        difficulty=0.5, topic="UNIV_OOP"
    )
    print(f"  → Reward: {reward:+.2f} (penalty: -4.0) ⚠️\n")
    
    # Scenario 4: Too easy (boring)
    print("Scenario 4: Too easy (boring)")
    print("  Old mastery: 0.8, New: 0.82 (+0.02)")
    print("  Accuracy: 95% (too easy)")
    reward = env._calculate_reward(
        old_mastery=0.8, new_mastery=0.82, accuracy=0.95,
        fluency_ratio=1.5, gate_violations=[], difficulty=0.3, topic="UNIV_VAR"
    )
    print(f"  → Reward: {reward:+.2f} (small gain) 😴\n")
    
    # Run a smarter episode with rule-based policy
    print("\n" + "=" * 70)
    print("RUNNING SMART EPISODE (Rule-Based Policy)")
    print("=" * 70)
    print("\nStrategy: Teach topics in order, match difficulty to mastery\n")
    
    state, info = env.reset(seed=123)
    total_reward = 0
    
    # Simple rule-based policy
    topic_order = ["UNIV_VAR", "UNIV_FUNC", "UNIV_COND", "UNIV_LOOP", 
                   "UNIV_COLL", "UNIV_OOP", "UNIV_RECUR", "UNIV_ERR"]
    
    for i, topic in enumerate(topic_order):
        if i >= env.max_steps:
            break
        
        # Get current mastery for this topic
        current_mastery = env.current_mastery[topic]
        
        # Match difficulty to mastery (adaptive)
        target_difficulty = min(current_mastery + 0.1, 1.0)
        
        # Find closest difficulty tier
        difficulty_idx = np.argmin(np.abs(env.difficulty_tiers - target_difficulty))
        difficulty = env.difficulty_tiers[difficulty_idx]
        
        # Encode action
        action = env.encode_action(topic, difficulty)
        
        # Execute
        next_state, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        
        print(f"Step {i+1}: {topic:12s} @ {difficulty:.1f} → "
              f"acc={info['accuracy']:.1%}, Δ={info['mastery_delta']:+.3f}, "
              f"reward={reward:+.2f}")
        
        if terminated or truncated:
            break
        
        state = next_state
    
    print(f"\nSmart policy total reward: {total_reward:+.2f}")
    
    stats = env.get_episode_stats()
    print(f"Final average mastery: {stats['final_avg_mastery']:.3f}")
    print(f"Gate violations: {stats['gate_violations']}")
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ Component 2 (Adaptive Learning Environment) is COMPLETE!")
    print("=" * 70)
    print("\nKey Features Demonstrated:")
    print("  ✅ Gymnasium API compatibility")
    print("  ✅ 40 discrete actions (8 topics × 5 difficulties)")
    print("  ✅ 36D state vectors (matches StateVectorGenerator)")
    print("  ✅ Curriculum-aware rewards (mastery + difficulty + safety)")
    print("  ✅ Prerequisite violation detection")
    print("  ✅ Student dropout modeling")
    print("  ✅ Episode statistics tracking")
    print("\nNext steps:")
    print("  → Component 3: PPO Agent (policy network)")
    print("  → Component 4: Training Pipeline")
    print("  → Component 5: Evaluation Framework")
    print("\nThe environment is ready for RL training!")
    print("=" * 70)


if __name__ == "__main__":
    demo_environment()
