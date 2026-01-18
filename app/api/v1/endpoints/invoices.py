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

@router.patch("/{invoice_id}/status", response_model=Upload)
async def update_invoice_status(
    invoice_id: int,
    status: str,
    db: Session = Depends(deps.get_db)
):
    """
    Update the status of an invoice (APPROVED/REJECTED).
    """
    upload = crud.upload.get(db, id=invoice_id)
    if not upload:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Update status
    crud.upload.update(db, db_obj=upload, obj_in={
        "invoice_status": status,
        "validation_status": status, # Sync validation status
        "batch_processing_status": "completed" # Ensure it's marked complete
    })
    
    return upload
