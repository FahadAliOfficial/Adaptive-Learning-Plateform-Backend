"""
Question Bank Models - Optimized for fast querying and deduplication.

Design Decisions:
- UUID primary key (distributed-safe, no auto-increment conflicts)
- JSONB column for flexible question data (PostgreSQL optimized, works with SQLite)
- Composite index on (mapping_id, language_id, difficulty) for fast filtering
- content_hash for O(1) duplicate detection
- UserQuestionHistory for "not seen" tracking

Loophole Fixes:
- Issue #1: Imports from centralized database.py (not creating new Base)
- Issue #3: UserQuestionHistory table for tracking seen questions
- Issue #11: mapping_id indexed for RL model integration
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, JSON, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from database import Base  # ✅ Import shared Base (not creating new one)


class QuestionBank(Base):
    """
    Stores generated MCQs with metadata for intelligent selection.
    
    Key Features:
    - content_hash: Prevents duplicate questions (Issue #12)
    - mapping_id: Links to curriculum (Issue #11 - indexed for RL model)
    - is_verified: Admin approval workflow
    - quality_score: AI self-assessment + human override
    - Analytics fields: For calibration loop (Issue #9)
    """
    __tablename__ = "question_bank"

    # Primary Key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Fast Query Fields (all indexed for performance)
    language_id = Column(String, nullable=False, index=True)  # "python_3", "javascript_es6", etc.
    mapping_id = Column(String, nullable=False, index=True)   # "UNIV_LOOP", "UNIV_VAR", etc. (RL model uses this)
    sub_topic = Column(String, nullable=True)                 # "for_loop_basics", "nested_loops" (Issue #9)
    difficulty = Column(Float, nullable=False, index=True)     # 0.0 (easy) to 1.0 (hard)
    
    # Question Content (stored as JSON for flexibility)
    question_data = Column(JSON, nullable=False)
    # Structure: {
    #   "question_text": "What is the output of this code?",
    #   "code_snippet": "for i in range(3):\n    print(i)",  # Optional - only for code-based questions
    #   "options": [
    #     {"id": "A", "text": "0 1 2", "is_correct": true, "error_type": null},
    #     {"id": "B", "text": "1 2 3", "is_correct": false, "error_type": "OFF_BY_ONE_ERROR"},
    #     {"id": "C", "text": "0 1 2 3", "is_correct": false, "error_type": "LOOP_BOUNDS_ERROR"},
    #     {"id": "D", "text": "Error", "is_correct": false, "error_type": "COMPILATION_MISCONCEPTION"}
    #   ],
    #   "explanation": "range(3) generates numbers 0, 1, 2",
    #   "primary_error_pattern": "LOOP_ERRORS",
    #   "targeted_errors": ["OFF_BY_ONE_ERROR", "LOOP_BOUNDS_ERROR"],
    #   "question_type": "code-based" | "conceptual" | "scenario-based"
    # }
    
    # Deduplication & Quality (Issue #12, #10)
    content_hash = Column(String, unique=True, nullable=False, index=True)  # MD5 hash of content
    is_verified = Column(Boolean, default=False)  # True after admin approval
    quality_score = Column(Float, default=0.5)    # AI self-assessment (0.0-1.0), admin can override
    
    # Analytics (for calibration loop - Issue #9)
    times_used = Column(Integer, default=0)           # How many times shown to students
    times_correct = Column(Integer, default=0)        # How many times answered correctly
    calibrated_difficulty = Column(Float, nullable=True)  # Real difficulty from student performance
    
    # Metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by = Column(String, default="gemini-1.5-pro")  # "human", "gemini-1.5-pro", etc.
    
    # Relationships
    usage_history = relationship("UserQuestionHistory", back_populates="question", cascade="all, delete-orphan")
    
    # Composite Index for "Smart Search" - most common query pattern
    # This makes: SELECT WHERE mapping_id=X AND language_id=Y AND difficulty BETWEEN a AND b
    # run in O(log n) instead of O(n)
    __table_args__ = (
        Index('ix_question_smart_search', 'mapping_id', 'language_id', 'difficulty'),
    )
    
    def __repr__(self):
        return f"<Question {self.id[:8]}... {self.mapping_id} diff={self.difficulty:.2f}>"
    
    def to_dict(self):
        """Convert to dictionary (for API responses)."""
        return {
            "id": self.id,
            "language_id": self.language_id,
            "mapping_id": self.mapping_id,
            "sub_topic": self.sub_topic,
            "difficulty": self.difficulty,
            "question_data": self.question_data,
            "is_verified": self.is_verified,
            "quality_score": self.quality_score,
            "times_used": self.times_used,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class UserQuestionHistory(Base):
    """
    Tracks which questions each user has seen (prevents repetition).
    
    Critical for implementing "exclude seen questions" logic (Issue #3).
    This table is the CORE of the "not seen" functionality.
    
    When a student takes an exam:
    1. Selector queries for questions NOT IN this table for that user
    2. After exam, we INSERT records here for each question shown
    3. Future exams automatically exclude those questions
    """
    __tablename__ = "user_question_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Foreign Keys
    user_id = Column(String, nullable=False, index=True)  # Links to users.id (if you have users table)
    question_id = Column(String, ForeignKey("question_bank.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Context (optional but useful for analytics)
    session_id = Column(String, nullable=True)        # Links to exam_sessions.id (if tracking sessions)
    was_correct = Column(Boolean, nullable=True)      # For difficulty calibration (Issue #9)
    time_spent_seconds = Column(Float, nullable=True) # For analysis (which questions take longest)
    
    # Timestamp
    seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    question = relationship("QuestionBank", back_populates="usage_history")
    
    # Unique Constraint: User can see each question only once
    # This prevents duplicate tracking and ensures "not seen" logic works
    __table_args__ = (
        Index('ix_user_question_unique', 'user_id', 'question_id', unique=True),
    )
    
    def __repr__(self):
        return f"<History user={self.user_id[:8]}... q={self.question_id[:8]}... correct={self.was_correct}>"
    
    def to_dict(self):
        """Convert to dictionary (for API responses)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "question_id": self.question_id,
            "session_id": self.session_id,
            "was_correct": self.was_correct,
            "time_spent_seconds": self.time_spent_seconds,
            "seen_at": self.seen_at.isoformat() if self.seen_at else None
        }
