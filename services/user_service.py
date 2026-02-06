"""
User Service - Handles user registration and state initialization.
Primes new users' knowledge state based on their self-reported experience level.
"""

import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any
from datetime import datetime

from .schemas import UserRegistrationPayload, UserRegistrationResponse, LoginRequest, LoginResponse, UserProfile
from .config import get_config
from .auth import hash_password, verify_password, create_access_token, create_refresh_token


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
        
        # Hash the password using bcrypt
        hashed_password = hash_password(payload.password)
        
        insert_user = text("""
            INSERT INTO users (id, email, password_hash, last_active_language, created_at)
            VALUES (:id, :email, :password, :language, NOW())
        """)
        
        self.db.execute(insert_user, {
            "id": user_id,
            "email": payload.email,
            "password": hashed_password,
            "language": payload.language_id  # Can be None for new users
        })
        
        # 3. Initialize learning state only if language and experience are provided
        # Otherwise, user will complete onboarding later
        starting_topic = "ONBOARDING_REQUIRED"
        experience_msg = ""
        
        if payload.language_id and payload.experience_level:
            # Get experience level configuration
            exp_config = self.config.get_experience_config(payload.experience_level)
            initial_mastery = exp_config.get('initial_mastery_estimate', 0.0)
            assumed_mastered = exp_config.get('assumed_mastered', [])
            experience_msg = f" at {payload.experience_level} level"
            
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
                
            # Get language-specific starting topic
            starting_mapping_id = exp_config.get('starting_mapping_id', 'UNIV_SYN_LOGIC')
            try:
                starting_topic = self.config.get_major_topic_id(
                    payload.language_id, 
                    starting_mapping_id
                )
            except ValueError:
                # Fallback to first topic if mapping fails
                starting_topic = f"{payload.language_id[:2].upper()}_SYN_LOGIC"
        
        # 5. Commit all changes
        self.db.commit()
        
        # Generate JWT tokens for immediate login after registration
        token_data = {"sub": user_id, "email": payload.email}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token({"sub": user_id})
        
        return UserRegistrationResponse(
            user_id=user_id,
            message=f"User registered successfully{experience_msg}.",
            starting_topic=starting_topic,
            experience_level=payload.experience_level or "not_set",
            access_token=access_token,
            token_type="bearer"
        ), refresh_token  # Return refresh_token separately for cookie
    
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
    
    def login_user(self, payload: LoginRequest) -> LoginResponse:
        """
        Authenticate user and generate JWT tokens.
        
        Args:
            payload: Login credentials (email, password)
        
        Returns:
            LoginResponse with access and refresh tokens
        
        Raises:
            ValueError: If credentials are invalid
        """
        # Fetch user by email
        query = text("""
            SELECT id, email, password_hash, last_active_language
            FROM users
            WHERE email = :email
        """)
        
        user = self.db.execute(query, {"email": payload.email}).fetchone()
        
        if not user:
            raise ValueError("Invalid email or password")
        
        user_id, email, password_hash, last_active_language = user
        
        # Verify password
        if not verify_password(payload.password, password_hash):
            raise ValueError("Invalid email or password")
        
        # Generate JWT tokens
        token_data = {"sub": user_id, "email": email}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token({"sub": user_id})
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user_id=user_id,
            email=email,
            last_active_language=last_active_language
        )
    
    def get_user_profile(self, user_id: str) -> UserProfile:
        """
        Get user profile data.
        
        Args:
            user_id: User UUID
        
        Returns:
            UserProfile with user details
        
        Raises:
            ValueError: If user not found
        """
        query = text("""
            SELECT id, email, last_active_language, total_exams_taken, created_at
            FROM users
            WHERE id = :user_id
        """)
        
        user = self.db.execute(query, {"user_id": user_id}).fetchone()
        
        if not user:
            raise ValueError("User not found")
        
        return UserProfile(
            id=user[0],
            email=user[1],
            last_active_language=user[2],
            total_exams_taken=user[3],
            created_at=user[4].isoformat() if isinstance(user[4], datetime) else str(user[4])
        )
    
    def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """
        Change user password.
        
        Args:
            user_id: User UUID
            current_password: Current password for verification
            new_password: New password to set
        
        Returns:
            True if successful
        
        Raises:
            ValueError: If current password is incorrect
        """
        # Fetch current password hash
        query = text("SELECT password_hash FROM users WHERE id = :user_id")
        result = self.db.execute(query, {"user_id": user_id}).fetchone()
        
        if not result:
            raise ValueError("User not found")
        
        password_hash = result[0]
        
        # Verify current password
        if not verify_password(current_password, password_hash):
            raise ValueError("Current password is incorrect")
        
        # Hash new password
        new_hash = hash_password(new_password)
        
        # Update password
        update_query = text("""
            UPDATE users
            SET password_hash = :new_hash
            WHERE id = :user_id
        """)
        
        self.db.execute(update_query, {"new_hash": new_hash, "user_id": user_id})
        self.db.commit()
        
        return True

