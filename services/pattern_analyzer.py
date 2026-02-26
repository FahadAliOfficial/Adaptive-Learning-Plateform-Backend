"""
Pattern Analyzer - Advanced Error Pattern Analysis (Phase 2D, Feature #20)
Detects recurring error patterns and provides targeted remediation.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Dict, List, Any, Tuple
from collections import Counter
from datetime import datetime, timedelta

from .config import get_config


class PatternAnalyzer:
    """Analyzes user error patterns for personalized remediation."""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
        self.taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
    
    def analyze_user_patterns(
        self, 
        user_id: str, 
        language_id: str,
        window_size: int = 50
    ) -> Dict[str, Any]:
        """
        Analyze user's error patterns from recent sessions.
        
        Uses hybrid scoring: frequency × severity for prioritization.
        
        Returns:
            {
                "top_errors": [
                    {
                        "error_type": "OFF_BY_ONE_ERROR",
                        "count": 12,
                        "severity": 0.5,
                        "priority_score": 6.0,
                        "category": "LOOP_ERRORS",
                        "remediation_boost": 0.12,
                        "suggested_practice": "..."
                    }
                ],
                "error_trends": {
                    "improving": [...],
                    "persistent": [...]
                },
                "recommended_remediation": [...],
                "total_errors_analyzed": 45,
                "analysis_window": "last 50 questions"
            }
        """
        
        # Fetch recent errors
        query = text("""
            SELECT error_type, error_category, severity, occurred_at, is_corrected
            FROM error_history
            WHERE user_id = :user_id AND language_id = :lang_id
            ORDER BY occurred_at DESC
            LIMIT :window
        """)
        
        errors = self.db.execute(query, {
            "user_id": user_id,
            "lang_id": language_id,
            "window": window_size
        }).fetchall()
        
        if not errors:
            return {
                "top_errors": [],
                "error_trends": {"improving": [], "persistent": []},
                "recommended_remediation": ["Keep practicing! No error patterns detected yet."],
                "total_errors_analyzed": 0,
                "analysis_window": f"last {window_size} questions"
            }
        
        # Calculate error frequencies and hybrid scores
        error_stats = {}
        for error in errors:
            error_type = error[0]
            category = error[1]
            severity = error[2]
            
            if error_type not in error_stats:
                error_stats[error_type] = {
                    "count": 0,
                    "severity": severity,
                    "category": category,
                    "recent_occurrences": []
                }
            
            error_stats[error_type]["count"] += 1
            error_stats[error_type]["recent_occurrences"].append(error[3])
        
        # Calculate priority scores (frequency × severity)
        top_errors = []
        for error_type, stats in error_stats.items():
            severity = stats["severity"] if stats["severity"] is not None else 0.5
            priority_score = stats["count"] * severity
            metadata = self._get_error_metadata(error_type)
            
            top_errors.append({
                "error_type": error_type,
                "count": stats["count"],
                "severity": severity,
                "priority_score": round(priority_score, 2),
                "category": stats["category"],
                "remediation_boost": metadata.get("remediation_boost", 0.10),
                "suggested_practice": metadata.get("common_message", f"Review {error_type.replace('_', ' ').lower()}")
            })
        
        # Sort by priority score (hybrid: frequency × severity)
        top_errors.sort(key=lambda x: x["priority_score"], reverse=True)
        
        # Detect trends
        trends = self._detect_trends(user_id, language_id)
        
        # Generate remediation plan
        recommendations = self._generate_remediation_plan(top_errors[:5])
        
        return {
            "top_errors": top_errors[:10],  # Top 10
            "error_trends": trends,
            "recommended_remediation": recommendations,
            "total_errors_analyzed": len(errors),
            "analysis_window": f"last {window_size} questions"
        }
    
    def log_error(
        self,
        user_id: str,
        language_id: str,
        mapping_id: str,
        session_id: str,
        question_id: str,
        error_type: str,
        difficulty_tier: int = 1
    ) -> None:
        """
        Log an error to the error_history table.
        Called by GradingService when student gets question wrong.
        """
        
        # Get error metadata
        category, severity = self._get_error_category_and_severity(error_type)
        
        query = text("""
            INSERT INTO error_history (
                user_id, language_id, mapping_id, session_id, question_id,
                error_type, error_category, severity, difficulty_tier
            ) VALUES (
                :user_id, :lang_id, :mapping_id, :session_id, :question_id,
                :error_type, :category, :severity, :tier
            )
        """)
        
        self.db.execute(query, {
            "user_id": user_id,
            "lang_id": language_id,
            "mapping_id": mapping_id,
            "session_id": session_id,
            "question_id": question_id,
            "error_type": error_type,
            "category": category,
            "severity": severity,
            "tier": difficulty_tier
        })
    
    def mark_error_corrected(
        self,
        user_id: str,
        language_id: str,
        error_type: str
    ) -> int:
        """
        Mark errors as corrected when student demonstrates mastery.
        Called when student correctly answers question of same error type.
        
        Returns: Number of errors marked as corrected
        """
        
        query = text("""
            UPDATE error_history
                        SET is_corrected = TRUE, corrected_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id 
              AND language_id = :lang_id
              AND error_type = :error_type
                            AND is_corrected = FALSE
        """)
        
        result = self.db.execute(query, {
            "user_id": user_id,
            "lang_id": language_id,
            "error_type": error_type
        })
        
        return result.rowcount
    
    def _get_error_metadata(self, error_type: str) -> Dict:
        """Fetch error metadata from taxonomy."""
        for category in self.taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    return pattern
        return {}
    
    def _get_error_category_and_severity(self, error_type: str) -> Tuple[str, float]:
        """Get category and severity for an error type."""
        for category in self.taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    return (
                        category.get('error_category', 'UNKNOWN'),
                        pattern.get('severity', 0.5)
                    )
        return ("UNKNOWN", 0.5)
    
    def _detect_trends(self, user_id: str, language_id: str) -> Dict[str, List[str]]:
        """
        Detect error trends: improving vs persistent.
        Compares last 10 sessions vs previous 10 sessions.
        """
        
        # Get session IDs in chronological order (using exam_sessions.created_at for proper ordering)
        session_query = text("""
            SELECT DISTINCT e.session_id
            FROM error_history e
            JOIN exam_sessions es ON e.session_id = es.id
            WHERE e.user_id = :user_id AND e.language_id = :lang_id
            ORDER BY es.created_at DESC
            LIMIT 20
        """)
        
        sessions = self.db.execute(session_query, {
            "user_id": user_id,
            "lang_id": language_id
        }).fetchall()
        
        if len(sessions) < 10:
            return {"improving": [], "persistent": []}
        
        recent_sessions = [s[0] for s in sessions[:10]]
        previous_sessions = [s[0] for s in sessions[10:20]] if len(sessions) >= 20 else []
        
        if not previous_sessions:
            return {"improving": [], "persistent": []}
        
        # Get error frequencies for each period
        recent_errors = self._get_errors_by_sessions(recent_sessions)
        previous_errors = self._get_errors_by_sessions(previous_sessions)
        
        improving = []
        persistent = []
        
        for error_type in set(list(recent_errors.keys()) + list(previous_errors.keys())):
            recent_count = recent_errors.get(error_type, 0)
            previous_count = previous_errors.get(error_type, 0)
            
            if previous_count == 0:
                continue  # New error, can't determine trend
            
            # Calculate percentage change
            change = ((recent_count - previous_count) / previous_count) * 100
            
            if change <= -30:  # 30%+ reduction = improving
                improving.append(error_type)
            elif change >= 0 and recent_count >= 3:  # Same or worse + frequent = persistent
                persistent.append(error_type)
        
        return {
            "improving": improving[:5],  # Top 5
            "persistent": persistent[:5]
        }
    
    def _get_errors_by_sessions(self, session_ids: List[str]) -> Dict[str, int]:
        """Count errors by type for given sessions."""
        if not session_ids:
            return {}
        
        placeholders = ','.join([f':sid{i}' for i in range(len(session_ids))])
        query = text(f"""
            SELECT error_type, COUNT(*) as count
            FROM error_history
            WHERE session_id IN ({placeholders})
            GROUP BY error_type
        """)
        
        params = {f'sid{i}': sid for i, sid in enumerate(session_ids)}
        results = self.db.execute(query, params).fetchall()
        
        return {row[0]: row[1] for row in results}
    
    def _generate_remediation_plan(self, top_errors: List[Dict]) -> List[str]:
        """Generate actionable remediation suggestions."""
        plan = []
        
        for i, error in enumerate(top_errors[:3], 1):  # Top 3 errors
            message = error.get('suggested_practice', '')
            count = error['count']
            severity_label = self._get_severity_label(error['severity'])
            
            plan.append(
                f"{i}. {error['error_type'].replace('_', ' ').title()} "
                f"({severity_label} priority, occurred {count}x) - {message}"
            )
        
        if not plan:
            plan.append("Great work! No major error patterns detected. Keep practicing!")
        
        return plan
    
    def _get_severity_label(self, severity: float) -> str:
        """Convert severity score to label."""
        if severity >= 0.8:
            return "CRITICAL"
        elif severity >= 0.6:
            return "HIGH"
        elif severity >= 0.4:
            return "MEDIUM"
        else:
            return "LOW"
