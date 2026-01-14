from datetime import datetime
from typing import Optional
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

    class Config:
        from_attributes = True

class UploadResult(BaseModel):
    filename: str
    content_type: str
    size: int
    status: str = "success"
    error: Optional[str] = None
    id: Optional[int] = None # Added ID for tracked uploads
