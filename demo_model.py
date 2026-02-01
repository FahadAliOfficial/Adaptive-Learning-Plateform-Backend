"""
Interactive Demo Script for DQN Model Testing
Tests model behavior across different student scenarios.

Run with: python demo_model.py
"""

import numpy as np
from pathlib import Path
from stable_baselines3 import DQN

from services.rl.student_simulator import StudentSimulator
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
from services.config import get_config


# Topic names for display
TOPIC_NAMES = {
    0: "UNIV_SYN_LOGIC",
    1: "UNIV_SYN_PREC", 
    2: "UNIV_VAR",
    3: "UNIV_COND",
    4: "UNIV_LOOP",
    5: "UNIV_FUNC",
    6: "UNIV_COLL",
    7: "UNIV_OOP"
}

DIFFICULTY_NAMES = {
    0: "Very Easy (0.2)",
    1: "Easy (0.4)",
    2: "Medium (0.6)",
    3: "Hard (0.8)",
    4: "Very Hard (1.0)"
}


def load_model():
    """Load the trained DQN model."""
    print("Loading trained DQN model...")
    simulator = StudentSimulator(seed=42)
    env = AdaptiveLearningEnv(simulator=simulator, max_steps_per_episode=100)
    model = DQN.load("./models/dqn/best/best_model.zip", env=env)
    print("✅ Model loaded!\n")
    return model, env, simulator


def create_custom_student(env, masteries: dict, archetype: str = "custom"):
    """Create a custom student with specific mastery levels."""
    profile = env.simulator.profiles[0]  # Use as template
    profile.archetype = archetype
    
    env.current_student = profile
    env.current_mastery = masteries.copy()
    env.step_count = 0
    env.episode_history = []
    env.recently_taught = []
    env.fluency_history = {topic: [] for topic in env.topics}
    env.mastery_history = {topic: [masteries.get(topic, 0.1)] for topic in env.topics}
    env.stagnation_counter = {topic: 0 for topic in env.topics}
    env.milestones_hit = {0.30: False, 0.40: False, 0.50: False, 0.60: False}
    
    return env._get_state_vector()


def display_recommendation(action, env):
    """Display the model's recommendation."""
    topic_idx = action // 5
    difficulty_idx = action % 5
    
    topic = env.topics[topic_idx]
    difficulty = env.difficulty_tiers[difficulty_idx]
    
    print(f"\n🎯 MODEL RECOMMENDATION:")
    print(f"   Topic: {topic} ({TOPIC_NAMES.get(topic_idx, topic_idx)})")
    print(f"   Difficulty: {DIFFICULTY_NAMES.get(difficulty_idx, difficulty_idx)}")
    print(f"   Action ID: {action}")


def run_scenario(model, env, name, masteries):
    """Run a single scenario and show recommendation."""
    print(f"\n{'='*60}")
    print(f"📚 SCENARIO: {name}")
    print(f"{'='*60}")
    
    print("\nStudent Mastery Levels:")
    for topic, mastery in masteries.items():
        bar = "█" * int(mastery * 20) + "░" * (20 - int(mastery * 20))
        print(f"   {topic}: {bar} {mastery*100:.0f}%")
    
    state = create_custom_student(env, masteries)
    action, _ = model.predict(state, deterministic=True)
    display_recommendation(int(action), env)


def demo_beginner_student(model, env):
    """Test with a complete beginner."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.05,
        "UNIV_SYN_PREC": 0.05,
        "UNIV_VAR": 0.10,
        "UNIV_COND": 0.05,
        "UNIV_LOOP": 0.02,
        "UNIV_FUNC": 0.01,
        "UNIV_COLL": 0.01,
        "UNIV_OOP": 0.00
    }
    run_scenario(model, env, "Complete Beginner (0-10% mastery)", masteries)


def demo_intermediate_student(model, env):
    """Test with an intermediate student."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.60,
        "UNIV_SYN_PREC": 0.55,
        "UNIV_VAR": 0.70,
        "UNIV_COND": 0.50,
        "UNIV_LOOP": 0.45,
        "UNIV_FUNC": 0.30,
        "UNIV_COLL": 0.20,
        "UNIV_OOP": 0.10
    }
    run_scenario(model, env, "Intermediate Student (30-70% mastery)", masteries)


def demo_advanced_student(model, env):
    """Test with an advanced student."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.90,
        "UNIV_SYN_PREC": 0.85,
        "UNIV_VAR": 0.95,
        "UNIV_COND": 0.88,
        "UNIV_LOOP": 0.82,
        "UNIV_FUNC": 0.75,
        "UNIV_COLL": 0.65,
        "UNIV_OOP": 0.55
    }
    run_scenario(model, env, "Advanced Student (65-95% mastery)", masteries)


def demo_weak_in_loops(model, env):
    """Test with student weak in loops but strong elsewhere."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.70,
        "UNIV_SYN_PREC": 0.65,
        "UNIV_VAR": 0.80,
        "UNIV_COND": 0.75,
        "UNIV_LOOP": 0.15,  # Weak!
        "UNIV_FUNC": 0.60,
        "UNIV_COLL": 0.50,
        "UNIV_OOP": 0.40
    }
    run_scenario(model, env, "Strong Overall, Weak in LOOPS", masteries)


