"""
Review Scheduler - Manages spaced repetition intervals (Phase 2C).
Implements SM2-Modified algorithm for optimal retention.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from .config import get_config


class ReviewScheduler:
    """
    Handles automatic review scheduling based on spaced repetition.
    
    Features:
    - Mastery-based interval calculation (0.0-0.4 → 1 day, 0.95-1.0 → 21 days)
    - Personal decay rate tracking (learns user's forgetting curve)
    - Review effectiveness tracking (adjusts intervals based on performance)
    - Priority-based scheduling (urgent reviews surface first)
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
        self.sr_config = self.config.transition_map.get('spaced_repetition_intervals', {})
    
    def schedule_review(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str,
        current_mastery: float
    ):
        """
        Schedule next review for a topic based on current mastery.
        
        Algorithm:
        1. Determine mastery tier from config
        2. Get base interval (days)
        3. Get user's personal decay rate
        4. Adjust interval based on decay rate
        5. Calculate priority (0-5)
        6. Upsert to review_schedule table
        
        Args:
            user_id: User UUID
            language_id: Language (e.g., 'python_3')
            mapping_id: Universal concept (e.g., 'UNIV_LOOP')
            current_mastery: Current mastery score (0.0-1.0)
        """
        
        # 1. Determine mastery tier and base interval
        tier = self._get_mastery_tier(current_mastery)
        base_interval = tier.get('review_after_days', 7)
        
        # 2. Get user's personal decay rate
        decay_rate = self._get_personal_decay_rate(user_id, language_id, mapping_id)
        
        # 3. Adjust interval based on decay rate
        adjusted_interval = self._adjust_interval_for_decay(base_interval, decay_rate)
        
        # 4. Calculate next review date
        next_review = datetime.now(timezone.utc) + timedelta(days=adjusted_interval)
        
        # 5. Calculate priority (0-5, where 5 is most urgent)
        priority = self._calculate_review_priority(current_mastery, adjusted_interval)
        
        # 6. Upsert to database (PostgreSQL syntax)
        review_id = str(uuid.uuid4())
        
        upsert_query = text("""
            INSERT INTO review_schedule 
                (id, user_id, language_id, mapping_id, current_mastery, 
                 next_review_date, review_interval_days, review_priority, 
                 personal_decay_rate, days_since_last_review, updated_at)
            VALUES 
                (:id, :u, :l, :m, :mastery, :next, :interval, :priority, :decay, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, language_id, mapping_id) 
            DO UPDATE SET
                current_mastery = EXCLUDED.current_mastery,
                next_review_date = EXCLUDED.next_review_date,
                review_interval_days = EXCLUDED.review_interval_days,
                review_priority = EXCLUDED.review_priority,
                personal_decay_rate = EXCLUDED.personal_decay_rate,
                days_since_last_review = 0,
                updated_at = CURRENT_TIMESTAMP
        """)
        
        self.db.execute(upsert_query, {
            "id": review_id,
            "u": user_id,
            "l": language_id,
            "m": mapping_id,
            "mastery": current_mastery,
            "next": next_review,
            "interval": adjusted_interval,
            "priority": priority,
            "decay": decay_rate
        })
        
        self.db.commit()
    
    def _get_mastery_tier(self, mastery: float) -> Dict[str, Any]:
        """
        Find appropriate review interval tier for mastery score.
        
        Config structure:
        {
            "mastery_range": [0.0, 0.4],
            "review_after_days": 1,
            "priority": "critical"
        }
        """
        intervals = self.sr_config.get('intervals', [])
        
        for tier in intervals:
            range_min, range_max = tier.get('mastery_range', [0.0, 1.0])
            if range_min <= mastery <= range_max:
                return tier
        
        # Default fallback: weekly review
        return {
            "mastery_range": [0.0, 1.0],
            "review_after_days": 7,
            "priority": "medium"
        }
    
    def _get_personal_decay_rate(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str
    ) -> float:
        """
        Calculate user's personal decay rate for this topic.
        
        Formula: λ = -ln(current_mastery / last_mastery) / days_elapsed
        
        Returns:
            Decay rate (0.005 to 0.05). Higher = faster forgetting.
        """
        # Get current mastery and last practice date
        query = text("""
            SELECT mastery_score, last_practiced_at
            FROM student_state
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        
        result = self.db.execute(query, {
            "u": user_id, "l": language_id, "m": mapping_id
        }).fetchone()
        
        if not result:
            return 0.02  # Default decay rate
        
        current_mastery = result[0]
        last_practiced = result[1]
        
        # Get mastery at last review from review_schedule
        last_review_query = text("""
            SELECT mastery_at_last_review, last_reviewed_at
            FROM review_schedule
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        
        last_review = self.db.execute(last_review_query, {
            "u": user_id, "l": language_id, "m": mapping_id
        }).fetchone()
        
        if not last_review or not last_review[0] or not last_review[1]:
            return 0.02  # No history, use default
        
        last_mastery = last_review[0]
        last_reviewed_at = last_review[1]
        
        # Parse timestamps
        if isinstance(last_reviewed_at, str):
            last_reviewed_at = datetime.fromisoformat(last_reviewed_at.replace('Z', '+00:00'))
        if last_reviewed_at.tzinfo is None:
            last_reviewed_at = last_reviewed_at.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        days_elapsed = (now - last_reviewed_at).total_seconds() / 86400.0
        
        if days_elapsed < 0.1:
            return 0.02  # Too recent to measure
        
        # Prevent division by zero or log of negative
        if current_mastery <= 0 or last_mastery <= 0 or current_mastery >= last_mastery:
            return 0.01  # Slow decayer (or improved)
        
        # Calculate decay rate: λ = -ln(current / last) / days
        try:
            decay_rate = -math.log(current_mastery / last_mastery) / days_elapsed
            # Clamp to reasonable bounds
            return max(0.005, min(decay_rate, 0.05))
        except (ValueError, ZeroDivisionError):
            return 0.02
    
    def _adjust_interval_for_decay(self, base_interval: int, decay_rate: float) -> int:
        """
        Adjust review interval based on personal decay rate.
        
        Fast decayer (λ > 0.03): Shorter intervals (×0.7)
        Slow decayer (λ < 0.015): Longer intervals (×1.3)
        Average: No adjustment
        """
        decay_config = self.sr_config.get('decay_acceleration_factors', {})
        
        # Fast decayer (forgets quickly)
        if decay_rate > 0.03:
            # Use multiplier from config or default 0.7
            multiplier = 1.0 / decay_config.get('no_review_in_7_days', 1.5)
            adjusted = int(base_interval * multiplier)
        
        # Slow decayer (strong retention)
        elif decay_rate < 0.015:
            multiplier = 1.3
            adjusted = int(base_interval * multiplier)
        
        # Average decayer
        else:
            adjusted = base_interval
        
        return max(1, adjusted)  # At least 1 day
    
    def _calculate_review_priority(self, mastery: float, interval_days: int) -> int:
        """
        Calculate urgency priority (0-5).
        
        Higher priority = more urgent to review.
        
        Rules:
        - mastery < 0.5: Priority 5 (critical)
        - mastery < 0.65: Priority 4 (high)
        - interval <= 3 days: Priority 3 (moderate)
        - interval <= 7 days: Priority 2 (low)
        - else: Priority 1 (very low)
        """
        if mastery < 0.5:
            return 5  # Critical
        elif mastery < 0.65:
            return 4  # High
        elif interval_days <= 3:
            return 3  # Moderate
        elif interval_days <= 7:
            return 2  # Low
        else:
            return 1  # Very low
    
    def get_due_reviews(
        self, 
        user_id: str, 
        language_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get all reviews due for a user.
        
        Args:
            user_id: User UUID
            language_id: Optional filter by language
        
        Returns:
            List of topics needing review, sorted by priority DESC, then date ASC.
            
            [
                {
                    "mapping_id": "UNIV_LOOP",
                    "language_id": "python_3",
                    "current_mastery": 0.68,
                    "due_date": datetime,
                    "priority": 3,
                    "days_overdue": 2
                },
                ...
            ]
        """
        if language_id:
            query = text("""
                SELECT 
                    rs.mapping_id,
                    rs.language_id,
                    rs.current_mastery,
                    rs.next_review_date,
                    rs.review_priority,
                    rs.days_since_last_review
                FROM review_schedule rs
                WHERE rs.user_id = :u
                  AND rs.language_id = :l
                  AND rs.next_review_date <= CURRENT_TIMESTAMP
                ORDER BY rs.review_priority DESC, rs.next_review_date ASC
            """)
            
            results = self.db.execute(query, {"u": user_id, "l": language_id}).fetchall()
        else:
            query = text("""
                SELECT 
                    rs.mapping_id,
                    rs.language_id,
                    rs.current_mastery,
                    rs.next_review_date,
                    rs.review_priority,
                    rs.days_since_last_review
                FROM review_schedule rs
                WHERE rs.user_id = :u
                  AND rs.next_review_date <= CURRENT_TIMESTAMP
                ORDER BY rs.review_priority DESC, rs.next_review_date ASC
            """)
            
            results = self.db.execute(query, {"u": user_id}).fetchall()
        
        now = datetime.now(timezone.utc)
        
        reviews = []
        for row in results:
            due_date = row[3]
            
            # Parse timestamp if string
            if isinstance(due_date, str):
                due_date = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
            
            days_overdue = (now - due_date).days
            
            reviews.append({
                "mapping_id": row[0],
                "language_id": row[1],
                "current_mastery": row[2],
                "due_date": due_date,
                "priority": row[4],
                "days_overdue": max(0, days_overdue)
            })
        
        return reviews
    
    def mark_review_completed(
        self, 
        user_id: str, 
        language_id: str, 
        mapping_id: str,
        review_accuracy: float,
        new_mastery: float
    ):
        """
        Update review schedule after completing a review session.
        
        Adjusts future intervals based on performance:
        - Accuracy >= 0.85: Increase interval by 1.5x
        - Accuracy < 0.65: Decrease interval by 0.7x
        
        Args:
            user_id: User UUID
            language_id: Language
            mapping_id: Universal concept
            review_accuracy: Accuracy on review session (0.0-1.0)
            new_mastery: Updated mastery after review
        """
        # Get current review schedule
        current_query = text("""
            SELECT review_interval_days, successful_reviews, failed_reviews, current_mastery
            FROM review_schedule
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        
        current = self.db.execute(current_query, {
            "u": user_id, "l": language_id, "m": mapping_id
        }).fetchone()
        
        if not current:
            # No review scheduled - create one
            self.schedule_review(user_id, language_id, mapping_id, new_mastery)
            return
        
        current_interval = current[0]
        successful = current[1]
        failed = current[2]
        old_mastery = current[3]
        
        # Adjust interval based on review performance
        if review_accuracy >= 0.85:
            # Good review → increase interval
            new_interval = int(current_interval * 1.5)
            successful += 1
        elif review_accuracy < 0.65:
            # Poor review → decrease interval
            new_interval = max(1, int(current_interval * 0.7))
            failed += 1
        else:
            # Moderate review → maintain interval
            new_interval = current_interval
            successful += 1
        
        # Calculate next review date
        next_review = datetime.now(timezone.utc) + timedelta(days=new_interval)
        
        # Update schedule
        update_query = text("""
            UPDATE review_schedule
            SET 
                mastery_at_last_review = :old_mastery,
                current_mastery = :new_mastery,
                review_interval_days = :interval,
                next_review_date = :next,
                successful_reviews = :success,
                failed_reviews = :fail,
                last_reviewed_at = CURRENT_TIMESTAMP,
                days_since_last_review = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        
        self.db.execute(update_query, {
            "old_mastery": old_mastery,
            "new_mastery": new_mastery,
            "interval": new_interval,
            "next": next_review,
            "success": successful,
            "fail": failed,
            "u": user_id,
            "l": language_id,
            "m": mapping_id
        })
        
        self.db.commit()
    
    def get_upcoming_reviews(
        self,
        user_id: str,
        language_id: str = None,
        days_ahead: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get reviews scheduled in the next N days.
        
        Args:
            user_id: User UUID
            language_id: Optional filter by language
            days_ahead: Number of days to look ahead (default: 7)
        
        Returns:
            List of upcoming reviews sorted by date.
        """
        future_date = datetime.now(timezone.utc) + timedelta(days=days_ahead)
        
        if language_id:
            query = text("""
                SELECT 
                    mapping_id,
                    language_id,
                    next_review_date,
                    review_priority,
                    current_mastery,
                    review_interval_days
                FROM review_schedule
                WHERE user_id = :u
                  AND language_id = :l
                  AND next_review_date > CURRENT_TIMESTAMP
                  AND next_review_date <= :future
                ORDER BY next_review_date ASC
            """)
            
            results = self.db.execute(query, {
                "u": user_id, 
                "l": language_id,
                "future": future_date
            }).fetchall()
        else:
            query = text("""
                SELECT 
                    mapping_id,
                    language_id,
                    next_review_date,
                    review_priority,
                    current_mastery,
                    review_interval_days
                FROM review_schedule
                WHERE user_id = :u
                  AND next_review_date > CURRENT_TIMESTAMP
                  AND next_review_date <= :future
                ORDER BY next_review_date ASC
            """)
            
            results = self.db.execute(query, {
                "u": user_id,
                "future": future_date
            }).fetchall()
        
        return [
            {
                "mapping_id": r[0],
                "language_id": r[1],
                "due_date": r[2],
                "priority": r[3],
                "current_mastery": r[4],
                "interval_days": r[5]
            }
            for r in results
        ]
