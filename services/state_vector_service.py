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

from .schemas import StateVectorRequest, StateVectorResponse
from .config import get_config


class StateVectorGenerator:
    """
    Generates fixed-size state vectors for RL model consumption.
    
    State Vector Structure (DYNAMIC based on curriculum):
    Default with 5 languages & 8 mappings = 35 dimensions:
    [lang_offset : lang_offset+5]         Language One-Hot Encoding
    [mastery_offset : mastery_offset+8]   Mastery Scores with Decay
    [fluency_offset : fluency_offset+8]   Fluency Scores
    [confidence_offset : confidence_offset+8] Confidence Scores
    [behavioral_offset : behavioral_offset+6] Behavioral Metrics:
        [0] Last Session Accuracy
        [1] Last Session Difficulty
        [2] Average Fluency Ratio
        [3] Mastery Stability (Std Dev)
        [4] Days Since Last Practice
        [5] Soft Gate Readiness
    
    Formula: vector_size = num_languages + (num_mappings × 3) + 6
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
        # Structure: language_onehot + (mappings × 3 scores) + 6 behavioral metrics
        self.vector_size = len(self.languages_order) + (len(self.mappings_order) * 3) + 6
        
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
        
        # Validate language_id exists in curriculum
        if language_id not in self.config.valid_languages:
            raise ValueError(
                f"Invalid language_id: {language_id}. "
                f"Valid languages: {sorted(self.config.valid_languages)}"
            )
        
        # Initialize vector (dynamic dimensions based on curriculum)
        vector = np.zeros(self.vector_size, dtype=np.float32)
        
        # 1. Language One-Hot Encoding [lang_offset : lang_offset + num_languages]
        lang_idx = self.languages_order.index(language_id)
        vector[self.lang_offset + lang_idx] = 1.0
        
        # 2. Decayed Mastery Scores [mastery_offset : mastery_offset + num_mappings]
        mastery_map = self._get_decayed_mastery(user_id, language_id)
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.mastery_offset + i] = mastery_map.get(mapping_id, 0.0)
        
        # 3. Fluency Scores [fluency_offset : fluency_offset + num_mappings]
        fluency_map = self._get_fluency_scores(user_id, language_id)
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.fluency_offset + i] = fluency_map.get(mapping_id, 1.0)  # Default to normal speed
        
        # 4. Confidence Scores [confidence_offset : confidence_offset + num_mappings]
        confidence_map = self._get_confidence_scores(user_id, language_id)
        for i, mapping_id in enumerate(self.mappings_order):
            vector[self.confidence_offset + i] = confidence_map.get(mapping_id, 0.0)
        
        # 5. Behavioral Metrics [behavioral_offset : behavioral_offset + 6]
        metrics = self._get_behavioral_metrics(user_id, language_id)
        vector[self.behavioral_offset + 0] = metrics['last_accuracy']
        vector[self.behavioral_offset + 1] = metrics['last_difficulty']
        vector[self.behavioral_offset + 2] = metrics['avg_fluency']
        vector[self.behavioral_offset + 3] = metrics['stability']
        vector[self.behavioral_offset + 4] = metrics['days_inactive']
        vector[self.behavioral_offset + 5] = metrics['gate_readiness']
        
        # 6. Generate rich metadata (prerequisites, transfer potential, errors)
        metadata = self._generate_metadata(vector, user_id, language_id, mastery_map)
        
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
        """
        
        # Last session stats
        last_session_query = text("""
            SELECT overall_score, difficulty_assigned, time_taken_seconds, created_at
            FROM exam_sessions 
            WHERE user_id=:u AND language_id=:l 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        last_session = self.db.execute(last_session_query, {"u": user_id, "l": language_id}).fetchone()
        
        if last_session:
            last_accuracy = last_session[0]
            last_difficulty = last_session[1]
            last_date = last_session[3]
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            days_inactive = (datetime.now(timezone.utc) - last_date).days
        else:
            last_accuracy = 0.0
            last_difficulty = 0.5
            days_inactive = 999  # Never practiced
        
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
            WHERE user_id=:u AND language_id=:l 
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
        
        return {
            'last_accuracy': round(last_accuracy, 3),
            'last_difficulty': round(last_difficulty, 3),
            'avg_fluency': round(avg_fluency, 2),
            'stability': round(stability, 3),
            'days_inactive': min(days_inactive, 30),  # Cap for normalization
            'gate_readiness': round(gate_readiness, 3)
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
            query = text("""
                SELECT mapping_id, mastery_score
                FROM student_state 
                WHERE user_id=:u AND language_id=:l AND mapping_id IN :prereqs
            """)
            
            prereq_scores = dict(self.db.execute(query, {
                "u": user_id,
                "l": language_id,
                "prereqs": tuple(prereqs)  # Use tuple for IN clause (SQL injection safe)
            }).fetchall())
            
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
            "strongest_topic": {"id": strongest[0], "mastery": round(strongest[1], 3)},
            "weakest_topic": {"id": weakest[0], "mastery": round(weakest[1], 3)},
            "needs_review": needs_review,
            "overall_mastery_avg": round(np.mean([s for _, s in topic_strengths if s > 0]), 3) if topic_strengths else 0.0,
            "last_session_accuracy": round(vector[self.behavioral_offset + 0], 3),
            "stability_score": round(vector[self.behavioral_offset + 3], 3),
            "days_since_practice": int(vector[self.behavioral_offset + 4]),
            "gate_readiness": round(vector[self.behavioral_offset + 5], 3),
            "prerequisites_status": prereq_status,  # NEW
            "transfer_potential": transfer_potential,  # NEW
            "recent_error_patterns": error_patterns,  # NEW
            "state_vector_version": "2.0",
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
                "all_prerequisites_met": met,
                "missing_prerequisites": missing,
                "prerequisite_strength": round(avg_strength, 3)
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
                    "logic_acceleration": logic_accel,
                    "syntax_friction": syntax_friction,
                    "expected_net_benefit": round(net_benefit, 3),
                    "recommended": net_benefit > 0.3
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