def demo_unbalanced_student(model, env):
    """Test with unbalanced mastery (skipped foundations)."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.20,  # Skipped!
        "UNIV_SYN_PREC": 0.15,   # Skipped!
        "UNIV_VAR": 0.25,        # Skipped!
        "UNIV_COND": 0.70,
        "UNIV_LOOP": 0.65,
        "UNIV_FUNC": 0.60,
        "UNIV_COLL": 0.55,
        "UNIV_OOP": 0.50
    }
    run_scenario(model, env, "Skipped Foundations (unbalanced)", masteries)


def demo_ready_for_oop(model, env):
    """Test with student ready for OOP."""
    masteries = {
        "UNIV_SYN_LOGIC": 0.80,
        "UNIV_SYN_PREC": 0.75,
        "UNIV_VAR": 0.85,
        "UNIV_COND": 0.80,
        "UNIV_LOOP": 0.75,
        "UNIV_FUNC": 0.70,
        "UNIV_COLL": 0.65,
        "UNIV_OOP": 0.30  # Ready to learn OOP
    }
    run_scenario(model, env, "Ready for OOP (strong foundations)", masteries)


def simulate_learning_journey(model, env, simulator, num_steps=10):
    """Simulate a learning journey and show progression."""
    print(f"\n{'='*60}")
    print(f"🚀 SIMULATED LEARNING JOURNEY ({num_steps} steps)")
    print(f"{'='*60}")
    
    state, info = env.reset()
    print(f"\nStarting with student: {info['student_id']}")
    print(f"Initial avg mastery: {info['initial_avg_mastery']*100:.1f}%\n")
    
    print(f"{'Step':<5} {'Topic':<18} {'Difficulty':<12} {'Accuracy':<10} {'Mastery Δ':<12}")
    print("-" * 60)
    
    for step in range(num_steps):
        action, _ = model.predict(state, deterministic=True)
        action = int(action)
        
        topic_idx = action // 5
        diff_idx = action % 5
        topic = env.topics[topic_idx]
        
        old_mastery = env.current_mastery[topic]
        state, reward, terminated, truncated, info = env.step(action)
        new_mastery = info.get('avg_mastery', 0)
        
        accuracy = env.episode_history[-1]['accuracy'] if env.episode_history else 0
        delta = env.episode_history[-1]['new_mastery'] - env.episode_history[-1]['old_mastery']
        
        print(f"{step+1:<5} {topic:<18} {diff_idx+1:<12} {accuracy*100:>6.1f}%    {delta*100:>+6.2f}%")
        
        if terminated or truncated:
            print(f"\nEpisode ended: {'Completed' if terminated else 'Student quit'}")
            break
    
    final_mastery = np.mean(list(env.current_mastery.values()))
    improvement = final_mastery - info['initial_avg_mastery']
    print(f"\n📊 Final avg mastery: {final_mastery*100:.1f}% (improvement: {improvement*100:+.1f}%)")


def interactive_mode(model, env):
    """Interactive mode for custom testing."""
    print(f"\n{'='*60}")
    print(f"🎮 INTERACTIVE MODE")
    print(f"{'='*60}")
    print("\nEnter mastery levels (0-100) for each topic, or press Enter for default (10)")
    
    masteries = {}
    for topic in env.topics:
        try:
            val = input(f"   {topic} mastery [10]: ").strip()
            masteries[topic] = int(val) / 100 if val else 0.10
        except ValueError:
            masteries[topic] = 0.10
    
    run_scenario(model, env, "Custom Student", masteries)


def main():
    print("\n" + "="*60)
    print("🤖 DQN MODEL DEMO - Test Model on Different Students")
    print("="*60)
    
    model, env, simulator = load_model()
    
    while True:
        print("\n" + "-"*40)
        print("Select a scenario to test:")
        print("-"*40)
        print("1. Complete Beginner (0-10% mastery)")
        print("2. Intermediate Student (30-70% mastery)")
        print("3. Advanced Student (65-95% mastery)")
        print("4. Weak in Loops (specific weakness)")
        print("5. Skipped Foundations (unbalanced)")
        print("6. Ready for OOP (strong foundations)")
        print("7. Simulate 10-step learning journey")
        print("8. Interactive mode (enter custom mastery)")
        print("0. Exit")
        
        try:
            choice = input("\nEnter choice (0-8): ").strip()
            
            if choice == "1":
                demo_beginner_student(model, env)
            elif choice == "2":
                demo_intermediate_student(model, env)
            elif choice == "3":
                demo_advanced_student(model, env)
            elif choice == "4":
                demo_weak_in_loops(model, env)
            elif choice == "5":
                demo_unbalanced_student(model, env)
            elif choice == "6":
                demo_ready_for_oop(model, env)
            elif choice == "7":
                simulate_learning_journey(model, env, simulator)
            elif choice == "8":
                interactive_mode(model, env)
            elif choice == "0":
                print("\n👋 Goodbye!")
                break
            else:
                print("Invalid choice, try again.")
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break


if __name__ == "__main__":
    main()
