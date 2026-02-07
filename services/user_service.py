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
            SELECT id, email, password_hash, last_active_language, is_admin, COALESCE(status, 'active') as status
            FROM users
            WHERE email = :email
        """)
        
        user = self.db.execute(query, {"email": payload.email}).fetchone()
        
        if not user:
            raise ValueError("Invalid email or password")
        
        user_id, email, password_hash, last_active_language, is_admin, status = user

        if status != "active":
            raise ValueError(f"ACCOUNT_STATUS:{status}")
        
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
            is_admin=is_admin,
            status=status
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
                COALESCE(u.status, 'active') as status,
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
            where_conditions.append("COALESCE(u.status, 'active') = :status_filter")
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
            SELECT 
                COUNT(*) as total_count,
                COUNT(CASE WHEN COALESCE(status, 'active') = 'active' THEN 1 END) as active_count,
                COUNT(CASE WHEN COALESCE(status, 'active') = 'inactive' THEN 1 END) as inactive_count,
                COUNT(CASE WHEN COALESCE(status, 'active') = 'suspended' THEN 1 END) as suspended_count
            FROM users
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
        
        Args:
            user_id: User UUID
            new_status: New status (active, inactive, suspended)
        
        Returns:
            Updated user data
        
        Raises:
            ValueError: If user not found
        """
        allowed_statuses = {"active", "inactive", "suspended"}
        if new_status not in allowed_statuses:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(allowed_statuses))}")
        
        update_status = text("UPDATE users SET status = :status WHERE id = :user_id")
        result = self.db.execute(update_status, {"status": new_status, "user_id": user_id})
        if result.rowcount == 0:
            self.db.rollback()
            raise ValueError("User not found")
        
        self.db.commit()
        return self._get_admin_user_data(user_id)
    
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
                    COALESCE(u.status, 'active') as status,
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
    
    def update_user_details_admin(self, user_id: str, request) -> Dict[str, Any]:
        """
        Update user details (admin only).
        
        Admin can update:
        - Display name
        - Language preference
        - Email (though usually restricted)
        """
        try:
            # Check if user exists
            check_user = text("SELECT id, email FROM users WHERE id = :user_id")
            user = self.db.execute(check_user, {"user_id": user_id}).fetchone()
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            
            # Prepare update fields
            update_fields = []
            update_params = {"user_id": user_id}
            
            if hasattr(request, 'name') and request.name is not None:
                update_fields.append("name = :name")
                update_params["name"] = request.name
            
            if hasattr(request, 'language') and request.language is not None:
                update_fields.append("last_active_language = :language")
                update_params["language"] = request.language if request.language else None
            
            if hasattr(request, 'email') and request.email is not None:
                # Email updates are usually restricted, but include for completeness
                # Check if new email is already in use
                check_email = text("SELECT id FROM users WHERE email = :email AND id != :user_id")
                existing = self.db.execute(check_email, {"email": request.email, "user_id": user_id}).fetchone()
                if existing:
                    raise ValueError(f"Email '{request.email}' is already in use by another user")
                
                update_fields.append("email = :email")
                update_params["email"] = request.email
            
            if not update_fields:
                raise ValueError("No valid fields provided for update")
            
            # Execute update
            update_query = f"""
                UPDATE users 
                SET {', '.join(update_fields)}
                WHERE id = :user_id
            """
            
            self.db.execute(text(update_query), update_params)
            self.db.commit()
            
            # Return updated user data
            return self._get_admin_user_data(user_id)
            
        except Exception as e:
            self.db.rollback()
            raise Exception(f"Failed to update user details: {str(e)}")
    
    def reset_user_password_admin(self, user_id: str, new_password: str) -> None:
        """
        Reset a user's password (admin only).
        
        This allows admin to set a new password for users who are locked out
        or need password assistance.
        """
        try:
            # Check if user exists
            check_user = text("SELECT id FROM users WHERE id = :user_id")
            user = self.db.execute(check_user, {"user_id": user_id}).fetchone()
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            
            # Hash the new password
            hashed_password = hash_password(new_password)
            
            # Update password
            update_password = text("""
                UPDATE users 
                SET password_hash = :hashed_password
                WHERE id = :user_id
            """)
            
            self.db.execute(update_password, {
                "hashed_password": hashed_password,
                "user_id": user_id
            })
            self.db.commit()
            
        except Exception as e:
            self.db.rollback()
            raise Exception(f"Failed to reset password: {str(e)}")
    
    def delete_user_admin(self, user_id: str) -> None:
        """
        Permanently delete a user account and all associated data (admin only).
        
        WARNING: This action is irreversible and will delete:
        - User account
        - All learning progress (student_state)
        - All practice sessions
        - All associated data
        
        Use with extreme caution.
        """
        # Start a new transaction to ensure clean state
        self.db.rollback()  # Clear any existing transaction state
        
        try:
            # Check if user exists
            check_user = text("SELECT id, email FROM users WHERE id = :user_id")
            user = self.db.execute(check_user, {"user_id": user_id}).fetchone()
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            
            # Delete in order to maintain referential integrity
            # Use separate try-catch for each deletion to handle missing tables gracefully
            
            # 1. Delete student_state records
            try:
                delete_state = text("DELETE FROM student_state WHERE user_id = :user_id")
                result = self.db.execute(delete_state, {"user_id": user_id})
                print(f"Deleted {result.rowcount} student_state records")
            except Exception as e:
                print(f"Note: student_state deletion issue (table may not exist): {e}")
                # Rollback and start fresh transaction
                self.db.rollback()
            
            # 2. Delete practice sessions (if table exists)
            try:
                delete_sessions = text("DELETE FROM practice_sessions WHERE user_id = :user_id")
                result = self.db.execute(delete_sessions, {"user_id": user_id})
                print(f"Deleted {result.rowcount} practice session records")
            except Exception as e:
                print(f"Note: practice_sessions deletion issue (table may not exist): {e}")
                # Rollback and start fresh transaction
                self.db.rollback()
            
            # 3. Delete any RL model data (if exists)
            try:
                delete_rl_data = text("""
                    DELETE FROM rl_model_states WHERE user_id = :user_id;
                    DELETE FROM rl_training_data WHERE user_id = :user_id;
                """)
                self.db.execute(delete_rl_data, {"user_id": user_id})
            except Exception as e:
                print(f"Note: RL data deletion issue (tables may not exist): {e}")
                # Rollback and start fresh transaction
                self.db.rollback()
            
            # 4. Finally, delete user record (this should always work)
            try:
                delete_user = text("DELETE FROM users WHERE id = :user_id")
                result = self.db.execute(delete_user, {"user_id": user_id})
                if result.rowcount == 0:
                    raise ValueError(f"User {user_id} was not found for deletion")
                print(f"Successfully deleted user record")
                self.db.commit()
                
            except Exception as e:
                self.db.rollback()
                raise Exception(f"Failed to delete user record: {str(e)}")
            
        except ValueError as ve:
            # User not found - this is expected in some cases
            self.db.rollback()
            raise ve
        except Exception as e:
            # Unexpected error
            self.db.rollback()
            raise Exception(f"Failed to delete user: {str(e)}")
    
    def _get_admin_user_data(self, user_id: str) -> Dict[str, Any]:
        """
        Helper method to get formatted user data for admin responses.
        """
        query = text("""
            SELECT 
                u.id,
                u.email,
                SPLIT_PART(u.email, '@', 1) as name,
                COALESCE(u.status, 'active') as status,
                u.last_active_language as language,
                u.created_at,
                COALESCE(es_recent.last_session_date, u.created_at) as last_active,
                COALESCE(completed_sessions.session_count, 0) as sessions_completed,
                COALESCE(avg_mastery.avg_mastery_score, 0.0) as avg_mastery
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
                SELECT user_id, COUNT(*) as session_count
                FROM exam_sessions
                WHERE session_status = 'completed'
                GROUP BY user_id
            ) completed_sessions ON u.id = completed_sessions.user_id
            LEFT JOIN (
                SELECT user_id, AVG(mastery_score) as avg_mastery_score
                FROM student_state
                WHERE user_id = :user_id
                GROUP BY user_id
            ) avg_mastery ON u.id = avg_mastery.user_id
            WHERE u.id = :user_id
        """)
        
        result = self.db.execute(query, {"user_id": user_id}).fetchone()
        
        if not result:
            raise ValueError(f"User with ID {user_id} not found")
        
        return {
            "id": result[0],
            "email": result[1],
            "name": result[2],
            "status": result[3],
            "language": result[4],
            "joinedAt": result[5].isoformat() if result[5] else "",
            "lastActive": result[6].isoformat() if result[6] else None,
            "sessionsCompleted": int(result[7]),
            "avgMastery": round(float(result[8]) * 100, 1) if result[8] else 0.0
        }

