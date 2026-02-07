"""
Analytics Router - Provides endpoints for student learning analytics.

Exposes multi-level analytics service through REST API.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services.multi_level_analytics_service import MultiLevelAnalyticsService
from services.auth import get_current_active_user, get_current_admin_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/student/{user_id}/profile")
def get_student_error_profile(
    user_id: str,
    language_id: str = Query(..., description="Language to analyze (e.g., 'python_3')"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive error analysis for a specific student.
    
    **Use Case:** Student dashboard showing their learning profile
    
    **Example:**
    GET /analytics/student/user123/profile?language_id=python_3
    
    **Returns:**
    - Major topic performance
    - Sub-topic error patterns
    - Most common errors
    - Personalized improvement areas
    """
    # Verify user can only access their own profile
    if current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Cannot access other user's analytics")
    
    analytics = MultiLevelAnalyticsService(db)
    profile = analytics.get_student_error_profile(user_id, language_id)
    
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
    
    return {
        "success": True,
        "user_id": user_id,
        "language_id": language_id,
        "profile": profile
    }


@router.get("/subtopic/{sub_topic}/errors")
def get_subtopic_error_distribution(
    sub_topic: str,
    language_id: str = Query(..., description="Language (e.g., 'python_3')"),
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Analyze error patterns for a specific sub-topic across all students.
    
    **Use Case:** Teacher view - "What mistakes do students make in for_loop_basics?"
    
    **Example:**
    GET /analytics/subtopic/for_loop_basics/errors?language_id=python_3
    
    **Returns:**
    - Total attempts
    - Error distribution percentages
    - Most common error type
    - Overall accuracy rate
    
    **Requires:** Admin/teacher authentication
    """
    analytics = MultiLevelAnalyticsService(db)
    distribution = analytics.get_sub_topic_error_distribution(language_id, sub_topic)
    
    if "error" in distribution:
        raise HTTPException(status_code=404, detail=distribution["error"])
    
    return {
        "success": True,
        "data": distribution
    }


@router.get("/student/{user_id}/cross-topic-analysis")
def get_cross_topic_error_analysis(
    user_id: str,
    language_id: str = Query(..., description="Language (e.g., 'python_3')"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Analyze how error patterns manifest across different sub-topics for a student.
    
    **Use Case:** Detailed diagnostics - "Where does this student make scope errors?"
    
    **Example:**
    GET /analytics/student/user123/cross-topic-analysis?language_id=python_3
    
    **Returns:**
    - Error patterns broken down by sub-topic
    - Sub-topic performance summary
    - Targeted recommendations
    """
    # Verify user can only access their own analysis
    if current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Cannot access other user's analytics")
    
    analytics = MultiLevelAnalyticsService(db)
    analysis = analytics.get_cross_topic_error_analysis(user_id, language_id)
    
    return {
        "success": True,
        "data": analysis
    }


@router.get("/student/{user_id}/recommendations")
def get_personalized_recommendations(
    user_id: str,
    language_id: str = Query(..., description="Language (e.g., 'python_3')"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get actionable learning recommendations for a student.
    
    **Use Case:** Student dashboard - "What should I practice next?"
    
    **Example:**
    GET /analytics/student/user123/recommendations?language_id=python_3
    
    **Returns:**
    - Specific improvement areas
    - Targeted practice suggestions
    - Priority topics
    """
    # Verify user can only access their own recommendations
    if current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Cannot access other user's recommendations")
    
    analytics = MultiLevelAnalyticsService(db)
    profile = analytics.get_student_error_profile(user_id, language_id)
    
    if "error" in profile:
        raise HTTPException(status_code=404, detail=profile["error"])
    
    return {
        "success": True,
        "user_id": user_id,
        "language_id": language_id,
        "improvement_areas": profile.get("improvement_areas", []),
        "most_common_errors": profile.get("most_common_errors", [])[:5],
        "weak_subtopics": [
            {
                "subtopic": subtopic,
                "accuracy": data["accuracy_percentage"],
                "top_error": list(data["error_distribution"].keys())[0] if data["error_distribution"] else None
            }
            for subtopic, data in profile.get("sub_topic_error_patterns", {}).items()
            if data["accuracy_percentage"] < 60
        ]
    }


@router.get("/class-insights")
def get_class_wide_insights(
    language_id: str = Query(..., description="Language (e.g., 'python_3')"),
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get aggregated insights across all students for a language.
    
    **Use Case:** Teacher dashboard - "Which topics are hardest for the class?"
    
    **Example:**
    GET /analytics/class-insights?language_id=python_3
    
    **Returns:**
    - Most difficult sub-topics
    - Common error patterns across all students
    
    **Requires:** Admin/teacher authentication
    """
    # Get all sub-topics for this language from question bank
    from sqlalchemy import text
    
    subtopics_query = text("""
        SELECT DISTINCT sub_topic FROM question_bank 
        WHERE language_id = :lang_id AND sub_topic IS NOT NULL
    """)
    
    subtopics = [row[0] for row in db.execute(subtopics_query, {"lang_id": language_id}).fetchall()]
    
    analytics = MultiLevelAnalyticsService(db)
    
    # Analyze each sub-topic
    subtopic_difficulties = []
    for subtopic in subtopics:
        distribution = analytics.get_sub_topic_error_distribution(language_id, subtopic)
        
        if "error" not in distribution:
            subtopic_difficulties.append({
                "subtopic": subtopic,
                "accuracy_rate": distribution.get("accuracy_rate", 0),
                "total_attempts": distribution.get("total_attempts", 0),
                "most_common_error": distribution.get("most_common_error")
            })
    
    # Sort by difficulty (lowest accuracy first)
    subtopic_difficulties.sort(key=lambda x: x["accuracy_rate"])
    
    return {
        "success": True,
        "language_id": language_id,
        "total_subtopics_analyzed": len(subtopic_difficulties),
        "hardest_subtopics": subtopic_difficulties[:5],
        "easiest_subtopics": subtopic_difficulties[-5:][::-1]
    }
