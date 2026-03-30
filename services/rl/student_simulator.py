"""
Student Simulator - Generates synthetic student behavior for RL training.

Creates diverse student profiles with different:
- Learning speeds (fast/average/slow learners)
- Starting knowledge (novice/intermediate)
- Preferences (some like challenges, others prefer easier)

This component generates unlimited training data since we have no historical sessions.
The simulator mimics the exact EMA formula and mastery updates from GradingService.
"""

import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.config import get_config

# Load universal mappings dynamically from curriculum
config = get_config()
UNIVERSAL_MAPPINGS = config.universal_mappings


@dataclass
class StudentProfile:
    """Represents a synthetic student's characteristics."""
    
    student_id: str
    learning_rate: float  # 0.5-2.0 (how fast they improve)
    initial_mastery: Dict[str, float]  # Starting knowledge per topic
    challenge_preference: float  # 0.0-1.0 (likes hard vs easy)
    consistency: float  # 0.5-1.0 (performance variance)
    dropout_threshold: float  # Quits if too frustrated
    
    # Behavioral traits
    focus_span: int  # Max topics before fatigue (10-25)
    optimal_accuracy_range: Tuple[float, float]  # Preferred success rate
    archetype: str = "beginner"  # P3 FIX: Student archetype for cross-episode conditioning
    current_language: str = "python_3"  # PHASE 1 FIX: Track language for difficulty modifiers
    
    # FIX #2: Error remediation tracking
    recent_errors: List[str] = field(default_factory=list)  # Last 10 error types made
    error_count_by_type: Dict[str, int] = field(default_factory=dict)  # Frequency of each error


