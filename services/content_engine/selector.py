"""
Intelligent question selection with "not seen" tracking.
Implements multiple selection strategies with graceful fallbacks.
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, not_, func, text
from models.question_bank import QuestionBank, UserQuestionHistory
from typing import List, Optional, Dict
import random
import uuid
from datetime import datetime, timezone


class QuestionSelector:
    """
    Selects optimal questions for exams using multi-strategy approach.
    
    Strategy Priority:
    1. Verified questions user hasn't seen (best)
    2. Unverified questions user hasn't seen (acceptable)
    3. Verified questions user saw long ago (fallback)
    4. Any available questions (emergency fallback)
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def select_questions(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        target_difficulty: float,
        count: int = 10,
        difficulty_tolerance: float = 0.1,
        mode: str = "exam",
        seen_ratio: float = 0.4
    ) -> List[QuestionBank]:
        """
        Select best questions for user.
        
        Args:
            user_id: Student UUID
            language_id: "python_3", "javascript_es6", etc.
            mapping_id: "UNIV_LOOP", "UNIV_VAR", etc.
            target_difficulty: 0.0 to 1.0
            count: Number of questions needed
            difficulty_tolerance: ±range for difficulty matching
        
        Returns:
            List of QuestionBank objects (may be less than count if warehouse empty)
        """
        if mode == "practice":
            return self._select_practice_mix(
                user_id,
                language_id,
                mapping_id,
                target_difficulty,
                difficulty_tolerance,
                count,
                seen_ratio
            )
        
        if mode == "review":
            return self._select_review_mix(
                user_id,
                language_id,
                mapping_id,
                target_difficulty,
                difficulty_tolerance,
                count,
                seen_ratio
            )
        
        return self._select_exam_unseen(
            user_id,
            language_id,
            mapping_id,
            target_difficulty,
            difficulty_tolerance,
            count
        )

    def _get_seen_question_ids(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        exam_only: bool
    ) -> List[str]:
        """
        Fetch question IDs seen by user for this topic.
        If exam_only is True, only include questions from prior exam sessions.
        """
        if exam_only:
            query = text("""
                SELECT h.question_id
                FROM user_question_history h
                JOIN question_bank q ON q.id = h.question_id
                JOIN exam_sessions es ON es.id = h.session_id
                WHERE h.user_id = :u
                  AND q.language_id = :l
                  AND q.mapping_id = :m
                  AND es.session_type = 'exam'
            """)
        else:
            query = text("""
                SELECT h.question_id
                FROM user_question_history h
                JOIN question_bank q ON q.id = h.question_id
                WHERE h.user_id = :u
                  AND q.language_id = :l
                  AND q.mapping_id = :m
            """)
        
        rows = self.db.execute(query, {
            "u": user_id,
            "l": language_id,
            "m": mapping_id
        }).fetchall()
        
        return [row[0] for row in rows]

    def _select_questions_by_ids(
        self,
        question_ids: List[str],
        language_id: str,
        mapping_id: str,
        target_diff: float,
        tolerance: float,
        count: int
    ) -> List[QuestionBank]:
        if not question_ids or count <= 0:
            return []
        
        questions = self.db.query(QuestionBank).filter(
            and_(
                QuestionBank.id.in_(question_ids),
                QuestionBank.language_id == language_id,
                QuestionBank.mapping_id == mapping_id,
                QuestionBank.difficulty.between(target_diff - tolerance, target_diff + tolerance),
                QuestionBank.is_verified == True
            )
        ).order_by(
            QuestionBank.quality_score.desc(),
            func.random()
        ).limit(count * 3).all()
        
        random.shuffle(questions)
        return questions[:count]

    def _select_unseen_questions(
        self,
        exclude_ids: List[str],
        language_id: str,
        mapping_id: str,
        target_diff: float,
        tolerance: float,
        count: int
    ) -> List[QuestionBank]:
        if count <= 0:
            return []
        
        conditions = [
            QuestionBank.language_id == language_id,
            QuestionBank.mapping_id == mapping_id,
            QuestionBank.difficulty.between(target_diff - tolerance, target_diff + tolerance),
            QuestionBank.is_verified == True
        ]
        
        if exclude_ids:
            conditions.append(~QuestionBank.id.in_(exclude_ids))
        
        questions = self.db.query(QuestionBank).filter(
            and_(*conditions)
        ).order_by(
            QuestionBank.quality_score.desc(),
            func.random()
        ).limit(count * 3).all()
        
        random.shuffle(questions)
        return questions[:count]

    def _select_exam_unseen(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        target_diff: float,
        tolerance: float,
        count: int
    ) -> List[QuestionBank]:
        seen_ids = self._get_seen_question_ids(user_id, language_id, mapping_id, exam_only=False)
        return self._select_unseen_questions(
            exclude_ids=seen_ids,
            language_id=language_id,
            mapping_id=mapping_id,
            target_diff=target_diff,
            tolerance=tolerance,
            count=count
        )

    def _select_practice_mix(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        target_diff: float,
        tolerance: float,
        count: int,
        seen_ratio: float
    ) -> List[QuestionBank]:
        seen_target = max(0, int(round(count * seen_ratio)))
        unseen_target = max(0, count - seen_target)
        
        seen_exam_ids = self._get_seen_question_ids(user_id, language_id, mapping_id, exam_only=True)
        all_seen_ids = self._get_seen_question_ids(user_id, language_id, mapping_id, exam_only=False)
        
        seen_questions = self._select_questions_by_ids(
            seen_exam_ids, language_id, mapping_id, target_diff, tolerance, seen_target
        )
        
        # If we don't have enough seen questions, shift the remainder to unseen
        missing_seen = max(0, seen_target - len(seen_questions))
        unseen_target += missing_seen
        
        unseen_questions = self._select_unseen_questions(
            exclude_ids=all_seen_ids,
            language_id=language_id,
            mapping_id=mapping_id,
            target_diff=target_diff,
            tolerance=tolerance,
            count=unseen_target
        )
        
        combined = seen_questions + unseen_questions
        
        # Final fallback: allow verified repeats if still short
        if len(combined) < count:
            fallback = self._select_strategy_3(
                user_id,
                language_id,
                mapping_id,
                target_diff,
                tolerance,
                count - len(combined)
            )
            combined.extend(fallback)
        
        random.shuffle(combined)
        return combined[:count]

    def _select_review_mix(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        target_diff: float,
        tolerance: float,
        count: int,
        seen_ratio: float
    ) -> List[QuestionBank]:
        seen_target = max(0, int(round(count * seen_ratio)))
        unseen_target = max(0, count - seen_target)
        
        seen_ids = self._get_seen_question_ids(user_id, language_id, mapping_id, exam_only=False)
        
        seen_questions = self._select_questions_by_ids(
            seen_ids, language_id, mapping_id, target_diff, tolerance, seen_target
        )
        
        missing_seen = max(0, seen_target - len(seen_questions))
        unseen_target += missing_seen
        
        unseen_questions = self._select_unseen_questions(
            exclude_ids=seen_ids,
            language_id=language_id,
            mapping_id=mapping_id,
            target_diff=target_diff,
            tolerance=tolerance,
            count=unseen_target
        )
        
        combined = seen_questions + unseen_questions
        
        if len(combined) < count:
            fallback = self._select_strategy_3(
                user_id,
                language_id,
                mapping_id,
                target_diff,
                tolerance,
                count - len(combined)
            )
            combined.extend(fallback)
        
        random.shuffle(combined)
        return combined[:count]
    
    def _select_strategy_1(self, user_id, language_id, mapping_id, 
                          target_diff, tolerance, count) -> List[QuestionBank]:
        """
        Strategy 1: Verified questions user hasn't seen.
        This is the ideal case.
        """
        # Get list of seen question IDs
        seen_ids = [row[0] for row in self.db.query(UserQuestionHistory.question_id).filter(
            UserQuestionHistory.user_id == user_id
        ).all()]
        
        # Build filter conditions
        conditions = [
            QuestionBank.language_id == language_id,
            QuestionBank.mapping_id == mapping_id,
            QuestionBank.difficulty.between(
                target_diff - tolerance,
                target_diff + tolerance
            ),
            QuestionBank.is_verified == True  # Only verified
        ]
        
        # Add NOT IN condition if user has seen questions
        if seen_ids:
            conditions.append(~QuestionBank.id.in_(seen_ids))
        
        questions = self.db.query(QuestionBank).filter(
            and_(*conditions)
        ).order_by(
            QuestionBank.quality_score.desc(),  # Best quality first
            func.random()                        # Then randomize
        ).limit(count * 3).all()  # Get 3x for randomization then shuffle
        
        # Shuffle to prevent order-based learning
        random.shuffle(questions)
        
        # Remove duplicates (shouldn't happen but safety check)
        seen_ids_set = set()
        unique_questions = []
        for q in questions:
            if q.id not in seen_ids_set:
                seen_ids_set.add(q.id)
                unique_questions.append(q)
        
        return unique_questions
    
    def _select_strategy_2(self, user_id, language_id, mapping_id,
                          target_diff, tolerance, count) -> List[QuestionBank]:
        """
        Strategy 2: Include unverified questions (if needed).
        """
        # Get list of seen question IDs
        seen_ids = [row[0] for row in self.db.query(UserQuestionHistory.question_id).filter(
            UserQuestionHistory.user_id == user_id
        ).all()]
        
        # Build filter conditions
        conditions = [
            QuestionBank.language_id == language_id,
            QuestionBank.mapping_id == mapping_id,
            QuestionBank.difficulty.between(
                target_diff - tolerance,
                target_diff + tolerance
            ),
            QuestionBank.is_verified == False  # Unverified OK now
        ]
        
        # Add NOT IN condition if user has seen questions
        if seen_ids:
            conditions.append(~QuestionBank.id.in_(seen_ids))
        
        questions = self.db.query(QuestionBank).filter(
            and_(*conditions)
        ).order_by(
            QuestionBank.quality_score.desc(),
            func.random()
        ).limit(count * 3).all()
        
        # Shuffle and remove duplicates
        random.shuffle(questions)
        
        seen_ids_set = set()
        unique_questions = []
        for q in questions:
            if q.id not in seen_ids_set:
                seen_ids_set.add(q.id)
                unique_questions.append(q)
        
        return unique_questions
    
    def _select_strategy_3(self, user_id, language_id, mapping_id,
                          target_diff, tolerance, count) -> List[QuestionBank]:
        """
        Strategy 3: Emergency fallback - allow question repeats.
        Only used when warehouse is critically low.
        """
        questions = self.db.query(QuestionBank).filter(
            and_(
                QuestionBank.language_id == language_id,
                QuestionBank.mapping_id == mapping_id,
                QuestionBank.difficulty.between(
                    target_diff - tolerance,
                    target_diff + tolerance
                )
            )
        ).order_by(
            QuestionBank.is_verified.desc(),
            QuestionBank.quality_score.desc(),
            func.random()
        ).limit(count * 2).all()
        
        # Shuffle and remove duplicates
        random.shuffle(questions)
        
        seen_ids_set = set()
        unique_questions = []
        for q in questions:
            if q.id not in seen_ids_set:
                seen_ids_set.add(q.id)
                unique_questions.append(q)
        
        return unique_questions
    
    def mark_questions_seen(
        self, 
        user_id: str, 
        question_ids: List[str],
        session_id: Optional[str] = None,
        results: Optional[List[Dict]] = None
    ):
        """
        Record that user has seen these questions.
        Uses bulk insert for performance.
        
        Args:
            user_id: Student UUID
            question_ids: List of question UUIDs
            session_id: Optional exam session ID for tracking
            results: Optional list of {question_id, was_correct, time_spent_seconds}
        """
        # Build results map if provided
        results_map = {}
        if results:
            for r in results:
                results_map[r['question_id']] = r
        
        history_records = []
        for q_id in question_ids:
            result_data = results_map.get(q_id, {})
            
            record = UserQuestionHistory(
                id=str(uuid.uuid4()),
                user_id=user_id,
                question_id=q_id,
                session_id=session_id,
                was_correct=result_data.get('was_correct'),
                time_spent_seconds=result_data.get('time_spent_seconds'),
                seen_at=datetime.now(timezone.utc)
            )
            history_records.append(record)
        
        # Bulk insert (much faster than one-by-one)
        self.db.bulk_save_objects(history_records)
        self.db.commit()
    
    def get_warehouse_status(
        self,
        language_id: str,
        mapping_id: str,
        difficulty: float,
        difficulty_tolerance: float = 0.1
    ) -> Dict:
        """
        Check stock levels for a topic/difficulty.
        Useful for triggering background replenishment.
        
        Returns:
            {
                "total": 45,
                "verified": 30,
                "unverified": 15,
                "status": "healthy" | "low" | "critical",
                "avg_quality_score": 0.75
            }
        """
        total = self.db.query(func.count(QuestionBank.id)).filter(
            and_(
                QuestionBank.language_id == language_id,
                QuestionBank.mapping_id == mapping_id,
                QuestionBank.difficulty.between(
                    difficulty - difficulty_tolerance,
                    difficulty + difficulty_tolerance
                )
            )
        ).scalar()
        
        verified = self.db.query(func.count(QuestionBank.id)).filter(
            and_(
                QuestionBank.language_id == language_id,
                QuestionBank.mapping_id == mapping_id,
                QuestionBank.difficulty.between(
                    difficulty - difficulty_tolerance,
                    difficulty + difficulty_tolerance
                ),
                QuestionBank.is_verified == True
            )
        ).scalar()
        
        # Get average quality score
        avg_quality = self.db.query(func.avg(QuestionBank.quality_score)).filter(
            and_(
                QuestionBank.language_id == language_id,
                QuestionBank.mapping_id == mapping_id,
                QuestionBank.difficulty.between(
                    difficulty - difficulty_tolerance,
                    difficulty + difficulty_tolerance
                )
            )
        ).scalar()
        
        # Determine status
        if total >= 50:
            status = "healthy"
        elif total >= 20:
            status = "low"
        else:
            status = "critical"
        
        return {
            "total": total or 0,
            "verified": verified or 0,
            "unverified": (total or 0) - (verified or 0),
            "status": status,
            "avg_quality_score": round(float(avg_quality or 0.5), 2)
        }
    
    def get_user_stats(self, user_id: str, language_id: str) -> Dict:
        """
        Get statistics about user's question history.
        
        Returns:
            {
                "total_seen": 120,
                "accuracy": 0.75,
                "avg_time_per_question": 45.2,
                "topics_covered": ["UNIV_LOOP", "UNIV_VAR", ...]
            }
        """
        # Total questions seen
        total_seen = self.db.query(func.count(UserQuestionHistory.id)).join(
            QuestionBank
        ).filter(
            and_(
                UserQuestionHistory.user_id == user_id,
                QuestionBank.language_id == language_id
            )
        ).scalar()
        
        # Calculate accuracy (only for answered questions)
        answered = self.db.query(UserQuestionHistory).join(
            QuestionBank
        ).filter(
            and_(
                UserQuestionHistory.user_id == user_id,
                QuestionBank.language_id == language_id,
                UserQuestionHistory.was_correct.isnot(None)
            )
        ).all()
        
        accuracy = 0.0
        avg_time = 0.0
        if answered:
            correct_count = sum(1 for h in answered if h.was_correct)
            accuracy = correct_count / len(answered)
            
            times = [h.time_spent_seconds for h in answered if h.time_spent_seconds]
            avg_time = sum(times) / len(times) if times else 0.0
        
        # Get unique topics covered
        topics = self.db.query(QuestionBank.mapping_id).distinct().join(
            UserQuestionHistory
        ).filter(
            and_(
                UserQuestionHistory.user_id == user_id,
                QuestionBank.language_id == language_id
            )
        ).all()
        
        topics_covered = [t[0] for t in topics]
        
        return {
            "total_seen": total_seen or 0,
            "accuracy": round(accuracy, 2),
            "avg_time_per_question": round(avg_time, 1),
            "topics_covered": topics_covered
        }
