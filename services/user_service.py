"""
User Service - Handles user registration and state initialization.
Primes new users' knowledge state based on their self-reported experience level.
"""

import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, Any, Optional
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
            SELECT id, email, password_hash, last_active_language, is_admin
            FROM users
            WHERE email = :email
        """)
        
        user = self.db.execute(query, {"email": payload.email}).fetchone()
        
        if not user:
            raise ValueError("Invalid email or password")
        
        user_id, email, password_hash, last_active_language, is_admin = user
        
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
            last_active_language=last_active_language,
            is_admin=is_admin
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
    
    def get_all_users_admin(self, search_query: Optional[str] = None, status_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all users for admin management with filtering and search.
        
        Args:
            search_query: Optional email/name search term
            status_filter: Optional status filter (active, inactive, suspended, or all)
        
        Returns:
            Dictionary containing user list and statistics
        """
        # Base query for users with their calculated status and statistics
        base_query = """
            SELECT 
                u.id,
                u.email,
                u.created_at,
                u.last_active_language,
                u.total_exams_taken,
                CASE 
                    WHEN es_recent.last_session_date >= NOW() - INTERVAL '30 days' THEN 'active'
                    WHEN es_recent.last_session_date IS NOT NULL THEN 'inactive'
                    ELSE 'inactive'
                END as status,
                COALESCE(es_recent.last_session_date, u.created_at) as last_active,
                COALESCE(completed_sessions.session_count, 0) as sessions_completed,
                COALESCE(avg_mastery.avg_mastery_score, 0.0) as avg_mastery_score
            FROM users u
            LEFT JOIN (
                SELECT 
                    user_id,
                    MAX(completed_at) as last_session_date
                FROM exam_sessions 
                WHERE session_status = 'completed' 
                GROUP BY user_id
            ) es_recent ON u.id = es_recent.user_id
            LEFT JOIN (
                SELECT 
                    user_id,
                    COUNT(*) as session_count
                FROM exam_sessions
                WHERE session_status = 'completed'
                GROUP BY user_id
            ) completed_sessions ON u.id = completed_sessions.user_id
            LEFT JOIN (
                SELECT 
                    user_id,
                    AVG(mastery_score) as avg_mastery_score
                FROM student_state
                GROUP BY user_id
            ) avg_mastery ON u.id = avg_mastery.user_id
        """
        
        # Add search and filter conditions
        where_conditions = []
        params = {}
        
        if search_query:
            where_conditions.append("(LOWER(u.email) LIKE LOWER(:search) OR LOWER(u.email) LIKE LOWER(:search))")
            params["search"] = f"%{search_query}%"
        
        if status_filter and status_filter != "all":
            # Add status filter to HAVING clause since status is calculated
            where_conditions.append("""
                CASE 
                    WHEN es_recent.last_session_date >= NOW() - INTERVAL '30 days' THEN 'active'
                    WHEN es_recent.last_session_date IS NOT NULL THEN 'inactive'
                    ELSE 'inactive'
                END = :status_filter
            """)
            params["status_filter"] = status_filter
        
        if where_conditions:
            final_query = f"{base_query} WHERE {' AND '.join(where_conditions)}"
        else:
            final_query = base_query
        
        final_query += " ORDER BY u.created_at DESC"
        
        users_result = self.db.execute(text(final_query), params).fetchall()
        
        # Process user data
        users = []
        for row in users_result:
            # Extract name from email (everything before @)
            name = row[1].split('@')[0].replace('.', ' ').title()
            
            users.append({
                "id": row[0],
                "email": row[1],
                "name": name,
                "status": row[5],
                "language": row[3] or "Not Set",
                "joinedAt": row[2].isoformat() if row[2] else None,
                "lastActive": row[6].isoformat() if row[6] else None,
                "sessionsCompleted": int(row[7]),
                "avgMastery": round(float(row[8]) * 100, 1) if row[8] else 0.0
            })
        
        # Get count statistics separately to avoid complex grouping
        stats_query = """
            WITH user_stats as (
                SELECT 
                    u.id,
                    CASE 
                        WHEN es_recent.last_session_date >= NOW() - INTERVAL '30 days' THEN 'active'
                        WHEN es_recent.last_session_date IS NOT NULL THEN 'inactive'
                        ELSE 'inactive'
                    END as status
                FROM users u
                LEFT JOIN (
                    SELECT 
                        user_id,
                        MAX(completed_at) as last_session_date
                    FROM exam_sessions 
                    WHERE session_status = 'completed' 
                    GROUP BY user_id
                ) es_recent ON u.id = es_recent.user_id
            )
            SELECT 
                COUNT(*) as total_count,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active_count,
                COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_count,
                COUNT(CASE WHEN status = 'suspended' THEN 1 END) as suspended_count
            FROM user_stats
        """
        
        stats_result = self.db.execute(text(stats_query)).fetchone()
        
        return {
            "users": users,
            "total_count": int(stats_result[0]),
            "active_count": int(stats_result[1]),
            "inactive_count": int(stats_result[2]),
            "suspended_count": int(stats_result[3])
        }
    
    def update_user_status_admin(self, user_id: str, new_status: str) -> Dict[str, Any]:
        """
        Update user status for admin management.
        
        Note: Currently this is a placeholder since the users table doesn't have a status column.
        In production, you would add a status column or use a separate user_status table.
        
        Args:
            user_id: User UUID
            new_status: New status (active, inactive, suspended)
        
        Returns:
            Updated user data
        
        Raises:
            ValueError: If user not found
        """
        # For now, since we don't have a status column, we simulate the update
        # In production, you would add: ALTER TABLE users ADD COLUMN status VARCHAR DEFAULT 'active';
        # Then execute: UPDATE users SET status = :status WHERE id = :user_id
        
        # Verify user exists
        check_user = text("SELECT id, email, created_at FROM users WHERE id = :user_id")
        user = self.db.execute(check_user, {"user_id": user_id}).fetchone()
        
        if not user:
            raise ValueError("User not found")
        
        # In production, uncomment these lines after adding status column:
        # update_status = text("UPDATE users SET status = :status WHERE id = :user_id")
        # self.db.execute(update_status, {"status": new_status, "user_id": user_id})
        # self.db.commit()
        
        # Return updated user data (simulated for now)
        name = user[1].split('@')[0].replace('.', ' ').title()
        
        return {
            "id": user[0],
            "email": user[1],
            "name": name,
            "status": new_status,  # This would come from the database in production
            "language": "Not Set",
            "joinedAt": user[2].isoformat() if user[2] else None,
            "lastActive": None,
            "sessionsCompleted": 0,
            "avgMastery": 0.0
        }
    
    def get_user_analytics_admin(self) -> Dict[str, Any]:
        """
        Get comprehensive user analytics for admin dashboard.
        
        Returns:
            Dictionary containing user statistics and analytics
        """
        # Main analytics query
        analytics_query = """
            WITH user_activity AS (
                SELECT 
                    u.id,
                    u.email,
                    u.created_at,
                    u.last_active_language,
                    CASE 
                        WHEN es_recent.last_session_date >= NOW() - INTERVAL '30 days' THEN 'active'
                        WHEN es_recent.last_session_date IS NOT NULL THEN 'inactive'
                        ELSE 'inactive'
                    END as status,
                    COALESCE(completed_sessions.session_count, 0) as sessions_completed,
                    COALESCE(avg_mastery.avg_mastery_score, 0.0) as avg_mastery_score
                FROM users u
                LEFT JOIN (
                    SELECT 
                        user_id,
                        MAX(completed_at) as last_session_date
                    FROM exam_sessions 
                    WHERE session_status = 'completed' 
                    GROUP BY user_id
                ) es_recent ON u.id = es_recent.user_id
                LEFT JOIN (
                    SELECT 
                        user_id,
                        COUNT(*) as session_count
                    FROM exam_sessions
                    WHERE session_status = 'completed'
                    GROUP BY user_id
                ) completed_sessions ON u.id = completed_sessions.user_id
                LEFT JOIN (
                    SELECT 
                        user_id,
                        AVG(mastery_score) as avg_mastery_score
                    FROM student_state
                    GROUP BY user_id
                ) avg_mastery ON u.id = avg_mastery.user_id
            )
            SELECT 
                COUNT(*) as total_users,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active_users,
                COUNT(CASE WHEN status = 'inactive' THEN 1 END) as inactive_users,
                COUNT(CASE WHEN status = 'suspended' THEN 1 END) as suspended_users,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as new_users_last_7_days,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN 1 END) as new_users_last_30_days,
                AVG(sessions_completed) as avg_sessions_per_user,
                AVG(avg_mastery_score) as avg_mastery_across_platform
            FROM user_activity
        """
        
        analytics_result = self.db.execute(text(analytics_query)).fetchone()
        
        # Language distribution query
        language_query = """
            SELECT 
                COALESCE(last_active_language, 'Not Set') as language,
                COUNT(*) as user_count
            FROM users
            GROUP BY last_active_language
            ORDER BY user_count DESC
        """
        
        language_result = self.db.execute(text(language_query)).fetchall()
        
        # Process language distribution
        languages_distribution = {}
        most_popular_language = "Not Set"
        max_count = 0
        
        for row in language_result:
            language = row[0] if row[0] else "Not Set"
            count = int(row[1])
            languages_distribution[language] = count
            
            if count > max_count:
                max_count = count
                most_popular_language = language
        
        return {
            "total_users": int(analytics_result[0]) if analytics_result[0] else 0,
            "active_users": int(analytics_result[1]) if analytics_result[1] else 0,
            "inactive_users": int(analytics_result[2]) if analytics_result[2] else 0,
            "suspended_users": int(analytics_result[3]) if analytics_result[3] else 0,
            "new_users_last_7_days": int(analytics_result[4]) if analytics_result[4] else 0,
            "new_users_last_30_days": int(analytics_result[5]) if analytics_result[5] else 0,
            "avg_sessions_per_user": round(float(analytics_result[6]), 1) if analytics_result[6] else 0.0,
            "avg_mastery_across_platform": round(float(analytics_result[7]) * 100, 1) if analytics_result[7] else 0.0,
            "most_popular_language": most_popular_language,
            "languages_distribution": languages_distribution
        }

