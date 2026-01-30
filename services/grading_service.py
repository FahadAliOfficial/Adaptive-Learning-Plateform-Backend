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
from .error_detection_service import error_detection_service


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
            
            # 1.5. Auto-detect error types from MCQ choices
            enhanced_results = self._enhance_results_with_error_detection(payload.results)
            
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
                results=enhanced_results  # Use enhanced results with error detection
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
            
            # 7. Increment User's Total Exam Counter (for cold-start confidence signal)
            self._increment_exam_counter(payload.user_id)
            
            # 8. Store Session History
            session_id = self._save_session_history(payload, accuracy, avg_difficulty, fluency_ratio)
            
            # 9. Save Detailed Questions Snapshot with error tracking
            self._save_exam_details(session_id, payload.results)
            
            # 10. Generate Recommendations (includes difficulty tier suggestion)
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
        
        # Detect Performance Velocity (high performers who should accelerate)
        is_high_velocity = (accuracy > 0.9 and fluency > 1.2 and difficulty > 0.6)
        
        # EMA Update with adaptive weights for fast learners
        if is_high_velocity:
            # Accelerate learning for high performers (reduce retention, increase innovation)
            retention = 0.5  # Less weight on old scores
            innovation = 0.5  # More weight on new performance
        else:
            retention = self.retention_weight  # Standard 0.7
            innovation = self.innovation_weight  # Standard 0.3
        
        new_mastery = (old_mastery * retention) + (performance * innovation)
        
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
                (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score, last_practiced_at, last_updated)
            VALUES (:u, :m, :l, :ms, :fs, :cs, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, mapping_id, language_id) 
            DO UPDATE SET 
                mastery_score = EXCLUDED.mastery_score,
                fluency_score = EXCLUDED.fluency_score,
                confidence_score = EXCLUDED.confidence_score,
                last_practiced_at = EXCLUDED.last_practiced_at,
                last_updated = EXCLUDED.last_updated
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
                SET mastery_score = MIN(mastery_score + :val, 1.0)
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
        
        # Parse JSON string if needed
        if isinstance(prev_snapshot, str):
            try:
                import json
                prev_snapshot = json.loads(prev_snapshot)
            except json.JSONDecodeError:
                return 0.0
        
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
            for pattern in category.get('common_patterns', []):  # Changed from 'patterns' to 'common_patterns'
                if pattern.get('error_type') == error_type:  # Changed from 'error_code' to 'error_type'
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
        - If UNIV_LOOP mastery increases, boost UNIV_COND and UNIV_VAR
        - If UNIV_FUNC mastery increases, boost UNIV_VAR, UNIV_LOOP, UNIV_COND
        """
        interdeps = self.config.transition_map.get('concept_interdependencies', [])
        
        if not interdeps:
            return []  # No interdependencies defined
        
        applied = []
        
        # Find interdependency rules that apply to the current mapping
        for interdep in interdeps:
            source_mapping = interdep.get('mapping_id')
            
            if source_mapping != mapping_id:
                continue  # This rule doesn't apply to current mapping
                
            # Apply reinforcements to related concepts
            reinforcements = interdep.get('reinforces', [])
            
            for reinforcement in reinforcements:
                target_mapping = reinforcement.get('target_mapping_id')
                strength = reinforcement.get('strength', 0.0)
                
                # Calculate boost: mastery improvement * strength (but scale it down reasonably)
                # Use a much smaller scale factor to match test expectations
                boost_amount = new_mastery * strength * 0.1  # Revert to reasonable scaling
                
                # Update target mapping mastery
                update_query = text("""
                    UPDATE student_state
                    SET mastery_score = MIN(mastery_score + :boost, 1.0),
                        last_updated = CURRENT_TIMESTAMP
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
                # Apply boost: source_mastery * acceleration (with reasonable scaling)
                # For cross-language transfer, use stronger scaling than other mechanisms
                boost = source_mastery * logic_accel * 0.8  # More substantial transfer boost
                
                update = text("""
                    UPDATE student_state 
                    SET mastery_score = MIN(mastery_score + :boost, 1.0)
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
    
    def _increment_exam_counter(self, user_id: str):
        """
        Atomically increment user's total exam counter.
        Used for cold-start confidence signals (avoids expensive COUNT(*) queries).
        """
        update_query = text("""
            UPDATE users 
            SET total_exams_taken = total_exams_taken + 1
            WHERE id = :user_id
        """)
        
        self.db.execute(update_query, {"user_id": user_id})
    
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
        # Build IN clause dynamically for SQLite compatibility
        placeholders = ','.join([f':p{i}' for i in range(len(prereq_mappings))])
        query = text(f"""
            SELECT mapping_id, mastery_score 
            FROM student_state 
            WHERE user_id=:u AND language_id=:l AND mapping_id IN ({placeholders})
        """)
        
        params = {"u": user_id, "l": language_id}
        for i, mapping in enumerate(prereq_mappings):
            params[f'p{i}'] = mapping
        
        results = self.db.execute(query, params).fetchall()
        
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
        """Save session to exam_sessions table with Phase 2B adaptive difficulty."""
        session_id = uuid.uuid4()
        
        # Phase 2B: Calculate recommended difficulty for NEXT session
        mapping_id = self.config.get_mapping_id(payload.language_id, payload.major_topic_id)
        recommended_next_diff = self._calculate_adaptive_difficulty(
            payload.user_id,
            payload.language_id,
            mapping_id
        )
        
        insert = text("""
            INSERT INTO exam_sessions 
                (id, user_id, language_id, major_topic_id, session_type, 
                 overall_score, difficulty_assigned, time_taken_seconds, rl_action_taken, recommended_next_difficulty)
            VALUES (:id, :u, :l, :t, :st, :score, :diff, :time, :action, :next_diff)
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
            "action": "GRADED",  # Placeholder for RL action
            "next_diff": recommended_next_diff
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
            VALUES (:sid, :snap, '{}', FALSE)
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
        Includes difficulty tier suggestions and Phase 2B predictions.
        """
        recommendations = []
        
        # If has violations, recommend strengthening prerequisites
        if violations:
            recommendations.append(f"⚠️ Strengthen prerequisites before advancing: {', '.join(violations)}")
        
        # Phase 2B Feature #16: Adaptive difficulty recommendation
        adaptive_diff = self._calculate_adaptive_difficulty(user_id, language_id, current_mapping)
        
        if adaptive_diff > 0.8:
            recommendations.append(f"🔥 Next difficulty: ADVANCED ({adaptive_diff:.2f}) - You're crushing it!")
        elif adaptive_diff > 0.6:
            recommendations.append(f"📈 Next difficulty: INTERMEDIATE ({adaptive_diff:.2f}) - Good progress!")
        else:
            recommendations.append(f"🌱 Next difficulty: BEGINNER ({adaptive_diff:.2f}) - Building foundations")
        
        # Phase 2B Feature #17: Time to mastery prediction
        prediction = self._predict_time_to_mastery(user_id, language_id, current_mapping, current_mastery)
        
        if prediction['estimated_hours'] is not None:
            hours = prediction['estimated_hours']
            sessions = prediction['estimated_sessions']
            conf = int(prediction['confidence'] * 100)
            
            if hours == 0:
                recommendations.append(f"🎯 Mastery achieved! ({current_mastery:.2f})")
            elif hours < 2:
                recommendations.append(f"⏱️ Almost there! ~{hours:.1f} hours to mastery ({conf}% confidence)")
            elif hours < 5:
                recommendations.append(f"📅 ~{hours:.1f} hours ({sessions} sessions) to reach mastery")
            else:
                recommendations.append(f"🎯 Long-term goal: ~{hours:.1f} hours to mastery")
        
        # Check if ready for next topic (original logic)
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

    def _enhance_results_with_error_detection(self, results: List[QuestionResult]) -> List[QuestionResult]:
        """
        Enhance question results with automatic error type detection from MCQ choices.
        """
        enhanced = []
        
        for result in results:
            # If result already has error_type or was correct, keep as-is
            if result.error_type or result.is_correct:
                enhanced.append(result)
                continue
            
            # Try to auto-detect error type from question bank
            try:
                # Get question data from database
                question_query = text("""
                    SELECT question_data FROM question_bank WHERE id = :qid
                """)
                question_row = self.db.execute(question_query, {"qid": result.q_id}).fetchone()
                
                if question_row:
                    question_data = question_row[0]  # JSON column
                    
                    # Detect error type based on selected choice
                    detected_error = error_detection_service.detect_error_from_mcq_choice(
                        question_data=question_data,
                        selected_choice=result.selected_choice
                    )
                    
                    if detected_error:
                        # Create new result with detected error type
                        enhanced_result = result.model_copy(update={'error_type': detected_error})
                        enhanced.append(enhanced_result)
                    else:
                        enhanced.append(result)
                else:
                    enhanced.append(result)
                    
            except Exception as e:
                # If error detection fails, use original result
                print(f"Error detection failed for question {result.q_id}: {e}")
                enhanced.append(result)
        
        return enhanced
    
    def _calculate_adaptive_difficulty(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str
    ) -> float:
        """
        Calculate recommended difficulty for next session based on recent performance.
        
        Phase 2B Feature #16: Adaptive Difficulty Curves
        
        Algorithm:
        1. Fetch last 10 sessions for this mapping_id
        2. Calculate average accuracy
        3. Apply adjustment rules from config (accuracy ranges → multipliers)
        4. Smooth with current difficulty to prevent abrupt jumps
        5. Clamp to bounds (0.3 to 1.0)
        
        Returns:
            float: Recommended difficulty (0.3 to 1.0)
        """
        config = self.config.transition_map.get('adaptive_difficulty_curves', {})
        window_size = config.get('performance_windows', {}).get('sample_size', 10)
        
        # 1. Fetch last N sessions for this topic
        # Need to get major_topic_id from mapping_id
        major_topic_id = self.config.get_major_topic_id(language_id, mapping_id)
        
        query = text("""
            SELECT overall_score, difficulty_assigned
            FROM exam_sessions
            WHERE user_id = :u 
              AND language_id = :l 
              AND major_topic_id = :m
            ORDER BY created_at DESC
            LIMIT :window
        """)
        
        sessions = self.db.execute(query, {
            "u": user_id,
            "l": language_id,
            "m": major_topic_id,
            "window": window_size
        }).fetchall()
        
        if not sessions:
            # No history - use beginner difficulty
            return 0.5
        
        # 2. Calculate average accuracy from recent sessions
        avg_accuracy = sum(s[0] for s in sessions) / len(sessions)
        current_difficulty = sessions[0][1]  # Most recent difficulty
        
        # 3. Apply adjustment rules based on accuracy ranges
        difficulty_multiplier = 1.0  # Default: maintain
        
        for rule in config.get('adjustment_rules', []):
            accuracy_range = rule.get('accuracy_range', [0.0, 1.0])
            if accuracy_range[0] <= avg_accuracy < accuracy_range[1]:
                difficulty_multiplier = rule.get('difficulty_multiplier', 1.0)
                break
        
        # Calculate adjusted difficulty
        adjusted_difficulty = current_difficulty * difficulty_multiplier
        
        # 4. Smooth with current difficulty (prevents sudden jumps)
        # This is implicit in the multiplier approach, but we can add extra smoothing
        # For now, the multiplier itself provides smoothing (1.1x, 1.3x vs raw jumps)
        
        # 5. Clamp to bounds
        min_diff = 0.3
        max_diff = 1.0
        
        return max(min_diff, min(adjusted_difficulty, max_diff))
    
    def _predict_time_to_mastery(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        current_mastery: float
    ) -> Dict[str, Any]:
        """
        Predict hours and sessions needed to reach 0.75 mastery.
        
        Phase 2B Feature #17: Temporal Learning Patterns
        
        Algorithm:
        1. Get baseline estimates from config (e.g., UNIV_VAR: 4 hours)
        2. Calculate user's learning velocity from last 5 sessions
        3. Predict time needed: mastery_gap / velocity
        4. Calculate confidence based on data availability
        
        Returns:
            {
                "estimated_hours": 2.5,
                "estimated_sessions": 3,
                "current_velocity": 0.12,  # mastery points per hour
                "confidence": 0.85
            }
        """
        # Get temporal pattern from config
        patterns = self.config.transition_map.get('temporal_learning_patterns', [])
        pattern = next((p for p in patterns if p['mapping_id'] == mapping_id), None)
        
        if not pattern:
            return {
                "estimated_hours": None, 
                "estimated_sessions": None,
                "current_velocity": None,
                "confidence": 0.0
            }
        
        target_mastery = 0.75
        mastery_gap = target_mastery - current_mastery
        
        if mastery_gap <= 0:
            # Already mastered
            return {
                "estimated_hours": 0.0,
                "estimated_sessions": 0,
                "current_velocity": 0.0,
                "confidence": 1.0
            }
        
        # Get major_topic_id for this mapping
        try:
            major_topic_id = self.config.get_major_topic_id(language_id, mapping_id)
        except ValueError:
            # Fallback if mapping not found
            return {
                "estimated_hours": pattern.get('estimated_hours', 5.0),
                "estimated_sessions": pattern.get('sessions_to_mastery', 5),
                "current_velocity": None,
                "confidence": 0.3
            }
        
        # Calculate user's current velocity (mastery improvement per hour)
        # Use overall_score from exam_sessions as a proxy for mastery at that time
        velocity_query = text("""
            SELECT created_at, overall_score, time_taken_seconds
            FROM exam_sessions 
            WHERE user_id = :u 
              AND language_id = :l
              AND major_topic_id = :m
            ORDER BY created_at ASC
            LIMIT 10
        """)
        
        sessions = self.db.execute(velocity_query, {
            "u": user_id, 
            "l": language_id, 
            "m": major_topic_id
        }).fetchall()
        
        if len(sessions) >= 2:
            # Calculate velocity from actual data
            # Use time range between first and last session, not sum of durations
            timestamps = [s[0] for s in sessions]
            mastery_values = [s[1] for s in sessions]
            
            # Parse timestamps if they're strings (SQLite compatibility)
            parsed_timestamps = []
            for ts in timestamps:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                parsed_timestamps.append(ts)
            
            # Calculate time elapsed between first and last session
            time_delta = (parsed_timestamps[-1] - parsed_timestamps[0]).total_seconds() / 3600.0  # hours
            mastery_delta = max(mastery_values) - min(mastery_values)
            
            if time_delta > 0 and mastery_delta > 0:
                user_velocity = mastery_delta / time_delta  # mastery points per hour
            else:
                # Use baseline from config
                avg_hours = pattern.get('estimated_hours', 5.0)
                user_velocity = 1.0 / avg_hours
            
            # Confidence increases with more data
            session_count = len(sessions)
            confidence = min(session_count / 10.0, 0.95)  # Max 95% confidence after 10+ sessions
        else:
            # No history - use average from config
            avg_hours = pattern.get('estimated_hours', 5.0)
            user_velocity = None  # No velocity data
            confidence = 0.0  # No confidence without data
        
        # Predict hours needed
        if user_velocity and user_velocity > 0:
            estimated_hours = mastery_gap / user_velocity
        else:
            # No velocity data - use baseline from config
            estimated_hours = pattern.get('estimated_hours', 5.0)
        
        # Predict sessions (using optimal session length from config)
        optimal_session_minutes = pattern.get('optimal_session_length_minutes', 45)
        estimated_sessions = int((estimated_hours * 60) / optimal_session_minutes) + 1
        
        return {
            "estimated_hours": round(estimated_hours, 1),
            "estimated_sessions": estimated_sessions,
            "current_velocity": round(user_velocity, 3) if user_velocity else None,
            "confidence": round(confidence, 2)
        }