class StudentSimulator:
    """
    Simulates student responses to teaching actions.
    
    This is the "environment" for offline RL training. It generates diverse
    student profiles and simulates their performance on exams, mimicking the
    real system's EMA formula for mastery updates.
    
    Key Features:
    - 100 diverse student profiles (20% fast, 60% average, 20% slow learners)
    - Realistic exam performance based on mastery-difficulty gap
    - Dropout behavior when students get frustrated
    - Learning rate variance (fast vs slow learners)
    - Matches real GradingService EMA formula
    
    Example:
        >>> sim = StudentSimulator(seed=42)
        >>> profile = sim.get_random_profile()
        >>> accuracy, time_ratio, gave_up = sim.simulate_exam_performance(
        ...     profile, "UNIV_VAR", difficulty=0.5, current_mastery=0.3
        ... )
        >>> new_mastery = sim.calculate_mastery_update(
        ...     profile, old_mastery=0.3, exam_accuracy=accuracy, difficulty=0.5
        ... )
    """
    
    def __init__(self, seed: int = 42):
        """
        Initialize simulator with diverse student profiles.
        
        Args:
            seed: Random seed for reproducibility
        """
        np.random.seed(seed)
        self.profiles = self._generate_diverse_profiles(num_students=100)
        
        # ═══════════════════════════════════════════════════════════════════
        # PRODUCTION ALIGNMENT: Load synergy and interdependency configs
        # ═══════════════════════════════════════════════════════════════════
        
        # Build synergy lookup from transition_map.json
        # Format: {trigger_mapping: [(target_mapping, bonus), ...]}
        self.synergy_map = {}
        for syn in config.transition_map.get('intra_language_synergy', []):
            trigger = syn['trigger_mapping_id']
            target = syn['target_mapping_id']
            bonus = syn['synergy_bonus']
            if trigger not in self.synergy_map:
                self.synergy_map[trigger] = []
            self.synergy_map[trigger].append((target, bonus))
        
        # Build concept interdependency lookup from concept_interdependencies_config.json
        # Format: {mapping: [(related_mapping, coefficient), ...]}
        self.interdep_map = {}
        import json
        interdep_path = Path(__file__).parent.parent.parent / 'core' / 'concept_interdependencies_config.json'
        try:
            with open(interdep_path, 'r', encoding='utf-8') as f:
                interdeps = json.load(f).get('concept_interdependencies', [])
            for dep in interdeps:
                a, b = dep['mapping_a'], dep['mapping_b']
                coef = dep['reinforcement_coefficient']
                # Bidirectional relationship
                self.interdep_map.setdefault(a, []).append((b, coef))
                self.interdep_map.setdefault(b, []).append((a, coef))
        except FileNotFoundError:
            self.interdep_map = {}  # Graceful fallback
        
        # Build soft gate lookup for graduated penalties
        # Format: {mapping: {prereqs: [...], steepness: float, min_score: float}}
        self.soft_gates = {}
        for gate in config.transition_map.get('soft_gates', []):
            mapping = gate['mapping_id']
            self.soft_gates[mapping] = {
                'prereqs': gate['prerequisite_mappings'],
                'steepness': gate.get('penalty_steepness', 2.0),
                'min_score': gate.get('minimum_allowable_score', 0.55)
            }
        
        # PHASE 1 FIX: Build language-specific difficulty modifier lookup
        # Format: {(language_id, mapping_id): multiplier}
        # Example: C++ variables are 1.4× harder, Python syntax 0.8× easier
        self.lang_difficulty_modifiers = {}
        for mod in config.transition_map.get('language_specific_modifiers', []):
            key = (mod['language_id'], mod['mapping_id'])
            self.lang_difficulty_modifiers[key] = mod['difficulty_multiplier']
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX #2: ERROR REMEDIATION - Load error taxonomy
        # ═══════════════════════════════════════════════════════════════════
        # Build error taxonomy lookup from transition_map.json
        # Format: {mapping_id: [{'error_type': str, 'severity': float, 'boost': float}, ...]}
        self.error_taxonomy = {}
        for category in config.transition_map.get('error_pattern_taxonomy', []):
            mapping_id = category.get('mapping_id')
            patterns = category.get('common_patterns', [])
            if mapping_id:
                self.error_taxonomy[mapping_id] = [
                    {
                        'error_type': p.get('error_type'),
                        'severity': p.get('severity', 0.5),
                        'remediation_boost': p.get('remediation_boost', 0.10)
                    }
                    for p in patterns
                ]
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX #3: CROSS-LANGUAGE TRANSFER - Load transfer coefficients
        # ═══════════════════════════════════════════════════════════════════
        # Build cross-language transfer lookup from transition_map.json
        # Format: {source_lang→target_lang: {logic_accel: float, syntax_friction: float}}
        self.cross_lang_transfer = {}
        for transfer in config.transition_map.get('cross_language_transfer', []):
            source = transfer.get('source_language_id')
            target = transfer.get('target_language_id')
            key = f"{source}_TO_{target}"
            self.cross_lang_transfer[key] = {
                'logic_accel': transfer.get('logic_acceleration', 0.7),
                'syntax_friction': transfer.get('syntax_friction', 0.0)
            }
        
        # Valid languages from curriculum
        self.languages = config.valid_languages
    
    def _generate_diverse_profiles(self, num_students: int) -> List[StudentProfile]:
        """
        Create diverse student archetypes for realistic training.
        
        Distribution:
        - 20% Fast learners (learning_rate > 1.5)
        - 60% Average learners (learning_rate 0.8-1.2)
        - 20% Slow learners (learning_rate < 0.8)
        
        Starting knowledge (OPTIMIZED FOR RL TRAINING):
        - 60% Complete beginners (mastery = 0.0-0.2) [easier to show improvement]
        - 25% Intermediate (mastery = 0.30-0.45) [moderate challenge]
        - 15% Advanced (mastery = 0.50-0.65) [hard but achievable]
        
        Args:
            num_students: Number of profiles to generate
        
        Returns:
            List of StudentProfile objects
        """
        profiles = []
        
        # Load experience level distributions from transition_map.json
        beginner_config = config.get_experience_config('beginner')
        intermediate_config = config.get_experience_config('intermediate')
        advanced_config = config.get_experience_config('advanced')
        
        for i in range(num_students):
            # Determine learning speed (normal distribution)
            learning_rate = np.clip(np.random.normal(1.0, 0.3), 0.5, 2.0)
            
            # ═══════════════════════════════════════════════════════════════════
            # FIX P1: Student Distribution - More beginners for easier improvement
            # ═══════════════════════════════════════════════════════════════════
            # Old: 30/40/30 (beginner/intermediate/advanced) - 70% couldn't improve
            # New: 60/25/15 - Most students start low, can show clear improvement
            # ═══════════════════════════════════════════════════════════════════
            
            if i < 60:  # 60% complete beginners (high improvement potential)
                # Start with 0-20% mastery - lots of room to grow
                initial_mastery = {
                    m: np.random.uniform(0.0, 0.20) for m in UNIVERSAL_MAPPINGS
                }
                archetype = "beginner"
            elif i < 85:  # 25% intermediate (moderate challenge)
                # Start with 30-45% mastery - still room for significant growth
                initial_mastery = {
                    m: np.random.uniform(0.30, 0.45) for m in UNIVERSAL_MAPPINGS
                }
                archetype = "intermediate"
            elif i < 95:  # 10% advanced (hard but achievable)
                # Start with 50-65% mastery - can still reach 60%+ goal
                initial_mastery = {
                    m: np.random.uniform(0.50, 0.65) for m in UNIVERSAL_MAPPINGS
                }
                archetype = "advanced"
            else:  # 5% true_advanced - matches production (initial_mastery_estimate=0.80)
                # Mirrors transition_map.json advanced profile:
                # assumed_mastered: SYN_LOGIC, SYN_PREC, VAR, COND, LOOP, FUNC, COLL → high mastery
                # Only OOP remains as the learning frontier
                easy_topics = [
                    "UNIV_SYN_LOGIC", "UNIV_SYN_PREC", "UNIV_VAR",
                    "UNIV_COND", "UNIV_LOOP", "UNIV_FUNC", "UNIV_COLL"
                ]
                initial_mastery = {
                    m: (np.random.uniform(0.75, 0.90) if m in easy_topics
                        else np.random.uniform(0.55, 0.75))
                    for m in UNIVERSAL_MAPPINGS
                }
                archetype = "advanced"
            
            # Challenge preference
            if learning_rate > 1.3:
                challenge_pref = np.random.uniform(0.6, 0.9)  # Fast learners like challenges
            else:
                challenge_pref = np.random.uniform(0.3, 0.6)  # Slow learners prefer easier
            
            # Consistency (how stable their performance is)
            consistency = np.random.uniform(0.6, 0.95)
            
            # Dropout threshold (frustration tolerance)
            # PHASE 2 FIX: Tighter range based on challenge_preference
            # Was 0.05-0.15 (3× variance), now 0.06-0.12 (2× variance)
            base_threshold = 0.08  # Median patience
            variance = challenge_pref * 0.02  # Risk-takers marginally more patient
            dropout_threshold = np.clip(
                base_threshold + np.random.uniform(-variance, variance),
                0.06,  # Minimum
                0.12   # Maximum
            )
            
            # Focus span (attention limit)
            focus_span = int(np.random.uniform(12, 22))
            
            # Optimal accuracy range (zone of proximal development)
            optimal_range = (
                np.random.uniform(0.35, 0.50),
                np.random.uniform(0.75, 0.90)
            )
            
            profiles.append(StudentProfile(
                student_id=f"sim-student-{i:03d}",
                learning_rate=learning_rate,
                initial_mastery=initial_mastery,
                challenge_preference=challenge_pref,
                consistency=consistency,
                dropout_threshold=dropout_threshold,
                focus_span=focus_span,
                optimal_accuracy_range=optimal_range,
                archetype=archetype  # P3 FIX: Store archetype for state conditioning
            ))
        
        return profiles
    
    def simulate_exam_performance(
        self,
        profile: StudentProfile,
        topic: str,
        difficulty: float,
        current_mastery: float,
        all_masteries: dict = None
    ) -> Tuple[float, float, bool]:
        """
        Simulate how a student performs on an exam.
        
        Models realistic behavior:
        - Students struggle on too-hard content (mastery << difficulty)
        - Students excel on too-easy content (mastery >> difficulty)
        - Optimal performance in zone of proximal development
        - Fast learners perform slightly better than mastery suggests
        - Performance has consistency-based variance
        - Students may quit if frustrated (accuracy < dropout_threshold)
        - CURRICULUM: Students struggle more when prerequisites unmet
        
        Args:
            profile: Student characteristics
            topic: Which universal mapping (UNIV_VAR, etc.)
            difficulty: Exam difficulty (0.3-1.0)
            current_mastery: Student's current mastery for THIS topic (0.0-1.0)
            all_masteries: Dict of all topic masteries (for prerequisite checking)
        
        Returns:
            Tuple of (accuracy, time_ratio, gave_up):
            - accuracy: 0.0-1.0 (percentage correct)
            - time_ratio: How fast compared to expected (0.5-2.5, where 1.0 is normal)
            - gave_up: True if student quit mid-exam due to frustration
        
        Example:
            >>> sim = StudentSimulator()
            >>> profile = sim.profiles[0]
            >>> accuracy, time, gave_up = sim.simulate_exam_performance(
            ...     profile, "UNIV_VAR", difficulty=0.5, current_mastery=0.3
            ... )
            >>> print(f"Accuracy: {accuracy:.2f}, Time: {time:.2f}x, Quit: {gave_up}")
        """
        
        # 1. Base accuracy (depends on mastery vs difficulty gap)
        # PHASE 1 FIX: Apply language-specific difficulty modifier
        lang_id = getattr(profile, 'current_language', 'python_3')
        modifier = self.lang_difficulty_modifiers.get((lang_id, topic), 1.0)
        effective_difficulty = difficulty * modifier
        
        mastery_gap = effective_difficulty - current_mastery
        
        # FIXED: Replaced cliff-edge thresholds with smooth sigmoid curve
        # Old approach had hard jumps (0.4x → 0.7x) that RL agents exploit
        # New approach: Smooth exponential decay based on difficulty gap
        
        # Sigmoid-like performance curve
        # When mastery_gap = 0 (perfect match): multiplier ≈ 0.9
        # When mastery_gap = 0.3 (moderately hard): multiplier ≈ 0.6
        # When mastery_gap = 0.5 (very hard): multiplier ≈ 0.4
        # When mastery_gap = -0.2 (too easy): multiplier ≈ 1.0 (ceiling)
        
        import math
        
        # FIX: Add guessing baseline (25% for 4-option MCQ)
        # Scale the remaining 75% based on mastery and difficulty
        guessing_floor = 0.25
        
        if mastery_gap <= 0:
            # Content is easier than mastery - high performance with ceiling
            performance_multiplier = min(0.95 + mastery_gap * 0.2, 1.0)
            base_accuracy = guessing_floor + (current_mastery * performance_multiplier * 0.75)
        else:
            # Content is harder than mastery - smooth decay
            # Sigmoid: 1 / (1 + e^(k*gap)), with k=5 for steepness
            smooth_factor = 1.0 / (1.0 + math.exp(mastery_gap * 5))
            # Map sigmoid to reasonable performance range (0.3 to 0.95)
            performance_multiplier = 0.3 + smooth_factor * 0.65
            base_accuracy = guessing_floor + (current_mastery * performance_multiplier * 0.75)
        
        # 2. Apply learning rate modifier
        # Fast learners perform slightly better than mastery suggests
        accuracy_modifier = (profile.learning_rate - 1.0) * 0.1
        base_accuracy += accuracy_modifier
        
        # 3. Add consistency noise
        # Low consistency = high variance in performance
        noise = np.random.normal(0, (1 - profile.consistency) * 0.15)
        actual_accuracy = np.clip(base_accuracy + noise, 0.0, 1.0)
        
        # 3.5. CURRICULUM CONSTRAINT: Penalize performance if prerequisites unmet
        # Student struggles significantly when learning advanced topics without foundation
        gate_info = self.get_soft_gate_info(topic)
        frustration_bonus = 0.0
        difficulty_slowdown_bonus = 1.0
        
        if gate_info and all_masteries:
            prereqs = gate_info.get('prereqs', [])
            min_score = gate_info.get('min_score', 0.55)
            
            if prereqs:
                # Calculate how many prerequisites are unmet
                unmet_prereqs = sum(1 for prereq in prereqs 
                                   if prereq in all_masteries and all_masteries[prereq] < min_score)
                prereq_readiness = 1.0 - (unmet_prereqs / len(prereqs))  # 0.0 to 1.0
                
                if prereq_readiness < 0.8:  # Less than 80% of prereqs met
                    # Student performs worse (50-100% of expected accuracy)
                    actual_accuracy *= (0.5 + 0.5 * prereq_readiness)
                    # Takes more time (100-150% of normal time)
                    difficulty_slowdown_bonus = 1.0 + 0.5 * (1.0 - prereq_readiness)
                    # Gets more frustrated faster
                    frustration_bonus = 0.3 * (1.0 - prereq_readiness)
        
        # 4. Check for dropout (frustration quit)
        # ═══════════════════════════════════════════════════════════════════
        # FIX P3: Psychological dropout based on PERCEIVED difficulty
        # ═══════════════════════════════════════════════════════════════════
        # Old: Only quit if accuracy < 15% (never happens with 25% guessing floor)
        # New: Quit based on frustration = difficulty gap + repeated failures
        # ═══════════════════════════════════════════════════════════════════
        gave_up = False
        
        # Calculate frustration level (0-1 scale)
        # High frustration when: difficulty >> mastery AND low accuracy
        frustration = frustration_bonus  # Start with prerequisite frustration
        if mastery_gap > 0.2:  # Content significantly harder than mastery
            frustration += mastery_gap * 0.5  # Base frustration from difficulty gap
        if actual_accuracy < 0.4:  # Struggling (even with guessing)
            frustration += (0.4 - actual_accuracy) * 0.5
        if actual_accuracy < current_mastery * 0.7:  # Performing below expectations
            frustration += 0.2
        
        # Dropout probability based on frustration and student tolerance
        # Higher frustration + lower tolerance = more likely to quit
        dropout_prob = frustration * (1.0 - profile.dropout_threshold * 2)
        dropout_prob = np.clip(dropout_prob, 0.0, 0.5)  # Cap at 50%
        
        if dropout_prob > 0.1 and np.random.random() < dropout_prob:
            gave_up = True
            actual_accuracy *= 0.5  # Incomplete exam, poor performance
        
        # 5. Time ratio (speed)
        # Fast learners are quicker, difficult exams take longer
        base_time_ratio = 1.0 / profile.learning_rate
        difficulty_slowdown = 1.0 + (mastery_gap * 0.5) if mastery_gap > 0 else 1.0
        difficulty_slowdown *= difficulty_slowdown_bonus  # Apply prerequisite penalty
        
        time_ratio = base_time_ratio * difficulty_slowdown
        time_ratio = np.clip(time_ratio, 0.5, 2.0)
        
        # Add noise to time
        time_ratio += np.random.normal(0, 0.1)
        time_ratio = np.clip(time_ratio, 0.5, 2.5)
        
        return actual_accuracy, time_ratio, gave_up
    
    def generate_error_type(self, topic: str, is_correct: bool, difficulty: float) -> str:
        """
        Generate error type for incorrect answers (FIX #2: Error Remediation).
        
        Simulates realistic error patterns based on topic and difficulty.
        Higher difficulty = more likely to generate severe errors.
        
        Args:
            topic: Universal mapping ID (e.g., 'UNIV_LOOP')
            is_correct: Whether answer was correct
            difficulty: Question difficulty (0.3-1.0)
        
        Returns:
            Error type string (e.g., 'OFF_BY_ONE_ERROR') or None if correct
        
        Example:
            >>> sim = StudentSimulator()
            >>> error = sim.generate_error_type('UNIV_LOOP', False, 0.7)
            >>> print(error)  # Might be 'OFF_BY_ONE_ERROR' or 'INFINITE_LOOP'
        """
        if is_correct:
            return None
        
        # Get error patterns for this topic
        patterns = self.error_taxonomy.get(topic, [])
        
        if not patterns:
            # No taxonomy defined for this topic - return generic error
            return 'UNKNOWN_ERROR'
        
        # Weight error selection by severity and difficulty
        # Harder questions tend to produce more severe errors
        weights = []
        for pattern in patterns:
            severity = pattern['severity']
            # Harder questions → more severe errors weighted higher
            weight = severity if difficulty > 0.6 else (1.0 - severity)
            weights.append(weight)
        
        # Normalize weights
        total_weight = sum(weights)
        if total_weight == 0:
            return patterns[0]['error_type']
        
        weights = [w / total_weight for w in weights]
        
        # Randomly select error type based on weights
        selected_idx = np.random.choice(len(patterns), p=weights)
        return patterns[selected_idx]['error_type']
    
    def calculate_remediation_bonus(
        self,
        profile: StudentProfile,
        topic: str,
        is_correct: bool,
        error_type: str = None
    ) -> float:
        """
        Calculate mastery bonus for fixing previous errors (FIX #2).
        
        Matches production GradingService._calculate_error_remediation_bonus().
        When student answers correctly on a topic they previously failed,
        they get an extra mastery boost (0.08-0.18 depending on error severity).
        
        Args:
            profile: Student with error history
            topic: Current topic
            is_correct: Whether current answer is correct
            error_type: Type of error (if incorrect)
        
        Returns:
            Remediation bonus (0.0-0.18), capped at 0.15 total
        
        Example:
            >>> profile.recent_errors = ['TYPE_MISMATCH', 'INDENTATION_ERROR']
            >>> bonus = sim.calculate_remediation_bonus(profile, 'UNIV_VAR', True, None)
            >>> print(f'Bonus: +{bonus:.3f}')  # Might be +0.15 if fixed TYPE_MISMATCH
        """
        if not is_correct:
            # Track new error
            if error_type and error_type not in profile.recent_errors:
                profile.recent_errors.append(error_type)
                # Keep only last 10 errors
                if len(profile.recent_errors) > 10:
                    profile.recent_errors.pop(0)
                # Increment error count
                profile.error_count_by_type[error_type] = profile.error_count_by_type.get(error_type, 0) + 1
            return 0.0
        
        # Student answered correctly - check if they fixed a previous error
        if not profile.recent_errors:
            return 0.0
        
        total_bonus = 0.0
        patterns = self.error_taxonomy.get(topic, [])
        
        # Check if any recent errors are from this topic
        for prev_error in profile.recent_errors[-5:]:  # Check last 5 errors
            # Find remediation boost for this error type
            for pattern in patterns:
                if pattern['error_type'] == prev_error:
                    # Student fixed this error!
                    total_bonus += pattern['remediation_boost']
                    # Remove from recent errors (fixed)
                    if prev_error in profile.recent_errors:
                        profile.recent_errors.remove(prev_error)
                    break
        
        # Cap total bonus at 0.15 (matches production)
        return min(total_bonus, 0.15)
    
    def calculate_cross_language_boost(
        self,
        source_language: str,
        target_language: str,
        source_mastery: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Calculate initial mastery boost when learning a new language (FIX #3).
        
        Matches production GradingService._apply_cross_language_transfer().
        When student has mastered concepts in one language, learning the same
        concepts in another language is accelerated.
        
        Example:
            Student knows Python: {UNIV_VAR: 0.8, UNIV_FUNC: 0.7}
            Switching to JavaScript (logic_accel=0.88, syntax_friction=-0.15)
            → JS initial: {UNIV_VAR: 0.8*0.88-0.15=0.554, UNIV_FUNC: 0.7*0.88-0.15=0.466}
        
        Args:
            source_language: Language student already knows (e.g., 'python_3')
            target_language: Language student is learning (e.g., 'javascript_es6')
            source_mastery: Mastery in source language {mapping_id: score}
        
        Returns:
            Initial mastery for target language with transfer applied
        
        Example:
            >>> sim = StudentSimulator()
            >>> python_mastery = {'UNIV_VAR': 0.8, 'UNIV_FUNC': 0.7}
            >>> js_mastery = sim.calculate_cross_language_boost(
            ...     'python_3', 'javascript_es6', python_mastery
            ... )
            >>> print(f\"Transferred mastery: {js_mastery['UNIV_VAR']:.3f}\")
        """
        transfer_key = f"{source_language}_TO_{target_language}"
        
        if transfer_key not in self.cross_lang_transfer:
            # No transfer data defined - start from scratch
            return {mapping: 0.0 for mapping in UNIVERSAL_MAPPINGS}
        
        transfer_coeffs = self.cross_lang_transfer[transfer_key]
        logic_accel = transfer_coeffs['logic_accel']
        syntax_friction = transfer_coeffs['syntax_friction']
        
        # Apply transfer formula: new = old * logic_acceleration + syntax_friction
        # This matches production exactly (grading_service.py lines 505-510)
        target_mastery = {}
        for mapping_id in UNIVERSAL_MAPPINGS:
            source_score = source_mastery.get(mapping_id, 0.0)
            # Only transfer if student has meaningful mastery (>0.3)
            if source_score > 0.3:
                transferred = source_score * logic_accel + syntax_friction
                target_mastery[mapping_id] = max(0.0, min(1.0, transferred))
            else:
                target_mastery[mapping_id] = 0.0
        
        return target_mastery
    
    def calculate_mastery_update(
        self,
        profile: StudentProfile,
        old_mastery: float,
        exam_accuracy: float,
        difficulty: float,
        fluency_ratio: float = 1.0,
        topic: str = None,
        error_type: str = None
    ) -> float:
        """
        Simulate how mastery changes after exam (mimics EMA formula).
        
        CRITICAL: This MUST match the real system's GradingService formula:
        - Base formula: new = old * retention_weight + performance * innovation_weight
        - Real system uses: retention=0.7, innovation=0.3
        - Simulator adds learning_rate modifier for diversity
        - NEW: High-velocity detection for adaptive EMA weights (matches production)
        - NEW: Error remediation bonuses (FIX #2 - matches production)
        
        For average students (learning_rate=1.0), this produces identical results
        to the real system. For fast/slow learners, innovation weight is adjusted.
        
        Formula:
            performance = exam_accuracy * (0.5 + difficulty * 0.5)
            innovation_weight = 0.3 * learning_rate (capped)
            retention_weight = 1.0 - innovation_weight
            new_mastery = old * retention + performance * innovation + remediation_bonus
        
        Args:
            profile: Student characteristics
            old_mastery: Mastery before exam
            exam_accuracy: Performance on exam (0.0-1.0)
            difficulty: Exam difficulty (0.3-1.0)
            fluency_ratio: Speed efficiency (1.0 = normal, >1.0 = faster)
            topic: Universal mapping ID (for error remediation)
            error_type: Error type if incorrect (for error tracking)
        
        Returns:
            New mastery score (0.0-1.0)
        
        Example:
            >>> sim = StudentSimulator()
            >>> avg_student = sim.profiles[50]  # Average learning_rate ≈ 1.0
            >>> new_mastery = sim.calculate_mastery_update(
            ...     avg_student, old_mastery=0.5, exam_accuracy=0.75, difficulty=0.6
            ... )
            >>> print(f"Mastery: 0.50 → {new_mastery:.3f}")
        """
        
        # Performance score (weighted by difficulty)
        # This matches GradingService exactly
        performance = exam_accuracy * (0.5 + difficulty * 0.5)
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX #1: HIGH-VELOCITY LEARNER DETECTION (Matches production)
        # ═══════════════════════════════════════════════════════════════════
        # Production code (grading_service.py lines 248-254):
        # is_high_velocity = (accuracy > 0.9 and fluency > 1.2 and difficulty > 0.6)
        # if is_high_velocity:
        #     retention = 0.5  # Less weight on old scores
        #     innovation = 0.5  # More weight on new performance
        # ═══════════════════════════════════════════════════════════════════
        
        is_high_velocity = (
            exam_accuracy > 0.9 and 
            fluency_ratio > 1.2 and 
            difficulty > 0.6
        )
        
        if is_high_velocity:
            # High performers learn FASTER (matches production exactly)
            retention = 0.5
            innovation = 0.5
        else:
            # Normal students: use learning_rate modifier
            # learning_rate=1.0 → innovation=0.3 (matches real system)
            # learning_rate=1.5 → innovation=0.45 (fast learner)
            # learning_rate=0.7 → innovation=0.21 (slow learner)
            base_innovation = 0.3 * profile.learning_rate
            
            # Cap innovation weight at reasonable bounds (0.15 to 0.5)
            innovation = np.clip(base_innovation, 0.15, 0.5)
            retention = 1.0 - innovation
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX #2: ASYMMETRIC EMA UPDATE (Existing logic, now combined with velocity)
        # ═══════════════════════════════════════════════════════════════════
        # Problem: Standard EMA causes high-mastery students to DECLINE
        # because they need >80% accuracy just to maintain 80% mastery.
        #
        # Solution: Asymmetric update rules:
        # - If student EXCEEDS current mastery → reward with growth bonus
        # - If student MATCHES current mastery → maintain (no penalty)
        # - If student STRUGGLES → protect existing knowledge (reduced decay)
        # ═══════════════════════════════════════════════════════════════════
        
        if exam_accuracy >= old_mastery:
            # ✅ CASE 1: Student performed AT OR ABOVE their level
            # Use the retention/innovation weights determined above (velocity-aware)
            new_mastery = old_mastery * retention + performance * innovation
            
            # Growth bonus: Extra reward for exceeding current mastery
            # This ensures high-mastery students CAN still improve
            growth_bonus = (exam_accuracy - old_mastery) * 0.15
            new_mastery += growth_bonus
            
        elif exam_accuracy >= old_mastery * 0.75:
            # ⚠️ CASE 2: Student struggled but stayed within 75% of their level
            # Reduced innovation rate to protect existing mastery
            # "Bad day" shouldn't erase learned knowledge
            reduced_innovation = innovation * 0.3  # 70% reduction
            reduced_retention = 1.0 - reduced_innovation
            new_mastery = old_mastery * reduced_retention + performance * reduced_innovation
            
        else:
            # 🛡️ CASE 3: Severe struggle (accuracy < 75% of mastery)
            # Content was way too hard - protect existing mastery heavily
            # Minimal decay, student shouldn't be penalized for bad content selection
            minimal_innovation = innovation * 0.1  # 90% reduction
            minimal_retention = 1.0 - minimal_innovation
            new_mastery = old_mastery * minimal_retention + performance * minimal_innovation
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX #2: ERROR REMEDIATION BONUS (Matches production)
        # ═══════════════════════════════════════════════════════════════════
        # If student fixed a previous error, apply remediation boost (+0.08 to +0.18)
        # Matches production GradingService lines 262-263
        # ═══════════════════════════════════════════════════════════════════
        
        remediation_bonus = 0.0
        if topic:
            is_correct = exam_accuracy >= 0.5  # Simplified: >50% accuracy = "correct"
            remediation_bonus = self.calculate_remediation_bonus(
                profile, topic, is_correct, error_type
            )
            new_mastery += remediation_bonus
        
        # Add small noise for realism
        new_mastery += np.random.normal(0, 0.01)
        
        return np.clip(new_mastery, 0.0, 1.0)
    
    def apply_synergy_bonuses(
        self,
        topic: str,
        current_mastery: Dict[str, float],
        exam_accuracy: float
    ) -> Dict[str, float]:
        """
        Apply synergy bonuses to related topics (matches production GradingService._apply_synergy).
        
        In production, when a student performs well (accuracy >= 70%) on a topic,
        related topics get a small mastery boost. This is loaded from transition_map.json.
        
        Example synergies:
        - UNIV_LOOP triggers +0.08 to UNIV_COND
        - UNIV_FUNC triggers +0.10 to UNIV_VAR
        
        Args:
            topic: Topic that was practiced
            current_mastery: Current mastery scores for all topics
            exam_accuracy: Performance on the exam
        
        Returns:
            Updated mastery dictionary with synergy bonuses applied
        """
        # Only apply synergies if accuracy >= 70% (like production)
        if exam_accuracy < 0.70:
            return current_mastery
        
        updated = current_mastery.copy()
        
        # Apply synergy bonuses from config
        synergies = self.synergy_map.get(topic, [])
        for target_topic, bonus in synergies:
            if target_topic in updated:
                updated[target_topic] = min(updated[target_topic] + bonus, 1.0)
        
        return updated
    
    def apply_concept_interdependencies(
        self,
        topic: str,
        current_mastery: Dict[str, float],
        new_mastery: float
    ) -> Dict[str, float]:
        """
        Apply bidirectional concept reinforcement (matches production GradingService._apply_concept_interdependencies).
        
        When mastery improves in one topic, related topics get a small boost based on
        the reinforcement_coefficient from concept_interdependencies_config.json.
        
        Example interdependencies:
        - UNIV_LOOP ↔ UNIV_COND (coefficient: 0.10)
        - UNIV_OOP ↔ UNIV_FUNC (coefficient: 0.12)
        
        Args:
            topic: Topic that was practiced
            current_mastery: Current mastery scores for all topics
            new_mastery: New mastery value for the practiced topic
        
        Returns:
            Updated mastery dictionary with interdependency boosts applied
        """
        updated = current_mastery.copy()
        
        # Get interdependencies for this topic
        interdeps = self.interdep_map.get(topic, [])
        
        for related_topic, coefficient in interdeps:
            if related_topic in updated:
                # Boost = new_mastery * coefficient * 0.1 (scaled down like production)
                boost = new_mastery * coefficient * 0.1
                updated[related_topic] = min(updated[related_topic] + boost, 1.0)
        
        return updated
    
    def get_soft_gate_info(self, topic: str) -> Dict:
        """
        Get soft gate configuration for a topic.
        
        Returns prereq info and penalty steepness from transition_map.json soft_gates.
        
        Args:
            topic: Universal mapping ID (e.g., UNIV_FUNC)
        
        Returns:
            Dict with prereqs, steepness, min_score, or None if no gate
        """
        return self.soft_gates.get(topic)
    
    def get_random_profile(self) -> StudentProfile:
        """
        Get random student profile for training episode.
        
        Returns:
            Randomly selected StudentProfile from the 100 generated profiles
        
        Example:
            >>> sim = StudentSimulator()
            >>> profile = sim.get_random_profile()
            >>> print(f"Student: {profile.student_id}, Rate: {profile.learning_rate:.2f}")
        """
        return np.random.choice(self.profiles)
    
    def get_profile_by_index(self, index: int) -> StudentProfile:
        """
        Get specific student profile by index.
        
        Useful for evaluation with consistent test set.
        
        Args:
            index: Profile index (0-99)
        
        Returns:
            StudentProfile at given index
        
        Example:
            >>> sim = StudentSimulator()
            >>> fast_learner = sim.get_profile_by_index(0)  # First profile
            >>> slow_learner = sim.get_profile_by_index(99)  # Last profile
        """
        return self.profiles[index]
    
    def get_profile_stats(self) -> Dict[str, any]:
        """
        Get statistics about the generated student population.
        
        Returns:
            Dictionary with profile statistics
        
        Example:
            >>> sim = StudentSimulator()
            >>> stats = sim.get_profile_stats()
            >>> print(f"Avg learning rate: {stats['avg_learning_rate']:.2f}")
        """
        learning_rates = [p.learning_rate for p in self.profiles]
        challenge_prefs = [p.challenge_preference for p in self.profiles]
        consistencies = [p.consistency for p in self.profiles]
        
        return {
            'num_profiles': len(self.profiles),
            'avg_learning_rate': np.mean(learning_rates),
            'std_learning_rate': np.std(learning_rates),
            'min_learning_rate': np.min(learning_rates),
            'max_learning_rate': np.max(learning_rates),
            'avg_challenge_preference': np.mean(challenge_prefs),
            'avg_consistency': np.mean(consistencies),
            'fast_learners': sum(1 for lr in learning_rates if lr > 1.3),
            'slow_learners': sum(1 for lr in learning_rates if lr < 0.8),
        }
