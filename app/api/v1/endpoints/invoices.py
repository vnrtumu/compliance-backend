from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api import deps
from app.schemas.upload import Upload
from app import crud

router = APIRouter()

@router.get("/", response_model=List[Upload])
async def get_invoices(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
):
    """
    Retrieve a list of uploaded invoices.
    """
    return crud.upload.get_multi(db, skip=skip, limit=limit)
