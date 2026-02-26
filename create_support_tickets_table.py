"""
Migration: Create support_tickets and ticket_messages tables for student support system

Allows students to create support tickets for queries and issues.
Admins can view, reply, assign, and manage tickets.
"""

from sqlalchemy import text
from database import engine

def create_support_tickets_tables():
    """Create support_tickets and ticket_messages tables with proper constraints"""
    
    with engine.connect() as conn:
        # Create ticket_number_sequence table first
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ticket_number_sequence (
                id INTEGER PRIMARY KEY DEFAULT 1,
                next_number INTEGER NOT NULL DEFAULT 1
            )
        """))
        conn.commit()
        
        # Initialize sequence if empty
        conn.execute(text("""
            INSERT INTO ticket_number_sequence (id, next_number) 
            SELECT 1, 1 WHERE NOT EXISTS (SELECT 1 FROM ticket_number_sequence WHERE id = 1)
        """))
        conn.commit()
        
        # Create support_tickets table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id VARCHAR(255) PRIMARY KEY,
                ticket_number VARCHAR(50) UNIQUE NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                subject VARCHAR(255) NOT NULL,
                category VARCHAR(20) NOT NULL DEFAULT 'general',
                priority VARCHAR(20) NOT NULL DEFAULT 'normal',
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                assigned_to VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                resolved_at TIMESTAMP WITH TIME ZONE,
                
                CONSTRAINT fk_ticket_user FOREIGN KEY (user_id) 
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_ticket_assigned FOREIGN KEY (assigned_to) 
                    REFERENCES users(id) ON DELETE SET NULL,
                CONSTRAINT chk_category CHECK (category IN ('technical', 'account', 'exam', 'general')),
                CONSTRAINT chk_priority CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                CONSTRAINT chk_status CHECK (status IN ('open', 'in_progress', 'resolved', 'closed'))
            )
        """))
        conn.commit()
        
        # Create indexes for support_tickets
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tickets_user ON support_tickets(user_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tickets_assigned ON support_tickets(assigned_to)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tickets_number ON support_tickets(ticket_number)
        """))
        conn.commit()
        
        # Create ticket_messages table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id VARCHAR(255) PRIMARY KEY,
                ticket_id VARCHAR(255) NOT NULL,
                sender_id VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                is_staff_reply BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                
                CONSTRAINT fk_message_ticket FOREIGN KEY (ticket_id) 
                    REFERENCES support_tickets(id) ON DELETE CASCADE,
                CONSTRAINT fk_message_sender FOREIGN KEY (sender_id) 
                    REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        
        # Create index for ticket_messages
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_ticket ON ticket_messages(ticket_id)
        """))
        conn.commit()
        
        print("✅ Support tickets tables created successfully!")
        print("✅ Created: support_tickets, ticket_messages, ticket_number_sequence")

if __name__ == "__main__":
    create_support_tickets_tables()
