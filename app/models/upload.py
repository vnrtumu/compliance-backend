from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, Float
from sqlalchemy.sql import func
from app.core.db import Base

class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True, nullable=False)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    storage_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Extraction fields
    extraction_status = Column(String, default="pending")  # pending, processing, completed, failed
    extraction_result = Column(JSON, nullable=True)  # Stores the full extraction result
    is_valid = Column(Boolean, default=None, nullable=True)  # Whether document passed validation
    
    # Validation fields
    validation_status = Column(String, default="pending")  # pending, APPROVED, REJECTED, REQUIRES_HUMAN_REVIEW
    validation_result = Column(JSON, nullable=True)  # Stores the full validation result
    compliance_score = Column(Float, nullable=True)  # 0-100 compliance score


