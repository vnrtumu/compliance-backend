"""
Extraction API Endpoints

Endpoints for triggering and retrieving document extraction results.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app import crud
from app.schemas.extraction import ExtractionResult
from app.services.extractor import extractor_agent

router = APIRouter()


@router.post("/{upload_id}", response_model=ExtractionResult)
async def extract_document(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Trigger extraction analysis for an uploaded document.
    
    This endpoint:
    1. Retrieves the upload record
    2. Runs the AI extractor agent on the document
    3. Updates the upload with extraction results
    4. Returns the extraction result
    """
    # Get the upload record
    upload = crud.upload.get(db, id=upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    # Run extraction
    result = extractor_agent.analyze_document(upload.storage_path)
    
    # Update the upload record with extraction results
    update_data = {
        "extraction_status": "completed",
        "extraction_result": result,
        "is_valid": result.get("is_valid_invoice", False)
    }
    crud.upload.update(db, db_obj=upload, obj_in=update_data)
    
    return ExtractionResult(
        upload_id=upload_id,
        is_valid_invoice=result.get("is_valid_invoice", False),
        decision=result.get("decision", "REJECT"),
        document_type=result.get("document_type", "unknown"),
        confidence_score=result.get("confidence_score", 0.0),
        rejection_reasons=result.get("rejection_reasons", []),
        extracted_fields=result.get("extracted_fields", {})
    )


@router.get("/{upload_id}", response_model=ExtractionResult)
async def get_extraction_result(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Get the extraction result for an upload.
    
    If extraction hasn't been run yet, triggers it automatically.
    """
    upload = crud.upload.get(db, id=upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    # Check if extraction has been done
    if upload.extraction_status == "completed" and upload.extraction_result:
        result = upload.extraction_result
        return ExtractionResult(
            upload_id=upload_id,
            is_valid_invoice=result.get("is_valid_invoice", False),
            decision=result.get("decision", "REJECT"),
            document_type=result.get("document_type", "unknown"),
            confidence_score=result.get("confidence_score", 0.0),
            rejection_reasons=result.get("rejection_reasons", []),
            extracted_fields=result.get("extracted_fields", {})
        )
    
    # If not done, trigger extraction
    return await extract_document(upload_id, db)
