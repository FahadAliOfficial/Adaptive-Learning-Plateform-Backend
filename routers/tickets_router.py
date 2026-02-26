"""
Support Tickets Router

Handles student support ticket creation, messaging, and admin management.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text, func, or_, and_
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

from database import get_db
from services.auth import get_current_active_user

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

# ============================================================================
# Pydantic Models
# ============================================================================

class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=5, max_length=255)
    category: str = Field(..., pattern="^(technical|account|exam|general)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    message: str = Field(..., min_length=10, max_length=5000)

class MessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)

class TicketStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|in_progress|resolved|closed)$")

class TicketAssignment(BaseModel):
    assigned_to: Optional[str] = None

class TicketResponse(BaseModel):
    id: str
    ticket_number: str
    user_id: str
    subject: str
    category: str
    priority: str
    status: str
    assigned_to: Optional[str]
    created_at: str
    updated_at: str
    resolved_at: Optional[str]
    message_count: int

class MessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_id: str
    sender_name: str
    message: str
    is_staff_reply: bool
    created_at: str

class TicketDetailResponse(BaseModel):
    ticket: TicketResponse
    messages: List[MessageResponse]

class TicketStatsResponse(BaseModel):
    total: int
    open: int
    in_progress: int
    resolved: int
    closed: int
    by_category: Dict[str, int]
    by_priority: Dict[str, int]
    avg_resolution_time_hours: Optional[float]

# ============================================================================
# Helper Functions
# ============================================================================

def generate_ticket_number(db: Session) -> str:
    """Generate unique ticket number like TKT-2024-00001"""
    # Get next number from sequence
    result = db.execute(
        text("UPDATE ticket_number_sequence SET next_number = next_number + 1 WHERE id = 1 RETURNING next_number")
    )
    db.commit()
    next_num = result.scalar()
    
    year = datetime.now().year
    return f"TKT-{year}-{next_num:05d}"

def get_user_name(db: Session, user_id: str) -> str:
    """Get user's full name or email"""
    result = db.execute(
        text("SELECT email FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    ).first()
    
    if result:
        return result[0] or "Unknown User"
    return "Unknown User"

def is_admin_user(db: Session, user_id: str) -> bool:
    """Check if a user has admin permissions."""
    result = db.execute(
        text("SELECT is_admin FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    ).first()
    return bool(result and result[0])

def ensure_admin_access(db: Session, user_id: str) -> None:
    """Raise 403 when user is not admin."""
    if not is_admin_user(db, user_id):
        raise HTTPException(status_code=403, detail="Admin access required")

# ============================================================================
# Student Endpoints
# ============================================================================

@router.post("", response_model=TicketResponse)
def create_ticket(
    ticket_data: TicketCreate,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new support ticket"""
    try:
        ticket_id = str(uuid.uuid4())
        ticket_number = generate_ticket_number(db)
        
        # Create ticket
        db.execute(
            text("""
                INSERT INTO support_tickets 
                (id, ticket_number, user_id, subject, category, priority, status)
                VALUES (:id, :ticket_number, :user_id, :subject, :category, :priority, 'open')
            """),
            {
                "id": ticket_id,
                "ticket_number": ticket_number,
                "user_id": current_user["id"],
                "subject": ticket_data.subject,
                "category": ticket_data.category,
                "priority": ticket_data.priority
            }
        )
        
        # Create initial message
        message_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO ticket_messages 
                (id, ticket_id, sender_id, message, is_staff_reply)
                VALUES (:id, :ticket_id, :sender_id, :message, FALSE)
            """),
            {
                "id": message_id,
                "ticket_id": ticket_id,
                "sender_id": current_user["id"],
                "message": ticket_data.message
            }
        )
        
        db.commit()
        
        # Fetch created ticket
        result = db.execute(
            text("""
                SELECT t.*, 
                       (SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = t.id) as message_count
                FROM support_tickets t
                WHERE t.id = :ticket_id
            """),
            {"ticket_id": ticket_id}
        ).first()
        
        return TicketResponse(
            id=result[0],
            ticket_number=result[1],
            user_id=result[2],
            subject=result[3],
            category=result[4],
            priority=result[5],
            status=result[6],
            assigned_to=result[7],
            created_at=result[8].isoformat(),
            updated_at=result[9].isoformat(),
            resolved_at=result[10].isoformat() if result[10] else None,
            message_count=result[11]
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create ticket: {str(e)}")

@router.get("/my", response_model=List[TicketResponse])
def get_my_tickets(
    status: Optional[str] = Query(None, pattern="^(open|in_progress|resolved|closed)$"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get current user's tickets"""
    query = """
        SELECT t.*, 
               (SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = t.id) as message_count
        FROM support_tickets t
        WHERE t.user_id = :user_id
    """
    params = {"user_id": current_user["id"]}
    
    if status:
        query += " AND t.status = :status"
        params["status"] = status
    
    query += " ORDER BY t.updated_at DESC"
    
    results = db.execute(text(query), params).fetchall()
    
    return [
        TicketResponse(
            id=row[0],
            ticket_number=row[1],
            user_id=row[2],
            subject=row[3],
            category=row[4],
            priority=row[5],
            status=row[6],
            assigned_to=row[7],
            created_at=row[8].isoformat(),
            updated_at=row[9].isoformat(),
            resolved_at=row[10].isoformat() if row[10] else None,
            message_count=row[11]
        )
        for row in results
    ]

@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(
    ticket_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get ticket details with messages"""
    # Check if user owns the ticket or is admin
    ticket = db.execute(
        text("SELECT * FROM support_tickets WHERE id = :ticket_id"),
        {"ticket_id": ticket_id}
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    is_admin = is_admin_user(db, current_user["id"])
    if ticket[2] != current_user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get messages
    messages = db.execute(
        text("""
            SELECT tm.*, u.email
            FROM ticket_messages tm
            JOIN users u ON tm.sender_id = u.id
            WHERE tm.ticket_id = :ticket_id
            ORDER BY tm.created_at ASC
        """),
        {"ticket_id": ticket_id}
    ).fetchall()
    
    message_count = len(messages)
    
    return TicketDetailResponse(
        ticket=TicketResponse(
            id=ticket[0],
            ticket_number=ticket[1],
            user_id=ticket[2],
            subject=ticket[3],
            category=ticket[4],
            priority=ticket[5],
            status=ticket[6],
            assigned_to=ticket[7],
            created_at=ticket[8].isoformat(),
            updated_at=ticket[9].isoformat(),
            resolved_at=ticket[10].isoformat() if ticket[10] else None,
            message_count=message_count
        ),
        messages=[
            MessageResponse(
                id=msg[0],
                ticket_id=msg[1],
                sender_id=msg[2],
                sender_name=msg[6] or "Unknown User",
                message=msg[3],
                is_staff_reply=msg[4],
                created_at=msg[5].isoformat()
            )
            for msg in messages
        ]
    )

@router.post("/{ticket_id}/messages", response_model=MessageResponse)
def add_message(
    ticket_id: str,
    message_data: MessageCreate,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add a message to a ticket"""
    # Verify ticket exists and user has access
    ticket = db.execute(
        text("SELECT user_id, status FROM support_tickets WHERE id = :ticket_id"),
        {"ticket_id": ticket_id}
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    is_admin = is_admin_user(db, current_user["id"])
    if ticket[0] != current_user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if ticket[1] == "closed":
        raise HTTPException(status_code=400, detail="Cannot add messages to closed ticket")
    
    try:
        message_id = str(uuid.uuid4())
        is_staff = is_admin_user(db, current_user["id"])
        
        db.execute(
            text("""
                INSERT INTO ticket_messages 
                (id, ticket_id, sender_id, message, is_staff_reply)
                VALUES (:id, :ticket_id, :sender_id, :message, :is_staff)
            """),
            {
                "id": message_id,
                "ticket_id": ticket_id,
                "sender_id": current_user["id"],
                "message": message_data.message,
                "is_staff": is_staff
            }
        )
        
        # Update ticket updated_at
        db.execute(
            text("UPDATE support_tickets SET updated_at = NOW() WHERE id = :ticket_id"),
            {"ticket_id": ticket_id}
        )
        
        db.commit()
        
        sender_name = get_user_name(db, current_user["id"])
        
        return MessageResponse(
            id=message_id,
            ticket_id=ticket_id,
            sender_id=current_user["id"],
            sender_name=sender_name,
            message=message_data.message,
            is_staff_reply=is_staff,
            created_at=datetime.now().isoformat()
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add message: {str(e)}")

# ============================================================================
# Admin Endpoints
# ============================================================================

@router.get("/admin/all", response_model=List[TicketResponse])
def get_all_tickets(
    status: Optional[str] = Query(None, pattern="^(open|in_progress|resolved|closed)$"),
    category: Optional[str] = Query(None, pattern="^(technical|account|exam|general)$"),
    priority: Optional[str] = Query(None, pattern="^(low|normal|high|urgent)$"),
    assigned_to: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all tickets (admin only)"""
    ensure_admin_access(db, current_user["id"])
    
    query = """
        SELECT t.*, 
               (SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = t.id) as message_count
        FROM support_tickets t
        WHERE 1=1
    """
    params = {}
    
    if status:
        query += " AND t.status = :status"
        params["status"] = status
    
    if category:
        query += " AND t.category = :category"
        params["category"] = category
    
    if priority:
        query += " AND t.priority = :priority"
        params["priority"] = priority
    
    if assigned_to:
        if assigned_to.lower() == "unassigned":
            query += " AND t.assigned_to IS NULL"
        else:
            query += " AND t.assigned_to = :assigned_to"
            params["assigned_to"] = assigned_to
    
    if search:
        query += " AND (t.ticket_number ILIKE :search OR t.subject ILIKE :search)"
        params["search"] = f"%{search}%"
    
    query += " ORDER BY t.updated_at DESC"
    
    results = db.execute(text(query), params).fetchall()
    
    return [
        TicketResponse(
            id=row[0],
            ticket_number=row[1],
            user_id=row[2],
            subject=row[3],
            category=row[4],
            priority=row[5],
            status=row[6],
            assigned_to=row[7],
            created_at=row[8].isoformat(),
            updated_at=row[9].isoformat(),
            resolved_at=row[10].isoformat() if row[10] else None,
            message_count=row[11]
        )
        for row in results
    ]

@router.get("/admin/stats", response_model=TicketStatsResponse)
def get_ticket_stats(
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get ticket statistics (admin only)"""
    ensure_admin_access(db, current_user["id"])
    
    # Overall counts
    total = db.execute(text("SELECT COUNT(*) FROM support_tickets")).scalar()
    open_count = db.execute(text("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")).scalar()
    in_progress = db.execute(text("SELECT COUNT(*) FROM support_tickets WHERE status = 'in_progress'")).scalar()
    resolved = db.execute(text("SELECT COUNT(*) FROM support_tickets WHERE status = 'resolved'")).scalar()
    closed = db.execute(text("SELECT COUNT(*) FROM support_tickets WHERE status = 'closed'")).scalar()
    
    # By category
    category_results = db.execute(
        text("SELECT category, COUNT(*) FROM support_tickets GROUP BY category")
    ).fetchall()
    by_category = {row[0]: row[1] for row in category_results}
    
    # By priority
    priority_results = db.execute(
        text("SELECT priority, COUNT(*) FROM support_tickets GROUP BY priority")
    ).fetchall()
    by_priority = {row[0]: row[1] for row in priority_results}
    
    # Average resolution time
    avg_time = db.execute(
        text("""
            SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)
            FROM support_tickets
            WHERE resolved_at IS NOT NULL
        """)
    ).scalar()
    
    return TicketStatsResponse(
        total=total,
        open=open_count,
        in_progress=in_progress,
        resolved=resolved,
        closed=closed,
        by_category=by_category,
        by_priority=by_priority,
        avg_resolution_time_hours=round(avg_time, 2) if avg_time else None
    )

@router.patch("/admin/{ticket_id}/status")
def update_ticket_status(
    ticket_id: str,
    status_data: TicketStatusUpdate,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update ticket status (admin only)"""
    ensure_admin_access(db, current_user["id"])
    
    # Check ticket exists
    ticket = db.execute(
        text("SELECT id, status FROM support_tickets WHERE id = :ticket_id"),
        {"ticket_id": ticket_id}
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    try:
        resolved_at = None
        if status_data.status in ["resolved", "closed"] and ticket[1] not in ["resolved", "closed"]:
            resolved_at = datetime.now()
        
        if resolved_at:
            db.execute(
                text("""
                    UPDATE support_tickets 
                    SET status = :status, resolved_at = :resolved_at, updated_at = NOW()
                    WHERE id = :ticket_id
                """),
                {"ticket_id": ticket_id, "status": status_data.status, "resolved_at": resolved_at}
            )
        else:
            db.execute(
                text("""
                    UPDATE support_tickets 
                    SET status = :status, updated_at = NOW()
                    WHERE id = :ticket_id
                """),
                {"ticket_id": ticket_id, "status": status_data.status}
            )
        
        db.commit()
        return {"message": "Status updated successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")

@router.patch("/admin/{ticket_id}/assign")
def assign_ticket(
    ticket_id: str,
    assignment_data: TicketAssignment,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Assign ticket to admin (admin only)"""
    ensure_admin_access(db, current_user["id"])
    
    # Check ticket exists
    ticket = db.execute(
        text("SELECT id FROM support_tickets WHERE id = :ticket_id"),
        {"ticket_id": ticket_id}
    ).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Verify assigned user is admin if provided
    if assignment_data.assigned_to:
        if not is_admin_user(db, assignment_data.assigned_to):
            raise HTTPException(status_code=400, detail="Can only assign to admin")
    
    try:
        db.execute(
            text("""
                UPDATE support_tickets 
                SET assigned_to = :assigned_to, updated_at = NOW()
                WHERE id = :ticket_id
            """),
            {"ticket_id": ticket_id, "assigned_to": assignment_data.assigned_to}
        )
        db.commit()
        return {"message": "Ticket assigned successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to assign ticket: {str(e)}")

@router.delete("/admin/{ticket_id}")
def delete_ticket(
    ticket_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a ticket (admin only)"""
    ensure_admin_access(db, current_user["id"])
    
    try:
        result = db.execute(
            text("DELETE FROM support_tickets WHERE id = :ticket_id"),
            {"ticket_id": ticket_id}
        )
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        return {"message": "Ticket deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete ticket: {str(e)}")
