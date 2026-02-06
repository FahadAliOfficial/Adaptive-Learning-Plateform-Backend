"""
State Vector Generator - Creates RL-compatible state representations (SCENARIO A).
Implements the "Vision" part of the RL system.
"""

import numpy as np
import math
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Dict, List, Tuple
import logging

from .schemas import StateVectorRequest, StateVectorResponse
from .config import get_config

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class StateVectorGenerator:
    """
    Generates fixed-size state vectors for RL model consumption.
    
    State Vector Structure (DYNAMIC based on curriculum):
    Default with 5 languages & 8 mappings = 35 dimensions:
    [lang_offset : lang_offset+5]         Language One-Hot Encoding
    [mastery_offset : mastery_offset+8]   Mastery Scores with Decay
    [fluency_offset : fluency_offset+8]   Fluency Scores
    [confidence_offset : confidence_offset+8] Confidence Scores
    [behavioral_offset : behavioral_offset+8] Behavioral Metrics:
        [0] Last Session Accuracy
        [1] Last Session Difficulty
        [2] Average Fluency Ratio
        [3] Mastery Stability (Std Dev)
        [4] Days Since Last Practice
        [5] Soft Gate Readiness
        [6] Session Confidence (Cold-Start Signal: smooth 0→1 based on total exams)
        [7] Performance Velocity (Fast Learner Detection: 1.0 if high accuracy + fluency + difficulty)
    
    Formula: vector_size = num_languages + (num_mappings × 3) + 8
    All indices calculated dynamically - NO hardcoded positions!
    
    Additional metadata includes:
    - Prerequisites satisfaction status
    - Cross-language transfer potential
    - Recent error patterns
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
        
        # Universal mappings in order (DYNAMIC from curriculum!)
        self.mappings_order = self.config.universal_mappings
        
        # Language encoding order (DYNAMIC from curriculum!)
        self.languages_order = list(self.config.valid_languages)
        
        # Decay rate (from transition_map config, NOT hardcoded!)
        self.lambda_decay = self.config.get_decay_rate()
        
        # Vector dimension calculation (DYNAMIC - adapts to curriculum changes!)
        # Structure: language_onehot + (mappings × 3 scores) + 9 behavioral metrics (includes cold-start + adaptive difficulty)
        self.vector_size = len(self.languages_order) + (len(self.mappings_order) * 3) + 9
        
        # Calculate index offsets dynamically (prevents corruption on curriculum changes!)
        self.lang_offset = 0
        self.mastery_offset = len(self.languages_order)
        self.fluency_offset = len(self.languages_order) + len(self.mappings_order)
        self.confidence_offset = len(self.languages_order) + (len(self.mappings_order) * 2)
        self.behavioral_offset = len(self.languages_order) + (len(self.mappings_order) * 3)
    
    def generate_vector(self, request: StateVectorRequest) -> StateVectorResponse:
        """
        Main entry point for state vector generation.
        Returns fixed-size numpy array ready for RL model.
        """
        user_id = request.user_id
        language_id = request.language_id
        
        logger.info(f"[StateVector] Starting generation for user {user_id[:8]}... language {language_id}")
        
        # Validate language_id exists in curriculum
        if language_id not in self.config.valid_languages:
            logger.error(f"[StateVector] Invalid language_id: {language_id}")
            raise ValueError(
                f"Invalid language_id: {language_id}. "
                f"Valid languages: {sorted(self.config.valid_languages)}"
            )
        
        # Initialize vector (dynamic dimensions based on curriculum)
        logger.debug(f"[StateVector] Initializing vector with {self.vector_size} dimensions")
        vector = np.zeros(self.vector_size, dtype=np.float32)
        
        # 1. Language One-Hot Encoding [lang_offset : lang_offset + num_languages]
        logger.debug(f"[StateVector] Step 1: Language encoding")
        lang_idx = self.languages_order.index(language_id)
        vector[self.lang_offset + lang_idx] = 1.0
        
        # 2. Decayed Mastery Scores [mastery_offset : mastery_offset + num_mappings]
        logger.debug(f"[StateVector] Step 2: Fetching mastery scores")
        mastery_map = self._get_decayed_mastery(user_id, language_id)
        logger.debug(f"[StateVector] Got {len(mastery_map)} mastery scores")
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.mastery_offset + i] = mastery_map.get(mapping_id, 0.0)
        
        # 3. Fluency Scores [fluency_offset : fluency_offset + num_mappings]
        logger.debug(f"[StateVector] Step 3: Fetching fluency scores")
        fluency_map = self._get_fluency_scores(user_id, language_id)
        logger.debug(f"[StateVector] Got {len(fluency_map)} fluency scores")
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.fluency_offset + i] = fluency_map.get(mapping_id, 1.0)  # Default to normal speed
        
        # 4. Confidence Scores [confidence_offset : confidence_offset + num_mappings]
        logger.debug(f"[StateVector] Step 4: Fetching confidence scores")
        confidence_map = self._get_confidence_scores(user_id, language_id)
        logger.debug(f"[StateVector] Got {len(confidence_map)} confidence scores")
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.confidence_offset + i] = confidence_map.get(mapping_id, 0.0)
        
        # 5. Behavioral Metrics [behavioral_offset : behavioral_offset + 9] (includes cold-start + Phase 2B adaptive difficulty)
        logger.debug(f"[StateVector] Step 5: Calculating behavioral metrics")
        try:
            metrics = self._get_behavioral_metrics(user_id, language_id)
            logger.debug(f"[StateVector] Metrics: {metrics}")
        except Exception as e:
            logger.error(f"[StateVector] ERROR in behavioral metrics: {type(e).__name__}: {str(e)}")
            raise
        vector[self.behavioral_offset + 0] = metrics['last_accuracy']
        vector[self.behavioral_offset + 1] = metrics['last_difficulty']
        vector[self.behavioral_offset + 2] = metrics['avg_fluency']
        vector[self.behavioral_offset + 3] = metrics['stability']
        vector[self.behavioral_offset + 4] = metrics['days_inactive']
        vector[self.behavioral_offset + 5] = metrics['gate_readiness']
        vector[self.behavioral_offset + 6] = metrics['session_confidence']  # Cold-start signal
        vector[self.behavioral_offset + 7] = metrics['performance_velocity']  # Fast learner detection
        vector[self.behavioral_offset + 8] = metrics['adaptive_difficulty']  # Phase 2B: Recommended next difficulty
        
        # 6. Generate rich metadata (prerequisites, transfer potential, errors)
        logger.debug(f"[StateVector] Step 6: Generating metadata")
        try:
            metadata = self._generate_metadata(vector, user_id, language_id, mastery_map)
            logger.debug(f"[StateVector] Metadata generated successfully")
        except Exception as e:
            logger.error(f"[StateVector] ERROR in metadata generation: {type(e).__name__}: {str(e)}")
            raise
        
        logger.info(f"[StateVector] Successfully generated {len(vector)} dimension vector")
        
        return StateVectorResponse(
            state_vector=vector.tolist(),
            metadata=metadata
        )
    
    def _get_decayed_mastery(self, user_id: str, language_id: str) -> Dict[str, float]:
        """
        Fetch mastery scores and apply exponential time decay.
        
        Formula: Decayed = Original * e^(-λ * days_passed)
        where λ = decay_rate_per_day from transition_map
        """
        query = text("""
            SELECT mapping_id, mastery_score, last_practiced_at 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l
        """)
        
        rows = self.db.execute(query, {"u": user_id, "l": language_id}).fetchall()
        
        decayed_scores = {}
        now = datetime.now(timezone.utc)
        
        for row in rows:
            mapping_id, score, last_date = row
            
            # Parse datetime if it's a string (SQLite compatibility)
            if isinstance(last_date, str):
                last_date = datetime.fromisoformat(last_date.replace('Z', '+00:00'))
            
            # Calculate days passed
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            days_passed = (now - last_date).days
            
            # Apply exponential decay
            decay_factor = math.exp(-self.lambda_decay * days_passed)
            decayed_value = score * decay_factor
            
            decayed_scores[mapping_id] = max(decayed_value, 0.0)
        
        return decayed_scores
    
    def _get_fluency_scores(self, user_id: str, language_id: str) -> Dict[str, float]:
        """Fetch fluency scores (speed/efficiency) per topic."""
        query = text("""
            SELECT mapping_id, fluency_score 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l
        """)
        
        rows = self.db.execute(query, {"u": user_id, "l": language_id}).fetchall()
        return {row[0]: row[1] for row in rows}
    
    def _get_confidence_scores(self, user_id: str, language_id: str) -> Dict[str, float]:
        """Fetch confidence scores (stability of mastery) per topic."""
        query = text("""
            SELECT mapping_id, confidence_score 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l
        """)
        
        rows = self.db.execute(query, {"u": user_id, "l": language_id}).fetchall()
        return {row[0]: row[1] for row in rows}
    
    def _get_behavioral_metrics(self, user_id: str, language_id: str) -> Dict[str, float]:
        """
        Calculate behavioral metrics from recent session history.
        
        Returns:
        - last_accuracy: Accuracy from most recent session
        - last_difficulty: Difficulty from most recent session
        - avg_fluency: Average fluency across all topics
        - stability: Inverse of score variance (high = consistent performance)
        - days_inactive: Days since last practice in this language
        - gate_readiness: % of soft gate prerequisites met
        - session_confidence: Cold-start signal (0.0 = new user, 1.0 = experienced)
        - performance_velocity: Fast learner detection (1.0 if high accuracy + fluency + difficulty)
        - adaptive_difficulty: Phase 2B - Recommended difficulty for next session (0.3-1.0)
        """
        
        # Last session stats (Phase 2B: includes recommended_next_difficulty)
        last_session_query = text("""
            SELECT overall_score, difficulty_assigned, time_taken_seconds, created_at, recommended_next_difficulty
            FROM exam_sessions 
            WHERE user_id=:u AND language_id=:l AND session_status = 'completed'
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        last_session = self.db.execute(last_session_query, {"u": user_id, "l": language_id}).fetchone()
        
        if last_session:
            last_accuracy = last_session[0]
            last_difficulty = last_session[1]
            last_date = last_session[3]
            adaptive_difficulty = last_session[4] or 0.5  # Default to 0.5 if NULL
            
            # Parse datetime if it's a string (SQLite compatibility)
            if isinstance(last_date, str):
                last_date = datetime.fromisoformat(last_date.replace('Z', '+00:00'))
            
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            days_inactive = (datetime.now(timezone.utc) - last_date).days
        else:
            last_accuracy = 0.0
            last_difficulty = 0.5
            days_inactive = 999  # Never practiced
            adaptive_difficulty = 0.5  # Default beginner-intermediate
        
        # Average fluency
        fluency_query = text("""
            SELECT AVG(fluency_score) 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l
        """)
        avg_fluency = self.db.execute(fluency_query, {"u": user_id, "l": language_id}).scalar() or 1.0
        
        # Stability (consistency of recent scores)
        stability_query = text("""
            SELECT overall_score 
            FROM exam_sessions 
            WHERE user_id=:u AND language_id=:l AND session_status = 'completed'
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_scores = [row[0] for row in self.db.execute(stability_query, {"u": user_id, "l": language_id})]
        
        if len(recent_scores) >= 2:
            score_std = np.std(recent_scores)
            stability = max(0.0, 1.0 - score_std)  # Higher std = lower stability
        else:
            stability = 0.5  # Neutral for new users
        
        # Gate readiness (average mastery of topics with gates)
        gate_readiness = self._calculate_gate_readiness(user_id, language_id)
        
        # COLD-START SIGNALS: Fetch total exams taken (O(1) counter, not COUNT(*))
        total_exams_query = text("""
            SELECT total_exams_taken 
            FROM users 
            WHERE id = :u
        """)
        total_exams = self.db.execute(total_exams_query, {"u": user_id}).scalar() or 0
        
        # Session Confidence: Smooth decay (avoids binary cliff at session 3)
        # Formula: 1 - 1/(n+1) → 0 exams=0.0, 1 exam=0.5, 9 exams=0.9, 99 exams=0.99
        session_confidence = 1.0 - (1.0 / (total_exams + 1))
        
        # Performance Velocity: Detect if last session was high-velocity
        # (Will be recalculated in real-time during next exam processing)
        is_high_velocity = (last_accuracy > 0.9 and last_difficulty > 0.6)
        performance_velocity = 1.0 if is_high_velocity else 0.0
        
        return {
            'last_accuracy': round(last_accuracy, 3),
            'last_difficulty': round(last_difficulty, 3),
            'avg_fluency': round(avg_fluency, 2),
            'stability': round(stability, 3),
            'days_inactive': min(days_inactive, 30),  # Cap for normalization
            'gate_readiness': round(gate_readiness, 3),
            'session_confidence': round(session_confidence, 3),  # NEW: Cold-start signal
            'performance_velocity': round(performance_velocity, 1),  # Fast learner flag
            'adaptive_difficulty': round(adaptive_difficulty, 3)  # Phase 2B: Next recommended difficulty
        }
    
    def _calculate_gate_readiness(self, user_id: str, language_id: str) -> float:
        """
        Calculate how ready user is to pass soft gates.
        Uses WEIGHTED AVERAGE of prerequisite mastery (not simple average).
        """
        gates = self.config.transition_map['soft_gates']
        if not gates:
            return 1.0  # No gates = always ready
        
        readiness_scores = []
        
        for gate in gates:
            prereqs = gate['prerequisite_mappings']
            min_required = gate['minimum_allowable_score']
            
            # Get prerequisite weights (defaults to equal if not defined)
            weights = gate.get('prerequisite_strength_weights', [1.0] * len(prereqs))
            
            if len(weights) != len(prereqs):
                # Fallback to equal weights if mismatch
                weights = [1.0] * len(prereqs)
            
            # Fetch mastery scores for each prerequisite
            # Build IN clause dynamically for SQLite compatibility
            placeholders = ','.join([f':p{i}' for i in range(len(prereqs))])
            query = text(f"""
                SELECT mapping_id, mastery_score
                FROM student_state 
                WHERE user_id=:u AND language_id=:l AND mapping_id IN ({placeholders})
            """)
            
            params = {"u": user_id, "l": language_id}
            for i, mapping in enumerate(prereqs):
                params[f'p{i}'] = mapping
            
            prereq_scores = dict(self.db.execute(query, params).fetchall())
            
            # Calculate weighted average
            weighted_sum = 0.0
            total_weight = 0.0
            
            for prereq, weight in zip(prereqs, weights):
                mastery = prereq_scores.get(prereq, 0.0)
                weighted_sum += mastery * weight
                total_weight += weight
            
            weighted_avg = weighted_sum / total_weight if total_weight > 0 else 0.0
            
            # Calculate readiness as ratio
            readiness = min(weighted_avg / min_required, 1.0) if min_required > 0 else 1.0
            readiness_scores.append(readiness)
        
        return sum(readiness_scores) / len(readiness_scores) if readiness_scores else 1.0
    
    def _generate_metadata(
        self, 
        vector: np.ndarray, 
        user_id: str, 
        language_id: str,
        mastery_map: Dict[str, float]
    ) -> Dict:
        """
        Generate human-readable interpretation of state vector.
        Includes prerequisites, transfer potential, and error patterns.
        """
        
        # Find strongest and weakest topics
        topic_strengths = [
            (self.mappings_order[i], mastery_map.get(self.mappings_order[i], 0.0))
            for i in range(len(self.mappings_order))
        ]
        topic_strengths.sort(key=lambda x: x[1], reverse=True)
        
        strongest = topic_strengths[0] if topic_strengths else ("N/A", 0.0)
        weakest = topic_strengths[-1] if topic_strengths else ("N/A", 0.0)
        
        # Identify topics needing review
        maintenance_threshold = self.config.get_maintenance_threshold()
        needs_review = [
            topic for topic, score in topic_strengths 
            if score < maintenance_threshold and score > 0
        ]
        
        # NEW: Get prerequisites satisfaction status
        prereq_status = self._get_prerequisites_status(user_id, language_id, mastery_map)
        
        # NEW: Calculate cross-language transfer potential
        transfer_potential = self._get_transfer_potential(user_id, language_id, mastery_map)
        
        # NEW: Get recent error patterns
        error_patterns = self._get_recent_errors(user_id, language_id)
        
        return {
            "user_id": user_id,
            "language": language_id,
            "strongest_topic": {"id": strongest[0], "mastery": round(float(strongest[1]), 3)},
            "weakest_topic": {"id": weakest[0], "mastery": round(float(weakest[1]), 3)},
            "needs_review": needs_review,
            "overall_mastery_avg": round(float(np.mean([s for _, s in topic_strengths if s > 0]) if any(s > 0 for _, s in topic_strengths) else 0.0), 3),
            "last_session_accuracy": round(float(vector[self.behavioral_offset + 0]), 3),
            "average_fluency_ratio": round(float(vector[self.behavioral_offset + 2]), 2),  # NEW: Expose fluency in metadata
            "stability_score": round(float(vector[self.behavioral_offset + 3]), 3),
            "days_since_practice": int(vector[self.behavioral_offset + 4]),
            "gate_readiness": round(float(vector[self.behavioral_offset + 5]), 3),
            "session_confidence": round(float(vector[self.behavioral_offset + 6]), 3),  # Cold-start signal
            "performance_velocity": round(float(vector[self.behavioral_offset + 7]), 1),  # Fast learner flag
            "prerequisites_status": prereq_status,
            "transfer_potential": transfer_potential,
            "recent_error_patterns": error_patterns,
            "state_vector_version": "4.0",  # Phase 2B: Added adaptive difficulty dimension (36D)
            "vector_dimensions": len(vector)
        }
    
    def _get_prerequisites_status(
        self, 
        user_id: str, 
        language_id: str, 
        mastery_map: Dict[str, float]
    ) -> Dict[str, Dict]:
        """
        Check which topics have their prerequisites met.
        Returns: {mapping_id: {met: bool, missing: [list], strength: 0-1}}
        """
        prereq_status = {}
        
        for gate in self.config.transition_map.get('soft_gates', []):
            mapping_id = gate['mapping_id']
            required_prereqs = gate['prerequisite_mappings']
            min_score = gate['minimum_allowable_score']
            
            met = True
            missing = []
            total_strength = 0.0
            
            for prereq_id in required_prereqs:
                current = mastery_map.get(prereq_id, 0.0)
                if current < min_score:
                    met = False
                    missing.append(f"{prereq_id} ({current:.2f}/{min_score})")
                total_strength += current
            
            avg_strength = total_strength / len(required_prereqs) if required_prereqs else 1.0
            
            prereq_status[mapping_id] = {
                "all_prerequisites_met": bool(met),
                "missing_prerequisites": missing,
                "prerequisite_strength": round(float(avg_strength), 3)
            }
        
        return prereq_status
    
    def _get_transfer_potential(
        self, 
        user_id: str, 
        language_id: str, 
        mastery_map: Dict[str, float]
    ) -> List[Dict]:
        """
        Calculate potential for cross-language transfer.
        Returns best target languages with transfer coefficients.
        """
        transfers = []
        
        for transfer in self.config.transition_map.get('cross_language_transfer', []):
            if transfer['source_language_id'] == language_id:
                target = transfer['target_language_id']
                logic_accel = transfer['logic_acceleration']
                syntax_friction = transfer['syntax_friction']
                
                # Calculate expected benefit
                avg_mastery = np.mean(list(mastery_map.values())) if mastery_map else 0.0
                expected_boost = avg_mastery * logic_accel
                expected_friction = abs(syntax_friction)
                net_benefit = expected_boost - expected_friction
                
                transfers.append({
                    "target_language": target,
                    "logic_acceleration": float(logic_accel),
                    "syntax_friction": float(syntax_friction),
                    "expected_net_benefit": round(float(net_benefit), 3),
                    "recommended": bool(net_benefit > 0.3)
                })
        
        # Sort by net benefit
        transfers.sort(key=lambda x: x['expected_net_benefit'], reverse=True)
        return transfers[:3]  # Top 3 recommendations
    
    def _get_recent_errors(self, user_id: str, language_id: str) -> Dict[str, int]:
        """
        Get frequency of recent error types from last 5 sessions.
        Returns: {error_type: count}
        """
        query = text("""
            SELECT ed.questions_snapshot
            FROM exam_details ed
            JOIN exam_sessions es ON ed.session_id = es.id
            WHERE es.user_id = :u AND es.language_id = :l
            ORDER BY es.created_at DESC
            LIMIT 5
        """)
        
        rows = self.db.execute(query, {"u": user_id, "l": language_id}).fetchall()
        
        error_counts = {}
        for row in rows:
            snapshot = row[0]
            if isinstance(snapshot, dict) and 'questions' in snapshot:
                for q in snapshot['questions']:
                    if not q.get('is_correct') and q.get('error_type'):
                        error_type = q['error_type']
                        error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        # Sort by frequency
        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_errors[:5])  # Top 5 error types
