"""
Adaptive Learning Environment - Gymnasium-compatible RL environment.

This is the core training environment where RL agents learn to make curriculum decisions.

Key Features:
- Wraps StudentSimulator in Gym API
- Action Space: Dynamic based on curriculum (num_topics × num_difficulties)
- State Space: Dynamic based on curriculum dimensions
- Reward: Curriculum-aware (mastery improvement + optimal challenge + safety)
- Termination: 20 topics taught OR 80% avg mastery OR student quits

Example Usage:
    >>> from services.rl.student_simulator import StudentSimulator
    >>> from services.rl.adaptive_learning_env import AdaptiveLearningEnv
    >>> 
    >>> sim = StudentSimulator(seed=42)
    >>> env = AdaptiveLearningEnv(sim)
    >>> 
    >>> state, info = env.reset()
    >>> action = env.action_space.sample()  # Random action
    >>> next_state, reward, terminated, truncated, info = env.step(action)
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Dict, Any, Tuple, Optional
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.rl.student_simulator import StudentSimulator, StudentProfile, UNIVERSAL_MAPPINGS
from services.config import get_config


class AdaptiveLearningEnv(gym.Env):
    """
    Gymnasium environment for adaptive curriculum sequencing.
    
    This environment simulates the teaching process where an RL agent decides
    what topic to teach next and at what difficulty level.
    
    ⚠️ CRITICAL: State dimensions are LOCKED to current curriculum configuration!
    Current: 38D state (5 languages + 8 topics × 3 + 9 behavioral)
    
    DO NOT modify final_curriculum.json (add/remove languages or topics) without:
    1. Retraining ALL models from scratch
    2. Updating this dimension documentation
    3. Clearing all saved model checkpoints
    
    Spaces:
        - Action: Discrete(40) representing (8 topics × 5 difficulty tiers)
        - Observation: Box(38,) continuous state vector [LOCKED]
    
    State Vector Structure (38D FIXED):
        [0-4]   Language one-hot (5 languages)
        [5-12]  Mastery scores (8 universal topics)
        [13-20] Fluency scores (8 universal topics)
        [21-28] Confidence scores (8 universal topics)
        [29-37] Behavioral features (9 metrics)
    
    Rewards (ASYMMETRIC):
        - Mastery improvement: +20 per 0.1 gain (asymmetric: -2 for loss)
        - Optimal difficulty: +1.0 for ZPD (40-85% accuracy)
        - Prerequisite violation: -10.0 per violation
        - Fluency bonus: +0.5 for efficient learning
        - Coherence bonus: +0.8 for curriculum sequencing
        - Dropout penalty: -5.0 if student quits
    
    Termination:
        - Max steps reached (50 topics)
        - Student quits (frustrated)
        - Curriculum complete (60% avg mastery)
    
    Attributes:
        simulator: StudentSimulator instance
        max_steps: Maximum topics per episode (default 20)
        current_student: Active student profile
        current_mastery: Current mastery scores per topic
        step_count: Number of actions taken
        episode_history: List of all teaching actions
    """
    
    metadata = {"render_modes": ["human", "rgb_array"]}
    
    def __init__(
        self,
        simulator: StudentSimulator,
        max_steps_per_episode: int = 100,  # P2 FIX: Increased from 50 to 100 for better topic coverage
        render_mode: Optional[str] = None
    ):
        """
        Initialize the adaptive learning environment.
        
        Args:
            simulator: StudentSimulator instance for generating student behavior
            max_steps_per_episode: Maximum number of topics to teach per episode
            render_mode: Rendering mode ('human' for console, 'rgb_array' for images, None for no rendering)
        """
        super().__init__()
        
        self.simulator = simulator
        self.max_steps = max_steps_per_episode
        self.render_mode = render_mode
        
        # Load configuration dynamically from curriculum
        self.config = get_config()
        self.topics = self.config.universal_mappings.copy()
        
        # Extract difficulty tiers from transition_map.json
        # Use the first tier config as template (all topics use same tiers)
        tier_configs = self.config.transition_map['question_difficulty_tiers']
        if tier_configs:
            # Extract difficulty values from tier configuration
            # Default tiers: beginner=0.2, intermediate=0.4, advanced=0.6-1.0
            self.difficulty_tiers = np.array([0.2, 0.4, 0.6, 0.8, 1.0])
        else:
            # Fallback to default tiers if not in config
            self.difficulty_tiers = np.array([0.2, 0.4, 0.6, 0.8, 1.0])
        
        self.num_topics = len(self.topics)
        self.num_difficulties = len(self.difficulty_tiers)
        
        # Action space: LOCKED to current curriculum
        # 8 universal topics × 5 difficulty tiers = 40 discrete actions
        # Encoding: action_id = topic_idx * num_difficulties + difficulty_idx
        # Example: action=17 → topic=3 (UNIV_LOOP), difficulty=2 (0.6)
        self.action_space = spaces.Discrete(self.num_topics * self.num_difficulties)
        
        # State space: LOCKED to current curriculum dimensions
        # ⚠️ CRITICAL: This dimension is FIXED for all trained models!
        # Current curriculum: 5 languages, 8 universal topics
        # 
        # State vector structure:
        # [0-4]   Language one-hot (5 languages: python, js, java, cpp, go)
        # [5-12]  Mastery scores (8 topics: SYN_LOGIC, SYN_PREC, VAR, COND, LOOP, FUNC, COLL, OOP)
        # [13-20] Fluency scores (8 topics)
        # [21-28] Confidence scores (8 topics)
        # [29-37] Behavioral metrics (9 features)
        # TOTAL: 5 + 8*3 + 9 = 38D
        
        num_languages = len(self.config.valid_languages)
        state_dim = num_languages + (self.num_topics * 3) + 9
        
        # Validate dimensions match expected curriculum
        expected_state_dim = 38  # LOCKED: 5 languages + 8 topics
        if state_dim != expected_state_dim:
            raise ValueError(
                f"State dimension mismatch! Expected {expected_state_dim}D (5 languages, 8 topics), "
                f"got {state_dim}D ({num_languages} languages, {self.num_topics} topics). \n"
                f"You CANNOT train models with different curriculum dimensions! \n"
                f"Either: \n"
                f"1. Restore original curriculum (5 languages, 8 universal topics)\n"
                f"2. Retrain ALL models from scratch with new dimensions\n"
                f"3. Update EXPECTED_STATE_DIM constant in this file"
            )
        
        self.observation_space = spaces.Box(
            low=-3.0,   # Normalized features can be negative
            high=3.0,   # Reasonable upper bound
            shape=(state_dim,),
            dtype=np.float32
        )
        
        # Episode state
        self.current_student: Optional[StudentProfile] = None
        self.current_mastery: Dict[str, float] = {}
        self.step_count = 0
        self.episode_history = []
        self.recently_taught = []  # For diversity bonus
        
        # Statistics tracking
        self.total_episodes = 0
        self.total_steps = 0
    
    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Reset the environment to start a new episode.
        
        Selects a random student profile and initializes their learning state.
        
        Args:
            seed: Random seed for reproducibility
            options: Additional options (not used currently)
        
        Returns:
            Tuple of (initial_state, info_dict):
            - initial_state: 36D numpy array representing student state
            - info: Dictionary with episode metadata
        """
        super().reset(seed=seed)
        
        # Select random student profile
        self.current_student = self.simulator.get_random_profile()
        
        # PHASE 1 FIX: Randomly select a language for this episode
        self.current_language_idx = np.random.randint(0, len(self.config.valid_languages))
        # Set language on profile for language-specific difficulty modifiers
        languages = list(self.config.valid_languages)
        self.current_student.current_language = languages[self.current_language_idx]
        
        # Initialize mastery from profile
        self.current_mastery = self.current_student.initial_mastery.copy()
        
        # Track initial average mastery for episode-end bonus calculation
        self.initial_avg_mastery = np.mean(list(self.current_mastery.values()))
        
        # TIERED GOAL SYSTEM
        # Assigns each student a progression target matching their starting level:
        #   Beginner     (avg mastery < 0.25)  → goal = 0.50  (reach mid-level)
        #   Intermediate (avg mastery 0.25–0.54) → goal = 0.75  (reach advanced)
        #   Advanced     (avg mastery ≥ 0.55)  → goal = 0.85  (reach mastery)
        # Goals upgrade dynamically mid-episode as tier boundaries are crossed.
        if self.initial_avg_mastery < 0.25:
            self.initial_tier = 'beginner'
            self.current_goal_mastery = 0.50
        elif self.initial_avg_mastery < 0.55:
            self.initial_tier = 'intermediate'
            self.current_goal_mastery = 0.75
        else:
            self.initial_tier = 'advanced'
            self.current_goal_mastery = 0.85
        
        # Flags to prevent multiple bonuses for the same tier crossing
        self.tier_crossed_to_mid = False
        self.tier_crossed_to_advanced = False
        self.tier_crossed_to_mastery = False
        
        # Reset episode tracking
        self.step_count = 0
        self.episode_history = []
        self.recently_taught = []
        
        # PRODUCTION ALIGNMENT: Track fluency and mastery history per topic
        self.fluency_history = {topic: [] for topic in self.topics}
        self.mastery_history = {topic: [self.current_mastery[topic]] for topic in self.topics}
        
        # Milestones aligned to tier thresholds
        self.milestones_hit = {0.50: False, 0.75: False, 0.85: False}
        
        # Increment episode counter
        self.total_episodes += 1
        
        # Generate initial state vector
        state = self._get_state_vector()
        
        info = {
            "student_id": self.current_student.student_id,
            "learning_rate": self.current_student.learning_rate,
            "initial_avg_mastery": np.mean(list(self.current_mastery.values())),
            "episode_number": self.total_episodes
        }
        
        return state, info
    
    def action_masks(self) -> np.ndarray:
        """
        Return binary mask indicating which actions are valid based on curriculum prerequisites.
        
        Used by RL algorithms to prevent suggesting locked topics.
        An action is valid if:
        1. Topic has no prerequisites (always accessible)
        2. Topic prerequisites are met (mastery >= minimum threshold)
        3. Student has already started practicing the topic
        
        Returns:
            np.ndarray of shape (40,) with 1=valid, 0=blocked
        """
        mask = np.zeros(self.action_space.n, dtype=np.int8)
        
        for i, topic in enumerate(self.topics):
            # Check if topic is accessible
            violations = self._check_prerequisite_violations(topic)
            
            # Topic is accessible if:
            # 1. No prerequisite violations, OR
            # 2. Student has made meaningful progress (>=35% mastery allows continuation)
            # NOTE: Changed from >0 to >=0.35 to prevent random init noise from bypassing gates
            is_accessible = (len(violations) == 0) or (self.current_mastery[topic] >= 0.35)
            
            if is_accessible:
                # Enable all 5 difficulty levels for this topic
                for j in range(5):
                    mask[i * 5 + j] = 1
        
        return mask
    
    def step(
        self,
        action: int
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Execute one teaching action and observe the result.
        
        Args:
            action: Integer 0-39 representing (topic, difficulty) pair
        
        Returns:
            Tuple of (next_state, reward, terminated, truncated, info):
            - next_state: 36D state vector after action
            - reward: Scalar reward value
            - terminated: True if episode completed naturally
            - truncated: True if episode stopped early (student quit)
            - info: Dictionary with step metadata
        """
        
        # CURRICULUM CONSTRAINT: Check if action is valid (prerequisites met)
        mask = self.action_masks()
        if mask[action] == 0:
            # Invalid action - teaching locked topic
            # Return immediate penalty and truncate episode
            next_state = self._get_state_vector()
            reward_original = -50.0  # Catastrophic penalty for violation
            
            # REWARD CLIPPING (apply to ALL returns, including violations)
            REWARD_CLIP_MIN = -10.0
            REWARD_CLIP_MAX = +10.0
            reward = np.clip(reward_original, REWARD_CLIP_MIN, REWARD_CLIP_MAX)
            
            terminated = False
            truncated = True
            info = {
                "step": self.step_count,
                "action": action,
                "error": "invalid_action_locked_topic",
                "avg_mastery": np.mean(list(self.current_mastery.values())),
                "reward_clipped": reward,
                "reward_original": reward_original
            }
            return next_state, reward, terminated, truncated, info
        
        # Decode action into topic and difficulty
        topic_idx = action // 5
        difficulty_idx = action % 5
        
        topic = self.topics[topic_idx]
        difficulty = self.difficulty_tiers[difficulty_idx]
        
        # Get current mastery for this topic
        old_mastery = self.current_mastery[topic]
        
        # Simulate student taking exam
        accuracy, time_ratio, gave_up = self.simulator.simulate_exam_performance(
            profile=self.current_student,
            topic=topic,
            difficulty=difficulty,
            current_mastery=old_mastery,
            all_masteries=self.current_mastery  # Pass full mastery dict for prereq checking
        )
        
        # Calculate fluency ratio (inverse of time) - needed for high-velocity detection
        fluency_ratio = 1.0 / time_ratio if time_ratio > 0 else 1.0
        
        # FIX #2: Generate error type if student got questions wrong
        is_correct = accuracy >= 0.5  # Simplified: >50% accuracy = "mostly correct"
        error_type = self.simulator.generate_error_type(topic, is_correct, difficulty)
        
        # Update mastery with high-velocity detection and error remediation
        new_mastery = self.simulator.calculate_mastery_update(
            profile=self.current_student,
            old_mastery=old_mastery,
            exam_accuracy=accuracy,
            difficulty=difficulty,
            fluency_ratio=fluency_ratio,  # FIX #1: Pass fluency for velocity detection
            topic=topic,  # FIX #2: Pass topic for error remediation
            error_type=error_type  # FIX #2: Pass error type for tracking
        )
        self.current_mastery[topic] = new_mastery
        
        # PRODUCTION ALIGNMENT: Apply synergy bonuses (like GradingService)
        self.current_mastery = self.simulator.apply_synergy_bonuses(
            topic=topic,
            current_mastery=self.current_mastery,
            exam_accuracy=accuracy
        )
        
        # PRODUCTION ALIGNMENT: Apply concept interdependencies (like GradingService)
        self.current_mastery = self.simulator.apply_concept_interdependencies(
            topic=topic,
            current_mastery=self.current_mastery,
            new_mastery=new_mastery
        )
        
        # Track history for realistic state vector generation
        self.fluency_history[topic].append(time_ratio)
        self.mastery_history[topic].append(new_mastery)
        
        # Check soft gate violations
        gate_violations = self._check_prerequisite_violations(topic)
        
        # Calculate reward
        reward = self._calculate_reward(
            old_mastery=old_mastery,
            new_mastery=new_mastery,
            accuracy=accuracy,
            fluency_ratio=fluency_ratio,
            gate_violations=gate_violations,
            difficulty=difficulty,
            topic=topic,
            gave_up=gave_up  # FIX: Pass dropout signal to reward
        )
        
        # REBALANCE FIX: Per-step survival bonus (+0.5 if student didn't quit)
        # This is the key fix: 79-step episode = +39.5 survival bonus vs 6-step = +3.0
        # Gives model a concrete incentive to KEEP the student engaged each step
        if not gave_up:
            reward += 0.5
        
        # REMOVED: Stagnation penalty - compounded with dropout to cause cascade failures
        # Model would panic and end episodes early when stagnation + dropout risk combined
        
        # Track teaching history
        self.step_count += 1
        self.total_steps += 1
        self.recently_taught.append(topic)
        if len(self.recently_taught) > 5:
            self.recently_taught.pop(0)
        
        self.episode_history.append({
            "step": self.step_count,
            "action": action,
            "topic": topic,
            "difficulty": difficulty,
            "old_mastery": old_mastery,
            "new_mastery": new_mastery,
            "accuracy": accuracy,
            "time_ratio": time_ratio,
            "reward": reward,
            "gave_up": gave_up,
            "gate_violations": len(gate_violations)
        })
        
        # Check termination conditions
        terminated = False
        truncated = False
        
        # Condition 1: Max steps reached
        if self.step_count >= self.max_steps:
            terminated = True
        
        # Condition 2: Student gave up (frustrated)
        if gave_up:
            truncated = True
            # Dropout penalty already applied in _calculate_reward()
        
        # Condition 3: Curriculum complete (60% average mastery)
        avg_mastery = np.mean(list(self.current_mastery.values()))
        
        # TIERED GOAL: Check for tier crossings every step.
        # Fires an immediate reward when a boundary is crossed and upgrades
        # current_goal_mastery so the agent keeps pushing the student forward.
        # REBALANCE FIX v2: Doubled all milestone bonuses to incentivize long episodes
        if avg_mastery >= 0.50 and not self.tier_crossed_to_mid:
            self.tier_crossed_to_mid = True
            reward += 100.0  # Doubled: Was 50.0
            if self.current_goal_mastery <= 0.50:
                self.current_goal_mastery = 0.75  # Upgrade goal to advanced
        
        if avg_mastery >= 0.75 and not self.tier_crossed_to_advanced:
            self.tier_crossed_to_advanced = True
            reward += 200.0  # Doubled: Was 75.0 → now cumulative +300
            if self.current_goal_mastery <= 0.75:
                self.current_goal_mastery = 0.85  # Upgrade goal to mastery
        
        if avg_mastery >= 0.85 and not self.tier_crossed_to_mastery:
            self.tier_crossed_to_mastery = True
            reward += 300.0  # Tripled: Was 100.0 → now cumulative +600
        
        # Milestone bonuses aligned to tier thresholds (fire once each per episode)
        milestones = [(0.50, 40.0), (0.75, 70.0), (0.85, 100.0)]
        for threshold, bonus in milestones:
            if avg_mastery >= threshold and not self.milestones_hit.get(threshold, False):
                reward += bonus
                self.milestones_hit[threshold] = True
        
        if terminated or truncated:
            # Calculate total mastery improvement over episode
            final_avg_mastery = avg_mastery
            total_improvement = final_avg_mastery - self.initial_avg_mastery
            
            # Scale reward with how much the student actually improved
            episode_improvement_bonus = total_improvement * 200.0
            reward += episode_improvement_bonus
            
            # Tiered completion bonuses (success threshold = 85% mastery)
            # REBALANCE FIX v2: Larger bonuses to incentivize long successful episodes
            if avg_mastery >= 0.85:
                # Full mastery achieved — ultimate success
                completion_bonus = +300.0  # Was +100.0
                reward += completion_bonus
            elif avg_mastery >= 0.75:
                # Reached advanced level
                completion_bonus = +200.0  # Was +70.0
                reward += completion_bonus
            elif avg_mastery >= 0.50:
                # Reached mid-level (beginner's primary goal)
                completion_bonus = +100.0  # Was +40.0
                reward += completion_bonus
            elif not gave_up and self.step_count >= 80:
                # Long episode engagement bonus (≥80% of 100 steps)
                completion_bonus = +50.0  # NEW: Reward patience
                reward += completion_bonus
            elif not gave_up and self.step_count >= 5:
                # Student stayed engaged — small engagement bonus
                completion_bonus = +20.0
                reward += completion_bonus
            else:
                completion_bonus = 0.0
        
        # Don't terminate mid-curriculum just for reaching threshold
        # Let student complete full learning journey
        
        # Get next state
        next_state = self._get_state_vector()
        
        # REWARD CLIPPING FOR TRAINING STABILITY (CRITICAL FIX)
        # Teacher feedback: Reward function has excessive variance
        # Current rewards range from -500 to +1,000 per episode
        # Clipping to [-10, +10] reduces variance by 50-100×
        # Standard RL practice: prevents gradient explosion and training instability
        # Optuna hyperparameter tuning requires stable reward signal
        reward_original = reward  # Preserve for logging/analysis
        REWARD_CLIP_MIN = -10.0
        REWARD_CLIP_MAX = +10.0
        reward = np.clip(reward, REWARD_CLIP_MIN, REWARD_CLIP_MAX)
        
        # Info for logging
        info = {
            "step": self.step_count,
            "action": action,
            "topic": topic,
            "difficulty": difficulty,
            "accuracy": accuracy,
            "mastery_delta": new_mastery - old_mastery,
            "avg_mastery": avg_mastery,
            "gave_up": gave_up,
            "gate_violations": len(gate_violations),
            "reward_clipped": reward,
            "reward_original": reward_original,
            "reward_components": {
                "mastery_improvement": (new_mastery - old_mastery) * 10.0,
                "difficulty_bonus": self._get_difficulty_bonus(accuracy),
                "prerequisite_penalty": -2.0 * len(gate_violations),
                "fluency_bonus": (fluency_ratio - 1.0) * 0.5
            }
        }
        
        return next_state, reward, terminated, truncated, info
    
    def _get_state_vector(self) -> np.ndarray:
        """
        Generate state vector for current student (dynamically sized based on curriculum).
        
        Mimics StateVectorGenerator structure for compatibility with trained models.
        
        Structure:
        - [0 : num_languages] Language one-hot encoding
        - [... : +num_topics] Mastery scores
        - [... : +num_topics] Fluency scores  
        - [... : +num_topics] Confidence scores
        - [... : +9] Behavioral metrics (9 features to match StateVectorGenerator)
        
        Returns:
            State vector matching observation_space dimensions
        """
        
        # Calculate dynamic offsets
        num_languages = len(self.config.valid_languages)
        lang_offset = 0
        mastery_offset = num_languages
        fluency_offset = mastery_offset + self.num_topics
        confidence_offset = fluency_offset + self.num_topics
        behavioral_offset = confidence_offset + self.num_topics
        
        # Initialize state vector with correct dimensions
        state_dim = num_languages + (self.num_topics * 3) + 9
        state = np.zeros(state_dim, dtype=np.float32)
        
        # [0 : num_languages] Language one-hot (randomized per episode)
        # PHASE 1 FIX: Use randomized language index from episode init
        lang_idx = getattr(self, 'current_language_idx', 0)
        state[lang_offset + lang_idx] = 1.0
        
        # [mastery_offset : mastery_offset + num_topics] Mastery scores
        for i, topic in enumerate(self.topics):
            state[mastery_offset + i] = self.current_mastery[topic]
        
        # [fluency_offset : fluency_offset + num_topics] Fluency scores
        # PRODUCTION ALIGNMENT: Use time ratio history with variance
        for i, topic in enumerate(self.topics):
            if hasattr(self, 'fluency_history') and self.fluency_history.get(topic):
                # Average of last 5 time ratios with small noise for variance
                history = self.fluency_history[topic][-5:]
                avg_fluency = np.mean(history) if history else 1.0
                noise = np.random.normal(0, 0.05)
                state[fluency_offset + i] = np.clip(avg_fluency + noise, 0.5, 2.0)
            else:
                state[fluency_offset + i] = 1.0 + np.random.normal(0, 0.1)  # Initial variance
        
        # [confidence_offset : confidence_offset + num_topics] Confidence scores
        # PRODUCTION ALIGNMENT: Use mastery stability (1 - std deviation of recent values)
        for i, topic in enumerate(self.topics):
            mastery = self.current_mastery[topic]
            if hasattr(self, 'mastery_history') and self.mastery_history.get(topic):
                # Confidence = stability * mastery (stable progress = high confidence)
                history = self.mastery_history[topic][-5:]
                stability = 1.0 - min(np.std(history) * 2, 0.5)
                state[confidence_offset + i] = stability * mastery
            else:
                state[confidence_offset + i] = min(mastery * 1.2, 1.0)
        
        # [behavioral_offset : behavioral_offset + 9] Behavioral metrics (9 features)
        
        # [0] Last session accuracy
        recent_accuracies = [h["accuracy"] for h in self.episode_history[-3:]]
        state[behavioral_offset + 0] = np.mean(recent_accuracies) if recent_accuracies else 0.5
        
        # [1] Last session difficulty
        recent_difficulties = [h["difficulty"] for h in self.episode_history[-3:]]
        state[behavioral_offset + 1] = np.mean(recent_difficulties) if recent_difficulties else 0.5
        
        # [2] Average fluency ratio
        # PHASE 1 FIX: Use student's learning_rate as proxy for fluency
        fluency = self.current_student.learning_rate  # Already 0.5-2.0 range
        state[behavioral_offset + 2] = np.clip(fluency, 0.5, 2.0)
        
        # [3] Mastery stability (inverse of std dev)
        masteries = list(self.current_mastery.values())
        state[behavioral_offset + 3] = 1.0 - np.std(masteries)
        
        # [4] Days inactive (simulate occasional breaks for realism)
        # PHASE 1 FIX: 80% no break, 15% short break (1-3 days), 5% long break (4-7 days)
        r = np.random.random()
        if r < 0.80:
            days_inactive = 0.0
        elif r < 0.95:
            days_inactive = np.random.uniform(1, 3)
        else:
            days_inactive = np.random.uniform(4, 7)
        state[behavioral_offset + 4] = days_inactive / 30.0  # Normalize to 0-1 range
        
        # [5] Gate readiness (% of prerequisites met)
        gate_readiness = self._calculate_gate_readiness()
        state[behavioral_offset + 5] = gate_readiness
        
        # [6] Session confidence (cold-start signal: 0→1 based on progress)
        state[behavioral_offset + 6] = min(self.step_count / 10.0, 1.0)
        
        # [7] Performance velocity (fast learner detection)
        if len(self.episode_history) >= 2:
            recent_masteries = [h.get("mastery_delta", 0.0) for h in self.episode_history[-2:]]
            velocity = np.mean(recent_masteries) if recent_masteries else 0.0
            state[behavioral_offset + 7] = min(velocity * 10.0, 1.0)  # Scale to 0-1
        else:
            state[behavioral_offset + 7] = 0.0
        
        # [8] Adaptive difficulty signal (unused in RL, reserved for Phase 2B)
        # P3 FIX: Encode student archetype for cross-episode learning
        # beginner=0.0, intermediate=0.5, advanced=1.0
        archetype = getattr(self.current_student, 'archetype', 'beginner')
        archetype_encoding = {'beginner': 0.0, 'intermediate': 0.5, 'advanced': 1.0}
        state[behavioral_offset + 8] = archetype_encoding.get(archetype, 0.0)
        
        return state
    
    def _calculate_reward(
        self,
        old_mastery: float,
        new_mastery: float,
        accuracy: float,
        fluency_ratio: float,
        gate_violations: list,
        difficulty: float,
        topic: str,
        gave_up: bool = False
    ) -> float:
        """
        Calculate curriculum-aware reward for the teaching action.
        
        Reward components:
        1. Mastery improvement (primary signal - ASYMMETRIC)
        2. Optimal difficulty bonus (Vygotsky's ZPD)
        3. Prerequisite penalty (safety)
        4. Fluency bonus (efficiency)
        5. Difficulty appropriateness
        6. Diversity bonus (exploration)
        7. Dropout penalty (retention)
        
        Args:
            old_mastery: Mastery before exam
            new_mastery: Mastery after exam
            accuracy: Exam performance (0-1)
            fluency_ratio: Speed metric (>1 = faster)
            gate_violations: List of prerequisite violations
            difficulty: Exam difficulty (0.2-1.0)
            topic: Topic taught
            gave_up: Whether student quit mid-exam
        
        Returns:
            Total reward (typically -10 to +10 range)
        """
        
        # ═══════════════════════════════════════════════════════════════════
        # 1. Base reward: Mastery improvement (DOMINANT SIGNAL - 80% of reward)
        # ═══════════════════════════════════════════════════════════════════
        # REBALANCE FIX: Stronger mastery signal (50× gains, 5× losses)
        # Previous 10× signal was overwhelmed by violation/stagnation penalties
        mastery_delta = new_mastery - old_mastery
        if mastery_delta > 0:
            base_reward = mastery_delta * 50.0  # Strong reward for improvement
        else:
            base_reward = mastery_delta * 5.0   # Small penalty for decay (can't fully control)
        
        # 2. Optimal difficulty bonus (Vygotsky's Zone of Proximal Development)
        # FIX: Reduced from ±0.5 to ±0.1 to prevent overshadowing mastery signal
        # Only meaningful when mastery actually improves
        if mastery_delta > 0 and 0.40 <= accuracy <= 0.85:
            difficulty_bonus = 0.2  # Small bonus for ZPD (capped, not scaled)
        elif accuracy < 0.40:
            difficulty_bonus = -0.1  # Too hard (reduced from -0.5)
        elif accuracy > 0.90:
            difficulty_bonus = -0.05  # Too easy (reduced from -0.3)
        else:
            difficulty_bonus = 0.0  # No learning, no bonus
        
        # 3. Prerequisite penalty (enforce curriculum safety)
        # REBALANCE FIX v2: Graduated penalty based on deficit severity
        # Replaces flat -1.5 that was too weak and -10.0 that was too harsh
        # This should never trigger in production since action masking prevents violations,
        # but serves as additional safety during training exploration
        prerequisite_penalty = self._calculate_soft_gate_penalty(gate_violations)
        
        # 4. Fluency bonus (reward efficient learning)
        # FIX: Reduced from ±0.5 to ±0.1 - fluency is nice-to-have, not core objective
        fluency_bonus = (fluency_ratio - 1.0) * 0.1
        fluency_bonus = np.clip(fluency_bonus, -0.1, 0.1)
        
        # 5. Difficulty appropriateness
        # FIX: Reduced from -0.5 to -0.1 to prevent overshadowing mastery
        difficulty_gap = abs(difficulty - new_mastery)
        difficulty_penalty = -0.1 if difficulty_gap > 0.3 else 0.0
        
        # 6. Coherence bonus (FIX #3: teach related topics together, not random jumps)
        # Check if current topic is synergistic with recently taught topics
        coherence_bonus = 0.0
        if len(self.recently_taught) > 0:
            # Check synergies from transition_map.json
            last_topic = self.recently_taught[-1]
            
            # Prerequisite relationships (good to teach in order)
            prereq_pairs = [
                ("UNIV_VAR", "UNIV_FUNC"),
                ("UNIV_COND", "UNIV_LOOP"),
                ("UNIV_FUNC", "UNIV_COLL"),
                ("UNIV_COLL", "UNIV_OOP")
            ]
            
            # Synergistic pairs (good to teach together)
            synergy_pairs = [
                ("UNIV_LOOP", "UNIV_COND"),
                ("UNIV_OOP", "UNIV_FUNC"),
                ("UNIV_COLL", "UNIV_LOOP")
            ]
            
            # Reward coherent curriculum sequencing
            # FIX: Reduced all coherence bonuses from ±0.8 to ±0.15
            # Prevents agent from farming +40 reward over 50 steps via repetition
            if (last_topic, topic) in prereq_pairs or (topic, last_topic) in prereq_pairs:
                coherence_bonus = +0.15  # Small bonus for following prerequisites
            elif (last_topic, topic) in synergy_pairs or (topic, last_topic) in synergy_pairs:
                coherence_bonus = +0.1  # Tiny bonus for synergistic topics
            elif topic == last_topic:
                # FIX: Track repetition count - diminishing returns
                repetition_count = self.recently_taught.count(topic)
                if repetition_count <= 2:
                    coherence_bonus = +0.05  # First 2 repetitions OK (spaced practice)
                else:
                    coherence_bonus = -0.1  # Over-drilling penalty
            else:
                coherence_bonus = -0.05  # Tiny penalty for random jumping
        
        # 7. Dropout penalty
        # REBALANCE FIX v2: Exponentially stronger early dropout penalty
        # Previous -70 early was still too weak to overcome survival bonus farming
        # New gradient: -200 (steps 1-10), -100 (11-30), -50 (31-60), -20 (61-100)
        if gave_up:
            progress = self.step_count / self.max_steps
            if progress < 0.10:
                dropout_penalty = -200.0  # Catastrophic early quit
            elif progress < 0.30:
                dropout_penalty = -100.0  # Very bad mid-early quit
            elif progress < 0.60:
                dropout_penalty = -50.0   # Moderate mid-quit
            else:
                dropout_penalty = -20.0   # Mild late quit (student tried hard)
        else:
            dropout_penalty = 0.0
        
        # 8. Completion bonus (FIX #2: Incentivize finishing full curriculum)
        # NOTE: This is calculated in step() when episode ends, not here
        # Placeholder for documentation - actual bonus added at termination
        
        # Total reward
        total = (
            base_reward +
            difficulty_bonus +
            prerequisite_penalty +
            fluency_bonus +
            difficulty_penalty +
            coherence_bonus +  # FIX #3: Replaced diversity_bonus
            dropout_penalty
        )
        
        # Scale reward by /20 instead of hard clipping.
        # Clipping destroyed relative magnitude: dropout(-200) and mastery(+5) both
        # became -10/+5, making dropout only 2x a bad step instead of 40x.
        # Scaling preserves ratios: dropout=-10, mastery gains=0.25–2.5, steps~±0.5
        # This keeps gradients stable while keeping the dropout penalty dominant.
        return float(total / 20.0)
    
    def _get_difficulty_bonus(self, accuracy: float) -> float:
        """
        Calculate difficulty bonus based on accuracy.
        
        PHASE 2 FIX: Smooth Gaussian curve instead of cliff edges.
        Sweet spot: 40-85% accuracy centered at 62.5%
        
        Args:
            accuracy: Exam accuracy (0-1)
        
        Returns:
            Bonus value (-0.5 to +1.0)
        """
        import math
        
        optimal_center = 0.625  # Midpoint of 40-85% range
        distance = abs(accuracy - optimal_center)
        
        # Gaussian-like curve: peaks at center, smooth falloff
        bonus = 1.0 * math.exp(-(distance ** 2) / 0.1)
        
        # Penalty for extreme cases (too easy or impossible)
        if accuracy < 0.20 or accuracy > 0.95:
            bonus -= 0.5
        
        return bonus
    
    def _check_prerequisite_violations(self, topic: str) -> list:
        """
        Check if prerequisites are met for given topic.
        
        Based on transition_map.json prerequisite rules:
        - UNIV_FUNC requires UNIV_VAR >= 0.6
        - UNIV_LOOP requires UNIV_COND >= 0.6
        - UNIV_COLL requires UNIV_VAR >= 0.6
        - UNIV_OOP requires UNIV_VAR, UNIV_FUNC, UNIV_COLL >= 0.6
        - UNIV_RECUR requires UNIV_FUNC, UNIV_LOOP >= 0.65
        - UNIV_ERR requires UNIV_FUNC >= 0.6
        
        Args:
            topic: Topic being taught
        
        Returns:
            List of violation strings (empty if no violations)
        
        Note: This is used for action masking - violations block the action entirely.
        For soft penalty calculation, use _calculate_soft_gate_penalty().
        """
        
        violations = []
        
        # PHASE 1 FIX: Load prerequisites dynamically from transition_map.json soft_gates
        # This eliminates ghost topics (UNIV_RECUR, UNIV_ERR) and uses correct prerequisite lists
        gate_info = self.simulator.get_soft_gate_info(topic)
        if gate_info:
            min_score = gate_info.get('min_score', 0.55)
            for prereq in gate_info['prereqs']:
                if prereq in self.current_mastery and self.current_mastery[prereq] < min_score:
                    violations.append(
                        f"{prereq} ({self.current_mastery[prereq]:.2f} < {min_score})"
                    )
        
        return violations
    
    def _calculate_soft_gate_penalty(self, gate_violations: list) -> float:
        """
        Calculate graduated penalty for prerequisite violations.
        
        REBALANCE FIX v2: Exponential scaling based on mastery deficit.
        Small deficit (10-20% below threshold) = -5 per prereq
        Large deficit (40-55% below threshold) = -20 per prereq
        
        This replaces flat -1.5 penalty that was too weak to influence learning.
        
        Args:
            gate_violations: List of violation strings from _check_prerequisite_violations
        
        Returns:
            Total penalty (negative value)
        """
        if not gate_violations:
            return 0.0
        
        total_penalty = 0.0
        
        for violation in gate_violations:
            # Parse violation string: "UNIV_VAR (0.25 < 0.55)"
            try:
                parts = violation.split('(')
                if len(parts) >= 2:
                    nums = parts[1].replace(')', '').split('<')
                    current = float(nums[0].strip())
                    required = float(nums[1].strip())
                    
                    deficit = required - current  # 0.0 to 0.55
                    deficit_ratio = deficit / required  # 0.0 to 1.0
                    
                    # Exponential scaling: y = -5 * (1 + (deficit_ratio)^2)
                    # At deficit_ratio=0.2 (small): -5.2
                    # At deficit_ratio=0.5 (medium): -6.25
                    # At deficit_ratio=1.0 (large): -10.0
                    penalty = -5.0 * (1.0 + deficit_ratio ** 2)
                    total_penalty += penalty
                else:
                    # Fallback if parsing fails
                    total_penalty += -5.0
            except:
                # Fallback if parsing fails
                total_penalty += -5.0
        
        return total_penalty
    
    def _calculate_gate_readiness(self) -> float:
        """
        Calculate average mastery of topics with soft gates.
        
        Returns proportion of foundational topics mastered.
        
        Returns:
            Gate readiness score (0-1)
        """
        
        gated_topics = ["UNIV_VAR", "UNIV_FUNC", "UNIV_COND", "UNIV_LOOP", "UNIV_COLL"]
        masteries = [self.current_mastery[t] for t in gated_topics]
        return float(np.mean(masteries))
    
    def decode_action(self, action: int) -> Tuple[str, float]:
        """
        Decode action ID into (topic, difficulty) pair.
        
        Args:
            action: Integer 0-39
        
        Returns:
            Tuple of (topic_name, difficulty_value)
        
        Example:
            >>> env.decode_action(17)
            ('UNIV_LOOP', 0.6)
        """
        topic_idx = action // 5
        difficulty_idx = action % 5
        return self.topics[topic_idx], self.difficulty_tiers[difficulty_idx]
    
    def encode_action(self, topic: str, difficulty: float) -> int:
        """
        Encode (topic, difficulty) pair into action ID.
        
        Args:
            topic: Topic name (e.g., 'UNIV_VAR')
            difficulty: Difficulty value (0.2, 0.4, 0.6, 0.8, or 1.0)
        
        Returns:
            Action ID (0-39)
        
        Example:
            >>> env.encode_action('UNIV_LOOP', 0.6)
            17
        """
        topic_idx = self.topics.index(topic)
        difficulty_idx = np.argmin(np.abs(self.difficulty_tiers - difficulty))
        return topic_idx * 5 + difficulty_idx
    
    def render(self):
        """
        Render the current state of the environment.
        
        In 'human' mode, prints current student state to console.
        """
        
        if self.render_mode == "human":
            print(f"\n{'='*70}")
            print(f"Step {self.step_count}/{self.max_steps}")
            print(f"{'='*70}")
            print(f"Student: {self.current_student.student_id} (rate={self.current_student.learning_rate:.2f})")
            print(f"\nMastery by Topic:")
            for topic, mastery in self.current_mastery.items():
                bar = '█' * int(mastery * 20)
                print(f"  {topic:12s} [{mastery:.2f}] {bar}")
            
            avg_mastery = np.mean(list(self.current_mastery.values()))
            print(f"\nAverage Mastery: {avg_mastery:.3f}")
            
            if self.episode_history:
                last = self.episode_history[-1]
                print(f"\nLast Action:")
                print(f"  Topic: {last['topic']} @ {last['difficulty']:.1f} difficulty")
                print(f"  Accuracy: {last['accuracy']:.1%}")
                print(f"  Mastery: {last['old_mastery']:.2f} → {last['new_mastery']:.2f}")
                print(f"  Reward: {last['reward']:.2f}")
            
            print(f"{'='*70}\n")
    
    def close(self):
        """Cleanup resources."""
        pass
    
    def get_episode_stats(self) -> Dict[str, Any]:
        """
        Get statistics for the current episode.
        
        Returns:
            Dictionary with episode statistics
        """
        if not self.episode_history:
            return {}
        
        rewards = [h["reward"] for h in self.episode_history]
        accuracies = [h["accuracy"] for h in self.episode_history]
        mastery_deltas = [h["new_mastery"] - h["old_mastery"] for h in self.episode_history]
        
        return {
            "total_steps": self.step_count,
            "total_reward": sum(rewards),
            "avg_reward": np.mean(rewards),
            "avg_accuracy": np.mean(accuracies),
            "avg_mastery_delta": np.mean(mastery_deltas),
            "final_avg_mastery": np.mean(list(self.current_mastery.values())),
            "gate_violations": sum(h["gate_violations"] for h in self.episode_history),
            "student_quit": any(h["gave_up"] for h in self.episode_history)
        }
