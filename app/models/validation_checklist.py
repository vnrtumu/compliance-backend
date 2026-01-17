"""
Validation Checklist Model

Master table for all compliance validation checks with complexity ratings.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, Float
from sqlalchemy.sql import func
from app.core.db import Base


class ValidationChecklist(Base):
    __tablename__ = "validation_checklist"

    id = Column(Integer, primary_key=True, index=True)
    
    # Check identification
    check_code = Column(String(20), unique=True, nullable=False, index=True)  # e.g., "GST-001"
    check_name = Column(String(200), nullable=False)
    
    # Categorization
    category = Column(String(50), nullable=False)  # e.g., "GST", "TDS", "DOCUMENT", "POLICY"
    subcategory = Column(String(50), nullable=True)  # e.g., "GSTIN", "IRN", "HSN"
    
    # Check details
    description = Column(Text, nullable=False)
    validation_logic = Column(Text, nullable=True)  # How to validate
    error_message = Column(String(500), nullable=True)  # Message when check fails
    
    # Complexity and scoring
    complexity = Column(String(20), nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    complexity_score = Column(Integer, nullable=False)  # 1-10 scale
    weight = Column(Float, default=1.0)  # Weight in overall compliance score
    
    # Automation
    is_automated = Column(Boolean, default=True)  # Can be auto-checked
    requires_api_call = Column(Boolean, default=False)  # Needs external API
    api_endpoint = Column(String(200), nullable=True)  # Which API to call
    
    # Actions
    auto_reject = Column(Boolean, default=False)  # Auto-reject if fails
    requires_manual_review = Column(Boolean, default=False)  # Needs human review
    
    # Status
    is_active = Column(Boolean, default=True)
    effective_from = Column(String(10), nullable=True)  # Date string YYYY-MM-DD
    effective_to = Column(String(10), nullable=True)
    
    # Reference
    reference_document = Column(String(200), nullable=True)  # GST Act, Policy doc, etc.
    
    def __repr__(self):
        return f"<ValidationCheck {self.check_code}: {self.check_name}>"
