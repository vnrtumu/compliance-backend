"""
Validation API Endpoint

Run LLM-powered compliance validation on uploaded documents.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.api import deps
from app.models.upload import Upload
from app.services.validator import validator_agent


router = APIRouter()


class ValidationResponse(BaseModel):
    upload_id: int
    overall_status: str
    compliance_score: float
    checks_passed: int
    checks_failed: int
    checks_warned: int
    checks_skipped: int
    auto_reject: bool
    validation_results: List[Dict]
    human_intervention: Dict
    llm_reasoning: Optional[str] = None
    detected_anomalies: Optional[List[str]] = None


@router.post("/{upload_id}", response_model=ValidationResponse)
def run_validation(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Run LLM-powered compliance validation on an uploaded document.
    
    Uses GPT-4o to analyze invoice against 45 compliance checks.
    Returns validation results with human intervention requirements.
    """
    # Get upload record
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    # Check if extraction has been done
    if not upload.extraction_result:
        raise HTTPException(
            status_code=400, 
            detail="Document has not been extracted yet. Run extraction first."
        )
    
    # Run LLM validation
    result = validator_agent.validate_document(
        upload_id=upload_id,
        extraction_result=upload.extraction_result
    )
    
    # Store validation result in upload record
    from app import crud
    crud.upload.update(db, db_obj=upload, obj_in={
        "validation_result": result,
        "compliance_score": result.get("compliance_score"),
        "validation_status": result.get("overall_status")
    })
    
    return result


@router.get("/{upload_id}", response_model=ValidationResponse)
def get_validation(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Get existing validation results for an upload.
    If not validated, triggers validation automatically.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    # Check if we have stored validation result
    if upload.validation_result:
        return upload.validation_result
    
    # Otherwise run validation
    return run_validation(upload_id, db)

