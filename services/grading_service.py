"""
Grading Service - Handles exam submission and mastery updates (SCENARIO B).
Implements the "Learning" part of the RL system.
"""

import math
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from .schemas import ExamSubmissionPayload, QuestionResult, MasteryUpdateResponse
from .config import get_config


class GradingService:
    """
    Processes exam submissions and updates student mastery state.
    Implements:
    - Exponential Moving Average (EMA) for mastery updates
    - Synergy bonus application
    - Soft gate violation detection
    - Fluency tracking
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
        
        # Weights for Exponential Moving Average
        self.retention_weight = 0.7   # How much old knowledge persists
        self.innovation_weight = 0.3  # How much new performance matters
        
        # Fluency calculation weights
        self.fluency_old_weight = 0.8
        self.fluency_new_weight = 0.2
    
    def process_submission(self, payload: ExamSubmissionPayload) -> MasteryUpdateResponse:
        """
        Main entry point for exam submission processing.
        
        Workflow:
        1. Calculate session statistics
        2. Get universal mapping ID
        3. Check soft gates (prerequisites)
        4. Update mastery scores
        5. Apply synergy bonuses
        6. Store session history
        7. Return recommendations
        
        Note: All DB operations wrapped in transaction for atomicity.
        """
        
        try:
            # 1. Calculate Session Statistics
            if not payload.results:
                raise ValueError("Exam must have at least one question")
            
            corrects = [q for q in payload.results if q.is_correct]
            accuracy = len(corrects) / len(payload.results)
            avg_difficulty = sum(q.difficulty for q in payload.results) / len(payload.results)
            
            # 2. Calculate Fluency (Time Efficiency)
            total_time = sum(q.time_spent for q in payload.results)
            total_expected = sum(q.expected_time for q in payload.results)
            fluency_ratio = min(total_expected / max(total_time, 0.1), 2.0)  # Cap at 2x speed
            
            # 3. Get Universal Mapping ID
            mapping_id = self.config.get_mapping_id(payload.language_id, payload.major_topic_id)
            
            # 4. Check Soft Gates (Prerequisites)
            gate_violations = self._check_soft_gates(
                payload.user_id, 
                payload.language_id, 
                mapping_id
            )
            
            # 5. Update Mastery in Database
            new_mastery = self._update_mastery(
                user_id=payload.user_id,
                language_id=payload.language_id,
                mapping_id=mapping_id,
                accuracy=accuracy,
                difficulty=avg_difficulty,
                fluency=fluency_ratio,
                has_violations=len(gate_violations) > 0,
                results=payload.results  # Pass results for error remediation
            )
            
            # 6. Apply Synergy Bonuses (only if accuracy >= 70%)
            synergies_applied = []
            if accuracy >= 0.7:
                synergies_applied = self._apply_synergy(
                    payload.user_id, 
                    payload.language_id, 
                    mapping_id
                )
            
            # 6.5. Apply Cross-Language Transfer (if user has other languages)
            transfer_bonuses = self._apply_cross_language_transfer(
                payload.user_id,
                payload.language_id,
                mapping_id,
                new_mastery
            )
            
            # 6.6. Apply Concept Interdependencies (bidirectional reinforcement)
            interdependency_boosts = self._apply_concept_interdependencies(
                payload.user_id,
                payload.language_id,
                mapping_id,
                new_mastery
            )
            
            # 7. Store Session History
            session_id = self._save_session_history(payload, accuracy, avg_difficulty, fluency_ratio)
            
            # 8. Save Detailed Questions Snapshot with error tracking
            self._save_exam_details(session_id, payload.results)
            
            # 9. Generate Recommendations (includes difficulty tier suggestion)
            recommendations = self._generate_recommendations(
                payload.user_id,
                payload.language_id,
                mapping_id,
                new_mastery,
                gate_violations
            )
            
            # COMMIT TRANSACTION: All operations succeeded
            self.db.commit()
            
            return MasteryUpdateResponse(
                success=True,
                session_id=str(session_id),
                accuracy=round(accuracy, 3),
                fluency_ratio=round(fluency_ratio, 2),
                new_mastery_score=round(new_mastery, 3),
                synergies_applied=synergies_applied + transfer_bonuses + interdependency_boosts,  # All bonuses combined
                soft_gate_violations=gate_violations,
                recommendations=recommendations
            )
        
        except Exception as e:
            # ROLLBACK: Ensure no partial updates on failure
            self.db.rollback()
            raise RuntimeError(f"Transaction failed during exam processing: {str(e)}") from e
    
    def _update_mastery(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str,
        accuracy: float,
        difficulty: float,
        fluency: float,
        has_violations: bool,
        results: List[QuestionResult] = None
    ) -> float:
        """
        Update mastery score using Exponential Moving Average.
        
        Formula:
        new_mastery = (old_mastery * 0.7) + (performance * 0.3) + remediation_bonus
        where performance = accuracy * difficulty * penalty_factor
        """
        
        # Fetch current scores
        query = text("""
            SELECT mastery_score, fluency_score, confidence_score 
            FROM student_state 
            WHERE user_id=:u AND mapping_id=:m AND language_id=:l
        """)
        res = self.db.execute(query, {"u": user_id, "m": mapping_id, "l": language_id}).fetchone()
        
        old_mastery = res[0] if res else 0.0
        old_fluency = res[1] if res else 0.0
        old_confidence = res[2] if res else 0.0
        
        # Calculate performance score
        performance = accuracy * difficulty
        
        # Apply soft gate penalty (reduce learning if prerequisites not met)
        if has_violations:
            # Use exponential penalty based on penalty_steepness from gate config
            gate = self.config.get_soft_gate(mapping_id)
            if gate and 'penalty_steepness' in gate:
                # Exponential decay: e^(-steepness) gives smooth penalty curve
                # steepness=2.5 → penalty_factor ≈ 0.082 (91.8% penalty)
                # steepness=2.0 → penalty_factor ≈ 0.135 (86.5% penalty)
                penalty_factor = math.exp(-gate['penalty_steepness'])
            else:
                penalty_factor = 0.6  # Fallback if no steepness defined
            performance *= penalty_factor
        
        # EMA Update
        new_mastery = (old_mastery * self.retention_weight) + (performance * self.innovation_weight)
        
        # Apply error remediation bonus (reward for fixing previous mistakes)
        if results:
            remediation_bonus = self._calculate_error_remediation_bonus(user_id, language_id, results)
            new_mastery += remediation_bonus
        
        new_mastery = min(new_mastery, 1.0)  # Cap at 1.0
        
        # Update fluency
        new_fluency = (old_fluency * self.fluency_old_weight) + (fluency * self.fluency_new_weight)
        new_fluency = min(new_fluency, 2.0)  # Cap at 2x
        
        # Update confidence (measure of score stability)
        # Higher when new score is close to old score
        score_delta = abs(new_mastery - old_mastery)
        confidence_boost = 1.0 - score_delta  # Inverse of change
        new_confidence = (old_confidence * 0.9) + (confidence_boost * 0.1)
        new_confidence = min(new_confidence, 1.0)
        
        # SQL Upsert
        upsert = text("""
            INSERT INTO student_state 
                (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score, last_practiced_at)
            VALUES (:u, :m, :l, :ms, :fs, :cs, NOW())
            ON CONFLICT (user_id, mapping_id, language_id) 
            DO UPDATE SET 
                mastery_score = EXCLUDED.mastery_score,
                fluency_score = EXCLUDED.fluency_score,
                confidence_score = EXCLUDED.confidence_score,
                last_practiced_at = EXCLUDED.last_practiced_at
        """)
        
        self.db.execute(upsert, {
            "u": user_id, 
            "m": mapping_id, 
            "l": language_id, 
            "ms": new_mastery, 
            "fs": new_fluency,
            "cs": new_confidence
        })
        
        return new_mastery
    
    def _apply_synergy(self, user_id: str, language_id: str, source_mapping_id: str) -> List[str]:
        """
        Apply synergy bonuses to related topics.
        Example: Mastering UNIV_LOOP gives +0.08 to UNIV_COND
        """
        bonuses = self.config.get_synergy_bonuses(source_mapping_id)
        applied = []
        
        for bonus in bonuses:
            target_id = bonus['target_mapping_id']
            bonus_value = bonus['synergy_bonus']
            
            sql = text("""
                UPDATE student_state 
                SET mastery_score = LEAST(mastery_score + :val, 1.0)
                WHERE user_id=:u AND mapping_id=:target AND language_id=:l
            """)
            
            result = self.db.execute(sql, {
                "val": bonus_value, 
                "u": user_id, 
                "target": target_id, 
                "l": language_id
            })
            
            if result.rowcount > 0:
                applied.append(f"{target_id} (+{bonus_value})")
        
        return applied
    
    def _calculate_error_remediation_bonus(self, user_id: str, language_id: str, results: List[QuestionResult]) -> float:
        """
        Calculate bonus for correcting previously made errors.
        If user answers questions correctly that they got wrong before, apply remediation_boost.
        """
        # Get previous errors from last session
        prev_errors_query = text("""
            SELECT ed.questions_snapshot
            FROM exam_details ed
            JOIN exam_sessions es ON ed.session_id = es.id
            WHERE es.user_id = :u AND es.language_id = :l
            ORDER BY es.created_at DESC
            LIMIT 1
        """)
        
        prev_session = self.db.execute(prev_errors_query, {"u": user_id, "l": language_id}).fetchone()
        
        if not prev_session:
            return 0.0  # No previous session to compare
        
        prev_snapshot = prev_session[0]
        if not isinstance(prev_snapshot, dict) or 'questions' not in prev_snapshot:
            return 0.0
        
        # Build set of error types from previous session
        prev_errors = set()
        for q in prev_snapshot.get('questions', []):
            if not q.get('is_correct') and q.get('error_type'):
                prev_errors.add(q['error_type'])
        
        if not prev_errors:
            return 0.0  # No previous errors to remediate
        
        # Check current session for corrected errors
        total_bonus = 0.0
        for result in results:
            if result.is_correct and result.error_type in prev_errors:
                # User corrected a previous error!
                bonus = self._get_remediation_boost(result.error_type)
                total_bonus += bonus
        
        return min(total_bonus, 0.15)  # Cap total bonus at +0.15
    
    def _get_remediation_boost(self, error_type: str) -> float:
        """
        Get remediation boost value for specific error type from taxonomy.
        """
        for category in self.config.transition_map.get('error_pattern_taxonomy', []):
            for pattern in category.get('patterns', []):
                if pattern.get('error_code') == error_type:
                    return pattern.get('remediation_boost', 0.0)
        return 0.0  # No boost defined for this error
    
    def _apply_concept_interdependencies(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str, 
        new_mastery: float
    ) -> List[str]:
        """
        Apply bidirectional reinforcement between related concepts.
        When mastery in one mapping improves, boost related mappings.
        
        Example:
        - If UNIV_LOOP mastery increases, boost UNIV_COND by 10%
        - If UNIV_OOP mastery increases, boost UNIV_FUNC and UNIV_VAR
        """
        interdeps = self.config.transition_map.get('concept_interdependencies', [])
        
        if not interdeps:
            return []  # No interdependencies defined
        
        applied = []
        
        for interdep in interdeps:
            mapping_a = interdep.get('mapping_a')
            mapping_b = interdep.get('mapping_b')
            coefficient = interdep.get('reinforcement_coefficient', 0.0)
            
            # Check if current mapping matches either side of the relationship
            if mapping_id == mapping_a:
                # Boost mapping_b
                target_mapping = mapping_b
            elif mapping_id == mapping_b:
                # Boost mapping_a (bidirectional)
                target_mapping = mapping_a
            else:
                continue  # This interdependency doesn't involve current mapping
            
            # Apply boost to related concept
            boost_amount = new_mastery * coefficient  # e.g., 0.8 mastery * 0.10 = 0.08 boost
            
            # Update target mapping mastery
            update_query = text("""
                UPDATE student_state
                SET mastery_score = LEAST(mastery_score + :boost, 1.0),
                    last_updated = NOW()
                WHERE user_id = :u AND language_id = :l AND mapping_id = :m
            """)
            
            result = self.db.execute(update_query, {
                "boost": boost_amount,
                "u": user_id,
                "l": language_id,
                "m": target_mapping
            })
            
            if result.rowcount > 0:
                applied.append(f"{target_mapping}:+{boost_amount:.3f}")
        
        return applied
    
    def _apply_cross_language_transfer(
        self, 
        user_id: str, 
        target_language_id: str, 
        mapping_id: str,
        current_mastery: float
    ) -> List[str]:
        """
        Apply cross-language transfer bonuses.
        If user has mastered this topic in another language, boost learning.
        
        Example: If mastered UNIV_VAR in Python, learning it in Java gets a boost.
        """
        # Find all languages user has practiced
        query = text("""
            SELECT DISTINCT language_id 
            FROM student_state 
            WHERE user_id=:u AND language_id != :target
        """)
        
        other_langs = [row[0] for row in self.db.execute(query, {"u": user_id, "target": target_language_id})]
        
        if not other_langs:
            return []  # No other languages to transfer from
        
        applied = []
        
        for source_lang in other_langs:
            # Get mastery in source language for this mapping
            source_query = text("""
                SELECT mastery_score 
                FROM student_state 
                WHERE user_id=:u AND language_id=:l AND mapping_id=:m
            """)
            
            source_mastery = self.db.execute(source_query, {
                "u": user_id,
                "l": source_lang,
                "m": mapping_id
            }).scalar()
            
            if not source_mastery or source_mastery < 0.5:
                continue  # Not enough mastery to transfer
            
            # Find transfer coefficient
            transfer = next(
                (t for t in self.config.transition_map.get('cross_language_transfer', [])
                 if t['source_language_id'] == source_lang and t['target_language_id'] == target_language_id),
                None
            )
            
            if transfer:
                logic_accel = transfer['logic_acceleration']
                # Apply boost: source_mastery * acceleration * 0.1 (scaled down)
                boost = source_mastery * logic_accel * 0.1
                
                update = text("""
                    UPDATE student_state 
                    SET mastery_score = LEAST(mastery_score + :boost, 1.0)
                    WHERE user_id=:u AND language_id=:l AND mapping_id=:m
                """)
                
                self.db.execute(update, {
                    "boost": boost,
                    "u": user_id,
                    "l": target_language_id,
                    "m": mapping_id
                })
                
                applied.append(f"{mapping_id} from {source_lang} (+{boost:.2f})")
        
        return applied
    
    def _check_soft_gates(self, user_id: str, language_id: str, mapping_id: str) -> List[str]:
        """
        Check if user meets prerequisite requirements (soft gates).
        Returns list of violated prerequisites.
        """
        gate = self.config.get_soft_gate(mapping_id)
        if not gate:
            return []  # No gate defined for this topic
        
        violations = []
        prereq_mappings = gate['prerequisite_mappings']
        min_score = gate['minimum_allowable_score']
        
        # Fetch current mastery for all prerequisites
        query = text("""
            SELECT mapping_id, mastery_score 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l AND mapping_id IN :prereqs
        """)
        
        results = self.db.execute(query, {
            "u": user_id,
            "l": language_id,
            "prereqs": tuple(prereq_mappings)  # Use tuple for IN clause (SQL injection safe)
        }).fetchall()
        
        mastery_map = {row[0]: row[1] for row in results}
        
        # Check each prerequisite
        for prereq_id in prereq_mappings:
            current_mastery = mastery_map.get(prereq_id, 0.0)
            if current_mastery < min_score:
                violations.append(f"{prereq_id} (has {current_mastery:.2f}, needs {min_score})")
        
        return violations
    
    def _save_session_history(
        self, 
        payload: ExamSubmissionPayload, 
        accuracy: float, 
        difficulty: float, 
        fluency: float
    ) -> uuid.UUID:
        """Save session to exam_sessions table."""
        session_id = uuid.uuid4()
        
        insert = text("""
            INSERT INTO exam_sessions 
                (id, user_id, language_id, major_topic_id, session_type, 
                 overall_score, difficulty_assigned, time_taken_seconds, rl_action_taken)
            VALUES (:id, :u, :l, :t, :st, :score, :diff, :time, :action)
        """)
        
        self.db.execute(insert, {
            "id": str(session_id),
            "u": payload.user_id,
            "l": payload.language_id,
            "t": payload.major_topic_id,
            "st": payload.session_type,
            "score": accuracy,
            "diff": difficulty,
            "time": payload.total_time_seconds,
            "action": "GRADED"  # Placeholder for RL action
        })
        
        return session_id
    
    def _save_exam_details(self, session_id: uuid.UUID, results: List[QuestionResult]):
        """Save detailed question results for review UI."""
        import json
        
        snapshot = {
            "questions": [
                {
                    "q_id": q.q_id,
                    "sub_topic": q.sub_topic,
                    "difficulty": q.difficulty,
                    "is_correct": q.is_correct,
                    "time_spent": q.time_spent,
                    "error_type": q.error_type
                }
                for q in results
            ]
        }
        
        insert = text("""
            INSERT INTO exam_details (session_id, questions_snapshot, recommendations, synergy_applied)
            VALUES (:sid, :snap::jsonb, '{}'::jsonb, FALSE)
        """)
        
        self.db.execute(insert, {
            "sid": str(session_id),
            "snap": json.dumps(snapshot)  # Proper JSON serialization (handles quotes, escaping, etc.)
        })
    
    def _generate_recommendations(
        self, 
        user_id: str, 
        language_id: str, 
        current_mapping: str,
        current_mastery: float,
        violations: List[str]
    ) -> List[str]:
        """
        Generate study recommendations based on current state.
        Includes difficulty tier suggestions.
        """
        recommendations = []
        
        # If has violations, recommend strengthening prerequisites
        if violations:
            recommendations.append(f"⚠️ Strengthen prerequisites before advancing: {', '.join(violations)}")
        
        # Get recommended difficulty tier
        tier = self.config.get_difficulty_tier(current_mapping, current_mastery)
        tier_emoji = {"beginner": "🟢", "intermediate": "🟡", "advanced": "🔴"}
        recommendations.append(f"{tier_emoji.get(tier, '⚪')} Recommended difficulty tier: {tier.upper()}")
        
        # Check if ready for next topic
        if current_mastery >= 0.75:
            recommendations.append(f"✅ Strong mastery ({current_mastery:.2f})! Ready to advance to next topic.")
        elif current_mastery >= 0.65:
            recommendations.append(f"📈 Good progress ({current_mastery:.2f}). Practice more to solidify understanding.")
        else:
            recommendations.append(f"📚 Keep practicing ({current_mastery:.2f}) to reach maintenance threshold (0.65).")
        
        # Check for topics needing review (decay)
        review_needed = self._find_topics_needing_review(user_id, language_id)
        if review_needed:
            recommendations.append(f"🔄 Review needed for: {', '.join(review_needed)}")
        
        # Check cross-language transfer opportunities
        transfer_opps = self._find_transfer_opportunities(user_id, language_id)
        if transfer_opps:
            recommendations.append(f"🌐 Transfer learning opportunity: {transfer_opps[0]}")
        
        return recommendations
    
    def _find_topics_needing_review(self, user_id: str, language_id: str) -> List[str]:
        """Find topics below maintenance threshold."""
        threshold = self.config.get_maintenance_threshold()
        
        query = text("""
            SELECT mapping_id 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l AND mastery_score < :thresh
        """)
        
        results = self.db.execute(query, {
            "u": user_id,
            "l": language_id,
            "thresh": threshold
        }).fetchall()
        
        return [row[0] for row in results]
    
    def _find_transfer_opportunities(self, user_id: str, current_language: str) -> List[str]:
        """
        Find languages where user could benefit from transfer learning.
        Returns suggestions like "Try Java - 85% transfer from your Python knowledge"
        """
        # Get user's average mastery in current language
        avg_query = text("""
            SELECT AVG(mastery_score)
            FROM student_state
            WHERE user_id=:u AND language_id=:l
        """)
        
        avg_mastery = self.db.execute(avg_query, {"u": user_id, "l": current_language}).scalar() or 0.0
        
        if avg_mastery < 0.5:
            return []  # Not ready for transfer yet
        
        # Find best transfer targets
        suggestions = []
        for transfer in self.config.transition_map.get('cross_language_transfer', []):
            if transfer['source_language_id'] == current_language:
                target = transfer['target_language_id']
                accel = transfer['logic_acceleration']
                
                if accel >= 0.75:  # Only suggest high-transfer languages
                    benefit = int(accel * avg_mastery * 100)
                    suggestions.append(f"Try {target} - {benefit}% knowledge transfer available")
        
        return suggestions[:2]  # Top 2 suggestions
