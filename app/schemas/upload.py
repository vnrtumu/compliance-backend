from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

class UploadBase(BaseModel):
    filename: str
    content_type: str
    size: int

class UploadCreate(UploadBase):
    storage_path: str
    file_hash: Optional[str] = None

class Upload(UploadBase):
    id: int
    created_at: datetime
    extraction_status: Optional[str] = "pending"
    extraction_result: Optional[Dict[str, Any]] = None
    is_valid: Optional[bool] = None
    file_hash: Optional[str] = None
    
    # Validation fields
    validation_status: Optional[str] = "pending"
    validation_result: Optional[Dict[str, Any]] = None
    compliance_score: Optional[float] = None

    class Config:
        from_attributes = True

class UploadResult(BaseModel):
    filename: str
    content_type: str
    size: int
    status: str = "success"
    error: Optional[str] = None
    id: Optional[int] = None  # Added ID for tracked uploads
    imported_count: Optional[int] = None  # Number of invoices imported from JSON


