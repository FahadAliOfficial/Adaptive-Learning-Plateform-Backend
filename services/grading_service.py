"""
Grading Service - Handles exam submission and mastery updates (SCENARIO B).
Implements the "Learning" part of the RL system.
"""

import math
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from .schemas import (
    ExamSubmissionPayload, 
    QuestionResult, 
    MasteryUpdateResponse,
    EnhancedMasteryUpdateResponse,
    EnhancedErrorPattern,
    PrerequisiteGap
)
from .config import get_config
from .error_detection_service import error_detection_service
from .review_scheduler import ReviewScheduler
from .content_engine.selector import QuestionSelector
from .pattern_analyzer import PatternAnalyzer


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
    
    def process_submission(self, payload: ExamSubmissionPayload, background_tasks=None) -> MasteryUpdateResponse:
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
        8. Trigger background exam analysis (if background_tasks provided)
        
        Note: All DB operations wrapped in transaction for atomicity.
        """
        
        try:
            # 1. Calculate Session Statistics
            if not payload.results:
                raise ValueError("Exam must have at least one question")
            
            corrects = [q for q in payload.results if q.is_correct]
            accuracy = len(corrects) / len(payload.results)
            avg_difficulty = sum(q.difficulty for q in payload.results) / len(payload.results)
            
            # 1.5. Auto-detect error types from MCQ choices (Phase 2 enhanced with language filtering)
            enhanced_results = self._enhance_results_with_error_detection(payload.results, payload.language_id)
            
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
            
            # 8.5. Mark RL recommendation as followed only for exam sessions
            if payload.session_type == "exam":
                self._mark_recommendation_followed(
                    payload.user_id,
                    payload.language_id,
                    payload.major_topic_id
                )
            
            # 9. Save Detailed Questions Snapshot with error tracking
            self._save_exam_details(session_id, payload.results)

            # 9.5. Record question history for seen tracking (skip for practice and review modes)
            if payload.session_type not in ["practice", "review"]:
                self._record_question_history(payload.user_id, str(session_id), payload.results)
            
            # 10. Generate Recommendations (includes difficulty tier suggestion)
            recommendations = self._generate_recommendations(
                payload.user_id,
                payload.language_id,
                mapping_id,
                new_mastery,
                gate_violations
            )
            
            # 11. Phase 2C: Schedule review for this topic
            scheduler = ReviewScheduler(self.db)
            scheduler.schedule_review(
                user_id=payload.user_id,
                language_id=payload.language_id,
                mapping_id=mapping_id,
                current_mastery=new_mastery
            )
            
            # 12. Phase 2C: If this was a review session, mark it completed
            if payload.session_type == "review":
                scheduler.mark_review_completed(
                    user_id=payload.user_id,
                    language_id=payload.language_id,
                    mapping_id=mapping_id,
                    review_accuracy=accuracy,
                    new_mastery=new_mastery
                )
            
            # 13. Phase 2D: Log errors and track corrections
            pattern_analyzer = PatternAnalyzer(self.db)
            for result in enhanced_results:
                if not result.is_correct and result.error_type:
                    pattern_analyzer.log_error(
                        user_id=payload.user_id,
                        language_id=payload.language_id,
                        mapping_id=result.sub_topic,
                        session_id=payload.session_id,
                        question_id=result.q_id,
                        error_type=result.error_type,
                        difficulty_tier=getattr(result, 'difficulty_tier', 1)
                    )
                elif result.is_correct and result.error_type:
                    # Mark previous errors of this type as corrected
                    pattern_analyzer.mark_error_corrected(
                        user_id=payload.user_id,
                        language_id=payload.language_id,
                        error_type=result.error_type
                    )
            
            # COMMIT TRANSACTION: All operations succeeded
            self.db.commit()
            
            # 14. Trigger background exam analysis generation (OpenAI GPT-4o-mini)
            if background_tasks:
                from services.background_tasks import generate_exam_analysis_task
                background_tasks.add_task(
                    generate_exam_analysis_task,
                    session_id=str(session_id),
                    db_connection_string=str(self.db.bind.url)
                )
            
            # Phase 2 Fix (Issue 2 & 3): Get error history context and prerequisite gaps
            # Build EnhancedErrorPattern list from current session + historical trends
            error_patterns_enhanced = []
            session_error_types = [r.error_type for r in enhanced_results if r.error_type and not r.is_correct]
            
            if session_error_types:
                # Get historical trends for session errors
                error_history_context = self._get_error_history_context(
                    user_id=payload.user_id,
                    language_id=payload.language_id,
                    session_error_types=list(set(session_error_types))  # Unique errors only
                )
                
                # Count errors in current session
                from collections import Counter
                session_error_counts = Counter(session_error_types)
                
                # Build EnhancedErrorPattern for each error type
                for error_type in set(session_error_types):
                    history = error_history_context.get(error_type, {})
                    pattern = EnhancedErrorPattern(
                        error_type=error_type,
                        count=session_error_counts[error_type],
                        total_count=history.get('total_count'),
                        trend=history.get('trend'),
                        severity=history.get('severity'),
                        category=self._get_error_category(error_type),
                        first_seen=history.get('first_seen'),
                        last_seen=history.get('last_seen'),
                        applies_to_languages=self._get_error_languages(error_type)
                    )
                    error_patterns_enhanced.append(pattern)
            
            # Get prerequisite gaps and readiness from PrerequisiteAnalyzer
            prerequisite_gaps_list = []
            overall_readiness_score = None
            
            try:
                from services.prerequisite_analyzer import PrerequisiteAnalyzer
                prereq_analyzer = PrerequisiteAnalyzer(self.db)
                
                # Analyze prerequisites for the current topic
                prereq_analysis = prereq_analyzer.analyze_prerequisites(
                    user_id=payload.user_id,
                    language_id=payload.language_id,
                    target_mapping_id=mapping_id
                )
                
                if prereq_analysis:
                    overall_readiness_score = prereq_analysis.get('overall_readiness', 0.0)
                    
                    # Get gaps (both critical and regular gaps)
                    all_gaps = prereq_analysis.get('critical_gaps', []) + prereq_analysis.get('gaps', [])
                    
                    for gap in all_gaps:
                        prerequisite_gaps_list.append(PrerequisiteGap(
                            prereq_id=gap['prereq_id'],
                            name=gap['name'],
                            current_mastery=gap['current_mastery'],
                            required_mastery=gap['required_mastery'],
                            gap_size=gap['gap_size'],
                            weight=gap['weight'],
                            impact=gap['impact'],
                            recommendation=gap['recommendation']
                        ))
            except Exception as e:
                # If prerequisite analysis fails, continue without it (backward compatible)
                print(f"Prerequisite analysis failed: {e}")
            
            # Phase 3 Fix (Issue 2): Store prerequisite_gaps and overall_readiness in exam_details
            # Update exam_details with Phase 2 data immediately after commit
            try:
                phase2_data = {}
                if prerequisite_gaps_list:
                    phase2_data['prerequisite_gaps'] = [
                        {
                            'prereq_id': gap.prereq_id,
                            'name': gap.name,
                            'current_mastery': gap.current_mastery,
                            'required_mastery': gap.required_mastery,
                            'gap_size': gap.gap_size,
                            'weight': gap.weight,
                            'impact': gap.impact,
                            'recommendation': gap.recommendation
                        }
                        for gap in prerequisite_gaps_list
                    ]
                if overall_readiness_score is not None:
                    phase2_data['overall_readiness'] = overall_readiness_score
                
                if phase2_data:
                    import json
                    update_query = text("""
                        UPDATE exam_details
                        SET recommendations = jsonb_set(
                            COALESCE(recommendations, '{}'::jsonb),
                            '{phase2_data}',
                            CAST(:phase2_json AS jsonb)
                        )
                        WHERE session_id = :sid
                    """)
                    self.db.execute(update_query, {
                        'sid': str(session_id),
                        'phase2_json': json.dumps(phase2_data)
                    })
                    self.db.commit()
            except Exception as e:
                print(f"Failed to store Phase 2 data: {e}")
                # Don't fail the entire request if Phase 2 storage fails
            
            # Return EnhancedMasteryUpdateResponse with Phase 2 fields
            return EnhancedMasteryUpdateResponse(
                success=True,
                session_id=str(session_id),
                accuracy=round(accuracy, 3),
                fluency_ratio=round(fluency_ratio, 2),
                new_mastery_score=round(new_mastery, 3),
                synergies_applied=synergies_applied + transfer_bonuses + interdependency_boosts,
                soft_gate_violations=gate_violations,
                recommendations=recommendations,
                # Phase 2 enhancements
                error_patterns=error_patterns_enhanced if error_patterns_enhanced else None,
                prerequisite_gaps=prerequisite_gaps_list if prerequisite_gaps_list else None,
                overall_readiness=round(overall_readiness_score, 3) if overall_readiness_score is not None else None
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
                    SET mastery_score = LEAST(mastery_score + :boost, 1.0),
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
        """Update session in exam_sessions table (from 'started' to 'completed')."""
        # Use session_id from payload (created by /api/exam/start)
        session_id = uuid.UUID(payload.session_id)
        
        # Phase 2B: Calculate recommended difficulty for NEXT session
        mapping_id = self.config.get_mapping_id(payload.language_id, payload.major_topic_id)
        recommended_next_diff = self._calculate_adaptive_difficulty(
            payload.user_id,
            payload.language_id,
            mapping_id
        )
        
        action = "GRADED" if payload.session_type == "exam" else None

        update = text("""
            UPDATE exam_sessions 
            SET overall_score = :score,
                difficulty_assigned = :diff,
                time_taken_seconds = :time,
                rl_action_taken = :action,
                recommended_next_difficulty = :next_diff,
                session_status = 'completed',
                completed_at = NOW()
            WHERE id = :id
        """)
        
        self.db.execute(update, {
            "id": str(session_id),
            "score": accuracy,
            "diff": difficulty,
            "time": payload.total_time_seconds,
            "action": action,
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
                    "expected_time": q.expected_time,
                    "selected_choice": q.selected_choice,
                    "correct_choice": q.correct_choice,
                    "question_text": q.question_text,
                    "code_snippet": q.code_snippet,
                    "options": q.options,
                    "explanation": q.explanation,
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

    def _record_question_history(
        self,
        user_id: str,
        session_id: str,
        results: List[QuestionResult]
    ):
        """Persist questions shown to the user for future seen/unseen filtering."""
        insert = text("""
            INSERT INTO user_question_history (
                id, user_id, question_id, session_id, was_correct, time_spent_seconds, seen_at
            )
            VALUES (
                :id, :user_id, :question_id, :session_id, :was_correct, :time_spent_seconds, NOW()
            )
        """)

        params = []
        for q in results:
            params.append({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "question_id": q.q_id,
                "session_id": session_id,
                "was_correct": q.is_correct,
                "time_spent_seconds": q.time_spent
            })

        if params:
            self.db.execute(insert, params)
    
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

    def _enhance_results_with_error_detection(self, results: List[QuestionResult], language_id: str = None) -> List[QuestionResult]:
        """
        Phase 2 Enhancement: Enhance question results with automatic error type detection from MCQ choices.
        
        Features:
        - Detects error types from MCQ option metadata
        - Filters errors by language applicability (Phase 2.5)
        - Enriches with error category and severity
        
        Args:
            results: List of question results
            language_id: Optional language identifier for filtering errors
        
        Returns: Enhanced results with error_type, category, severity
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
                        # Phase 2.5: Apply language filtering
                        if language_id and not self._is_error_applicable_to_language(detected_error, language_id):
                            # Error not applicable to this language, skip it
                            enhanced.append(result)
                            continue
                        
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
    
    def _is_error_applicable_to_language(self, error_type: str, language_id: str) -> bool:
        """
        Phase 2.5: Check if an error type applies to a specific language.
        
        Example:
        - MEMORY_LEAK: Only applicable to cpp_20, not python_3
        - INDENTATION_ERROR: Only applicable to python_3, not javascript_es6
        - OFF_BY_ONE_ERROR: Universal (applies to all languages)
        
        Args:
            error_type: Error type identifier
            language_id: Language identifier
        
        Returns: True if error applies to language, False otherwise
        """
        # Get error taxonomy
        taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
        
        # Find error definition
        for category in taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    # Check applies_to_languages field
                    applies_to = pattern.get('applies_to_languages', [])
                    
                    # If empty or "all", applies to all languages
                    if not applies_to or applies_to == ["all"] or "all" in applies_to:
                        return True
                    
                    # Check if language is in the list
                    return language_id in applies_to
        
        # If error not found in taxonomy, assume it applies (backward compatibility)
        return True
    
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
              AND session_status = 'completed'
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
        # Guard against NULL overall_score values in completed sessions
        valid_scores = [s[0] for s in sessions if s[0] is not None]
        if not valid_scores:
            return 0.5
        avg_accuracy = sum(valid_scores) / len(valid_scores)
        current_difficulty = sessions[0][1]  # Most recent difficulty
        if current_difficulty is None:
            return 0.5  # Fallback if difficulty_assigned is NULL
        
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
        # Only use COMPLETED sessions with non-null scores to avoid NoneType comparison errors
        velocity_query = text("""
            SELECT created_at, overall_score, time_taken_seconds
            FROM exam_sessions 
            WHERE user_id = :u 
              AND language_id = :l
              AND major_topic_id = :m
              AND session_status = 'completed'
              AND overall_score IS NOT NULL
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
            mastery_values = [s[1] for s in sessions if s[1] is not None]
            
            if len(mastery_values) >= 2:
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
                    avg_hours = pattern.get('estimated_hours', 5.0) if pattern else 5.0
                    user_velocity = 1.0 / avg_hours
                
                # Confidence increases with more data
                session_count = len(sessions)
                confidence = min(session_count / 10.0, 0.95)  # Max 95% confidence after 10+ sessions
            else:
                # Not enough valid (non-null) scores — fall back to baseline
                avg_hours = pattern.get('estimated_hours', 5.0) if pattern else 5.0
                user_velocity = None
                confidence = 0.0
        else:
            # No history - use average from config
            avg_hours = pattern.get('estimated_hours', 5.0) if pattern else 5.0
            user_velocity = None  # No velocity data
            confidence = 0.0  # No confidence without data
        
        # Predict hours needed
        if user_velocity and user_velocity > 0:
            estimated_hours = mastery_gap / user_velocity
        else:
            # No velocity data - use baseline from config
            estimated_hours = pattern.get('estimated_hours', 5.0) if pattern else 5.0
        
        # Predict sessions (using optimal session length from config)
        optimal_session_minutes = pattern.get('optimal_session_length_minutes', 45) if pattern else 45
        estimated_sessions = int((estimated_hours * 60) / optimal_session_minutes) + 1
        
        return {
            'mapping_id': mapping_id,
            'current_mastery': current_mastery,
            'target_mastery': 0.85,
            'mastery_gap': mastery_gap,
            'estimated_hours': round(estimated_hours, 1) if mastery_gap > 0 else 0,
            'estimated_sessions': estimated_sessions if mastery_gap > 0 else 0,
            'confidence': round(confidence, 2),
            'user_velocity': round(user_velocity, 4) if user_velocity else None,
            'pattern_avg_hours': pattern.get('estimated_hours', 5.0) if pattern else 5.0,
            'session_count': len(sessions)
        }
    
    def _get_error_history_context(
        self,
        user_id: str,
        language_id: str,
        session_error_types: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get enriched error history context for current session errors.
        
        Phase 2 Enhancement: Returns detailed trend analysis for each error type.
        
        Args:
            user_id: Student UUID
            language_id: Language identifier
            session_error_types: List of error types from current session
        
        Returns:
            {
                "OFF_BY_ONE_ERROR": {
                    "total_count": 7,
                    "trend": "persistent",  # persistent/improving/new
                    "first_seen": "2026-01-15",
                    "last_seen": "2026-02-26",
                    "corrected_count": 2,
                    "severity": 0.5
                },
                ...
            }
        """
        if not session_error_types:
            return {}
        
        # Query error history for these specific error types
        query = text("""
            SELECT 
                error_type,
                COUNT(*) as total_count,
                MIN(occurred_at) as first_seen,
                MAX(occurred_at) as last_seen,
                SUM(CASE WHEN is_corrected THEN 1 ELSE 0 END) as corrected_count,
                AVG(severity) as avg_severity
            FROM error_history
            WHERE user_id = :uid 
              AND language_id = :lang
              AND error_type = ANY(:error_types)
            GROUP BY error_type
        """)
        
        rows = self.db.execute(query, {
            "uid": user_id,
            "lang": language_id,
            "error_types": list(set(session_error_types))  # Unique error types
        }).fetchall()
        
        error_context = {}
        for row in rows:
            error_type = row[0]
            total_count = row[1]
            first_seen = row[2]
            last_seen = row[3]
            corrected_count = row[4]
            avg_severity = row[5] or 0.5
            
            # Determine trend
            if total_count >= 4:
                trend = "persistent"
            elif corrected_count > 0:
                trend = "improving"
            else:
                trend = "new" if total_count <= 2 else "recurring"
            
            error_context[error_type] = {
                "total_count": total_count,
                "trend": trend,
                "first_seen": first_seen.strftime("%Y-%m-%d") if first_seen else None,
                "last_seen": last_seen.strftime("%Y-%m-%d") if last_seen else None,
                "corrected_count": corrected_count,
                "severity": round(avg_severity, 2)
            }
        
        return error_context
    
    def _get_error_category(self, error_type: str) -> Optional[str]:
        """
        Get the category for an error type from taxonomy.
        
        Args:
            error_type: Error type identifier
        
        Returns: Category name (SYNTAX_ERRORS, LOGIC_ERRORS, etc.) or None
        """
        taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
        
        for category in taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    return category.get('error_category')
        
        return None
    
    def _get_error_languages(self, error_type: str) -> Optional[List[str]]:
        """
        Get the list of applicable languages for an error type.
        
        Args:
            error_type: Error type identifier
        
        Returns: List of language_ids or None if universal
        """
        taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
        
        for category in taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    applies_to = pattern.get('applies_to_languages', [])
                    # Return None for universal errors (empty or "all")
                    if not applies_to or applies_to == ["all"] or "all" in applies_to:
                        return None
                    return applies_to
        
        return None  # Default: universal
    
    def _mark_recommendation_followed(
        self,
        user_id: str,
        language_id: str,
        major_topic_id: str
    ):
        """
        Mark the most recent RL recommendation as followed up if it matches this exam submission.
        Tracks recommendation adherence for effectiveness analysis.
        
        Args:
            user_id: User UUID
            language_id: Language of the exam
            major_topic_id: Topic of the exam submission
        """
        try:
            # Find most recent unfollowed recommendation for this major_topic_id
            # within last 24 hours (to avoid matching old stale recommendations)
            query = text("""
                UPDATE rl_recommendation_history
                SET followed_up = TRUE,
                    followed_up_at = :now
                WHERE id = (
                    SELECT id 
                    FROM rl_recommendation_history
                    WHERE user_id = :user_id
                      AND language_id = :language_id
                      AND major_topic_id = :major_topic_id
                      AND followed_up = FALSE
                      AND created_at > (NOW() - INTERVAL '1 day')
                    ORDER BY created_at DESC
                    LIMIT 1
                )
            """)
            
            result = self.db.execute(query, {
                'user_id': user_id,
                'language_id': language_id,
                'major_topic_id': major_topic_id,
                'now': datetime.now(timezone.utc)
            })
            
            if result.rowcount > 0:
                print(f"✅ Marked RL recommendation as followed: {major_topic_id}")
        
        except Exception as e:
            # Don't fail exam submission if recommendation tracking fails
            print(f"⚠️ Failed to mark recommendation as followed: {e}")
