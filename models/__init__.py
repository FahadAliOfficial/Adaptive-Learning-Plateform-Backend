"""
Database models for FYP backend.
Import Base from database.py (single source of truth).

This package registers all models with SQLAlchemy's Base.
"""
from database import Base

# Import all models to register with Base
from .question_bank import QuestionBank, UserQuestionHistory

__all__ = ['Base', 'QuestionBank', 'UserQuestionHistory']
