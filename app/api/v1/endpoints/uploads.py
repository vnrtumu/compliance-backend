import os
import shutil
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session
from app.api import deps
from app.core.config import settings
from app.schemas.upload import UploadResult, Upload, UploadCreate
from app import crud

router = APIRouter()

@router.get("/", response_model=List[Upload])
async def get_uploads(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
):
    """
    Fetch upload history.
    """
    return crud.upload.get_multi(db, skip=skip, limit=limit)

@router.post("/", response_model=List[UploadResult])
async def upload_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(deps.get_db)
):
    results = []
    
    # Ensure upload directory exists
    if not os.path.exists(settings.UPLOAD_DIR):
        os.makedirs(settings.UPLOAD_DIR)
        
    for file in files:
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Save to Database
            db_obj = crud.upload.create(
                db, 
                obj_in=UploadCreate(
                    filename=file.filename,
                    content_type=file.content_type,
                    size=file_size,
                    storage_path=file_path
                )
            )
            
            results.append(UploadResult(
                filename=file.filename,
                content_type=file.content_type,
                size=file_size,
                status="success",
                id=db_obj.id
            ))
        except Exception as e:
            results.append(UploadResult(
                filename=file.filename,
                content_type=file.content_type,
                size=0,
                status="error",
                error=str(e)
            ))
        finally:
            file.file.close()
            
    return results
