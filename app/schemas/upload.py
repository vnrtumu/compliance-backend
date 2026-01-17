from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

class UploadBase(BaseModel):
    filename: str
    content_type: str
    size: int

class UploadCreate(UploadBase):
    storage_path: str

class Upload(UploadBase):
    id: int
    created_at: datetime
    extraction_status: Optional[str] = "pending"
    extraction_result: Optional[Dict[str, Any]] = None
    is_valid: Optional[bool] = None

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


