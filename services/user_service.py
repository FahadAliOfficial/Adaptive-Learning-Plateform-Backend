"""
User Service - Handles user registration and state initialization.
Primes new users' knowledge state based on their self-reported experience level.
"""

import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any

from .schemas import UserRegistrationPayload, UserRegistrationResponse
from .config import get_config


class UserService:
    """
    Manages user registration and initial state priming.
    
    When a user registers, this service:
    1. Creates the user record
    2. Reads their experience level configuration
    3. Pre-populates mastery for "assumed_mastered" topics
    4. Returns the starting topic for their learning journey
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.config = get_config()
    
    def register_user(self, payload: UserRegistrationPayload) -> UserRegistrationResponse:
        """
        Register a new user and initialize their learning state.
        
        Workflow:
        1. Check email uniqueness
        2. Create user record
        3. Get experience level configuration
        4. Pre-populate assumed knowledge
        5. Return starting point
        """
        
        # 1. Check if email already exists
        check_email = text("SELECT id FROM users WHERE email = :email")
        existing = self.db.execute(check_email, {"email": payload.email}).fetchone()
        if existing:
            raise ValueError(f"Email '{payload.email}' is already registered")
        
        # 2. Create user record
        user_id = str(uuid.uuid4())
        
        # NOTE: In production, hash the password using bcrypt/passlib!
        # For FYP demo, storing plaintext (not secure for production)
        insert_user = text("""
            INSERT INTO users (id, email, password_hash, last_active_language, created_at)
            VALUES (:id, :email, :password, :language, NOW())
        """)
        
        self.db.execute(insert_user, {
            "id": user_id,
            "email": payload.email,
            "password": payload.password,  # Hash this in production!
            "language": payload.language_id
        })
        
        # 3. Get experience level configuration
        exp_config = self.config.get_experience_config(payload.experience_level)
        initial_mastery = exp_config.get('initial_mastery_estimate', 0.0)
        assumed_mastered = exp_config.get('assumed_mastered', [])
        
        # 4. Pre-populate assumed knowledge
        # If they are "intermediate" or "advanced", give them credit for basics
        for mapping_id in assumed_mastered:
            insert_state = text("""
                INSERT INTO student_state 
                    (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score, last_practiced_at, last_updated)
                VALUES 
                    (:user_id, :mapping_id, :language_id, :mastery, :fluency, :confidence, NOW(), NOW())
            """)
            
            self.db.execute(insert_state, {
                "user_id": user_id,
                "mapping_id": mapping_id,
                "language_id": payload.language_id,
                "mastery": initial_mastery,
                "fluency": 1.2,      # Slightly above average (assumed practice)
                "confidence": 0.5    # Medium confidence (not verified)
            })
        
        # 5. Commit all changes
        self.db.commit()
        
        # 6. Get language-specific starting topic
        starting_mapping_id = exp_config.get('starting_mapping_id', 'UNIV_SYN_LOGIC')
        try:
            starting_topic = self.config.get_major_topic_id(
                payload.language_id, 
                starting_mapping_id
            )
        except ValueError:
            # Fallback to first topic if mapping fails
            starting_topic = f"{payload.language_id[:2].upper()}_SYN_LOGIC"
        
        return UserRegistrationResponse(
            user_id=user_id,
            message=f"User registered successfully at {payload.experience_level} level.",
            starting_topic=starting_topic,
            experience_level=payload.experience_level
        )
    
    def get_user_starting_topic(self, user_id: str, language_id: str) -> Dict[str, Any]:
        """
        Get the recommended starting topic for an existing user.
        Used when user switches languages or resumes learning.
        """
        # Check if user has any mastery in this language
        query = text("""
            SELECT mapping_id, mastery_score 
            FROM student_state 
            WHERE user_id = :user_id AND language_id = :language_id
            ORDER BY mastery_score DESC
        """)
        
        results = self.db.execute(query, {
            "user_id": user_id,
            "language_id": language_id
        }).fetchall()
        
        if not results:
            # New to this language - start from beginning
            return {
                "starting_mapping_id": "UNIV_SYN_LOGIC",
                "starting_topic": self.config.get_major_topic_id(language_id, "UNIV_SYN_LOGIC"),
                "reason": "No prior experience in this language"
            }
        
        # Find the first topic they haven't mastered yet
        mastered_mappings = {row[0] for row in results if row[1] >= 0.65}
        
        for mapping_id in self.config.universal_mappings:
            if mapping_id not in mastered_mappings:
                return {
                    "starting_mapping_id": mapping_id,
                    "starting_topic": self.config.get_major_topic_id(language_id, mapping_id),
                    "reason": f"Next topic to master (current mappings mastered: {len(mastered_mappings)})"
                }
        
        # All mastered - review mode
        return {
            "starting_mapping_id": "UNIV_OOP",
            "starting_topic": self.config.get_major_topic_id(language_id, "UNIV_OOP"),
            "reason": "All topics mastered - review mode"
        }
