"""
Question Reporting Router

Allows students to report issues with questions during or after exams.
Admins can review, resolve, or dismiss reports from the admin dashboard.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from database import get_db
from services.auth import get_current_active_user, get_current_admin_user
from services.schemas import (
    CreateQuestionReportRequest,
    UpdateReportStatusRequest,
    QuestionReportResponse,
    ReportStatsResponse,
    ReportListResponse,
    QuestionPreview
)

router = APIRouter(prefix="/api", tags=["reports"])


@router.post("/reports", response_model=QuestionReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    report: CreateQuestionReportRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Create a new question report (student endpoint).
    
    Students can report issues during or after exams.
    One report per student per question (unique constraint).
    """
    user_id = current_user["id"]
    
    # Verify question exists
    question_check = db.execute(
        text("SELECT id FROM question_bank WHERE id = :qid"),
        {"qid": report.question_id}
    ).fetchone()
    
    if not question_check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found"
        )
    
    # Verify session exists if provided
    if report.session_id:
        session_check = db.execute(
            text("""
                SELECT id FROM exam_sessions 
                WHERE id = :sid AND user_id = :uid
            """),
            {"sid": report.session_id, "uid": user_id}
        ).fetchone()
        
        if not session_check:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or does not belong to you"
            )
    
    # Check for duplicate report (enforced by unique constraint, but friendlier error)
    existing = db.execute(
        text("""
            SELECT id FROM question_reports 
            WHERE question_id = :qid AND reporter_user_id = :uid
        """),
        {"qid": report.question_id, "uid": user_id}
    ).fetchone()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reported this question"
        )
    
    # Create report
    insert_query = text("""
        INSERT INTO question_reports 
        (question_id, reporter_user_id, session_id, report_type, description, status, created_at)
        VALUES (:qid, :uid, :sid, :type, :desc, 'pending', NOW())
        RETURNING id, created_at
    """)
    
    result = db.execute(insert_query, {
        "qid": report.question_id,
        "uid": user_id,
        "sid": report.session_id,
        "type": report.report_type,
        "desc": report.description
    }).fetchone()
    
    db.commit()
    
    # Fetch complete report data
    return await get_report_by_id(result[0], db)


@router.get("/reports/user", response_model=List[QuestionReportResponse])
async def get_user_reports(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all reports created by the current user"""
    user_id = current_user["id"]
    
    query = text("""
        SELECT 
            qr.id, qr.question_id, qr.reporter_user_id, u.email as reporter_email,
            qr.session_id, qr.report_type, qr.description, qr.status,
            qr.created_at, qr.resolved_at, qr.resolved_by,
            resolver.email as resolved_by_email
        FROM question_reports qr
        JOIN users u ON qr.reporter_user_id = u.id
        LEFT JOIN users resolver ON qr.resolved_by = resolver.id
        WHERE qr.reporter_user_id = :uid
        AND (:sid IS NULL OR qr.session_id = :sid)
        ORDER BY qr.created_at DESC
    """)
    
    results = db.execute(query, {"uid": user_id, "sid": session_id}).fetchall()
    
    reports = []
    for row in results:
        reports.append(QuestionReportResponse(
            id=row[0],
            question_id=row[1],
            reporter_user_id=row[2],
            reporter_email=row[3],
            session_id=row[4],
            report_type=row[5],
            description=row[6],
            status=row[7],
            created_at=row[8].isoformat() if row[8] else None,
            resolved_at=row[9].isoformat() if row[9] else None,
            resolved_by=row[10],
            resolved_by_email=row[11],
            question_preview=None
        ))
    
    return reports


@router.get("/admin/reports", response_model=ReportListResponse)
async def get_admin_reports(
    status_filter: Optional[str] = Query("all", regex="^(all|pending|resolved|dismissed)$"),
    question_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Search in description or user email"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get all question reports with filters (admin only).
    
    Supports filtering by status, question_id, and search text.
    Returns paginated results with question preview data.
    """
    
    # Build WHERE conditions
    conditions = []
    params = {"limit": limit, "offset": offset}
    
    if status_filter != "all":
        conditions.append("qr.status = :status")
        params["status"] = status_filter
    
    if question_id:
        conditions.append("qr.question_id = :qid")
        params["qid"] = question_id
    
    if search:
        conditions.append("""(
            LOWER(qr.description) LIKE :search 
            OR LOWER(u.email) LIKE :search
            OR LOWER(qb.question_data->>'question_text') LIKE :search
        )""")
        params["search"] = f"%{search.lower()}%"
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    # Get total count
    count_query = text(f"""
        SELECT COUNT(*) 
        FROM question_reports qr
        JOIN users u ON qr.reporter_user_id = u.id
        LEFT JOIN question_bank qb ON qr.question_id = qb.id
        {where_clause}
    """)
    
    total_count = db.execute(count_query, params).scalar()
    
    # Get reports with full data
    query = text(f"""
        SELECT 
            qr.id, qr.question_id, qr.reporter_user_id, u.email as reporter_email,
            qr.session_id, qr.report_type, qr.description, qr.status,
            qr.created_at, qr.resolved_at, qr.resolved_by,
            resolver.email as resolved_by_email,
            qb.question_data->>'question_text' as question_text,
            qb.language_id, qb.mapping_id, qb.difficulty
        FROM question_reports qr
        JOIN users u ON qr.reporter_user_id = u.id
        LEFT JOIN users resolver ON qr.resolved_by = resolver.id
        LEFT JOIN question_bank qb ON qr.question_id = qb.id
        {where_clause}
        ORDER BY qr.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    
    results = db.execute(query, params).fetchall()
    
    reports = []
    for row in results:
        question_preview = None
        if row[12]:  # question_text exists
            question_preview = QuestionPreview(
                question_text=row[12][:200] + "..." if len(row[12]) > 200 else row[12],
                language_id=row[13] or "unknown",
                mapping_id=row[14] or "unknown",
                difficulty=row[15] or 0.5
            )
        
        reports.append(QuestionReportResponse(
            id=row[0],
            question_id=row[1],
            reporter_user_id=row[2],
            reporter_email=row[3],
            session_id=row[4],
            report_type=row[5],
            description=row[6],
            status=row[7],
            created_at=row[8].isoformat() if row[8] else None,
            resolved_at=row[9].isoformat() if row[9] else None,
            resolved_by=row[10],
            resolved_by_email=row[11],
            question_preview=question_preview
        ))
    
    return ReportListResponse(
        reports=reports,
        total_count=total_count,
        filtered_count=total_count
    )


@router.get("/admin/reports/stats", response_model=ReportStatsResponse)
async def get_report_stats(
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get report statistics for admin dashboard"""
    
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE status = 'pending') as pending,
            COUNT(*) FILTER (WHERE status = 'resolved') as resolved,
            COUNT(*) FILTER (WHERE status = 'dismissed') as dismissed,
            COUNT(*) as total
        FROM question_reports
    """)
    
    result = db.execute(query).fetchone()
    
    return ReportStatsResponse(
        pending_count=result[0] or 0,
        resolved_count=result[1] or 0,
        dismissed_count=result[2] or 0,
        total_count=result[3] or 0
    )


@router.patch("/admin/reports/{report_id}/resolve", response_model=QuestionReportResponse)
async def resolve_report(
    report_id: int,
    update: UpdateReportStatusRequest,
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Mark a report as resolved (admin only)"""
    return await update_report_status(report_id, "resolved", current_user["id"], update.admin_notes, db)


@router.patch("/admin/reports/{report_id}/dismiss", response_model=QuestionReportResponse)
async def dismiss_report(
    report_id: int,
    update: UpdateReportStatusRequest,
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Mark a report as dismissed (admin only)"""
    return await update_report_status(report_id, "dismissed", current_user["id"], update.admin_notes, db)


@router.delete("/admin/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a report (admin only, rare use case)"""
    
    result = db.execute(
        text("DELETE FROM question_reports WHERE id = :rid RETURNING id"),
        {"rid": report_id}
    ).fetchone()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found"
        )
    
    db.commit()
    return None


# Helper functions

async def update_report_status(
    report_id: int,
    new_status: str,
    admin_id: str,
    admin_notes: Optional[str],
    db: Session
) -> QuestionReportResponse:
    """Update report status (resolved/dismissed)"""
    
    # Check if report exists and is pending
    check_query = text("""
        SELECT status FROM question_reports WHERE id = :rid
    """)
    
    existing = db.execute(check_query, {"rid": report_id}).fetchone()
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found"
        )
    
    if existing[0] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Report is already {existing[0]}"
        )
    
    # Update status
    update_query = text("""
        UPDATE question_reports
        SET status = :status,
            resolved_by = :admin_id,
            resolved_at = NOW()
        WHERE id = :rid
    """)
    
    db.execute(update_query, {
        "status": new_status,
        "admin_id": admin_id,
        "rid": report_id
    })
    
    db.commit()
    
    # Return updated report
    return await get_report_by_id(report_id, db)


async def get_report_by_id(report_id: int, db: Session) -> QuestionReportResponse:
    """Fetch complete report data by ID"""
    
    query = text("""
        SELECT 
            qr.id, qr.question_id, qr.reporter_user_id, u.email as reporter_email,
            qr.session_id, qr.report_type, qr.description, qr.status,
            qr.created_at, qr.resolved_at, qr.resolved_by,
            resolver.email as resolved_by_email,
            qb.question_data->>'question_text' as question_text,
            qb.language_id, qb.mapping_id, qb.difficulty
        FROM question_reports qr
        JOIN users u ON qr.reporter_user_id = u.id
        LEFT JOIN users resolver ON qr.resolved_by = resolver.id
        LEFT JOIN question_bank qb ON qr.question_id = qb.id
        WHERE qr.id = :rid
    """)
    
    row = db.execute(query, {"rid": report_id}).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    
    question_preview = None
    if row[12]:
        question_preview = QuestionPreview(
            question_text=row[12][:200] + "..." if len(row[12]) > 200 else row[12],
            language_id=row[13] or "unknown",
            mapping_id=row[14] or "unknown",
            difficulty=row[15] or 0.5
        )
    
    return QuestionReportResponse(
        id=row[0],
        question_id=row[1],
        reporter_user_id=row[2],
        reporter_email=row[3],
        session_id=row[4],
        report_type=row[5],
        description=row[6],
        status=row[7],
        created_at=row[8].isoformat() if row[8] else None,
        resolved_at=row[9].isoformat() if row[9] else None,
        resolved_by=row[10],
        resolved_by_email=row[11],
        question_preview=question_preview
    )
