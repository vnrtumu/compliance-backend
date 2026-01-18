"""
Resolver API Endpoint

Provides endpoints for conflict resolution and ambiguity handling.
"""

import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, List, Optional, Any

from app.api import deps
from app.models.upload import Upload
from app.services.resolver import resolver_agent
from app.core.config import settings


router = APIRouter()


class ResolveRequest(BaseModel):
    """Request for resolution."""
    batch_context: Optional[Dict] = None
    historical_decisions: Optional[List[Dict]] = None


class ResolutionResponse(BaseModel):
    """Resolution result."""
    upload_id: int
    final_recommendation: str
    confidence_score: float
    requires_human_review: bool
    reasoning: str
    conflicts_detected: int
    ocr_corrections_count: int
    conflict_resolutions: List[Dict] = []
    key_risks: List[str] = []


@router.post("/{upload_id}", response_model=ResolutionResponse)
def resolve_conflicts(
    upload_id: int,
    request: ResolveRequest = ResolveRequest(),
    db: Session = Depends(deps.get_db)
):
    """
    Resolve conflicts and ambiguities for a validated invoice.
    
    Uses LLM to handle:
    - Conflicting GST/TDS regulations
    - OCR errors in GSTIN/PAN
    - Temporal rule application
    - Stateful validation
    - Historical trap detection
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if not upload.extraction_result:
        raise HTTPException(status_code=400, detail="Document not extracted yet")
    
    if not upload.validation_result:
        raise HTTPException(status_code=400, detail="Document not validated yet. Run validation first.")
    
    # Get invoice data
    invoice = upload.extraction_result.get("extracted_fields", {})
    
    # Run resolution
    result = resolver_agent.resolve(
        invoice=invoice,
        validation_result=upload.validation_result,
        batch_context=request.batch_context,
        historical_decisions=request.historical_decisions
    )
    
    # Store resolution result in dedicated column
    from app import crud
    
    crud.upload.update(db, db_obj=upload, obj_in={
        "resolver_result": result
    })
    
    return {
        "upload_id": upload_id,
        **result
    }


async def generate_resolution_stream(upload_id: int, invoice: dict, validation_result: dict):
    """Generate SSE stream for resolution progress."""
    from openai import OpenAI
    
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    # Step 1: OCR Check
    yield f"data: {json.dumps({'step': 'ocr', 'message': '🔍 Checking for OCR errors...'})}\n\n"
    await asyncio.sleep(0.3)
    
    ocr_corrections = resolver_agent._fix_ocr_errors(invoice)
    if ocr_corrections:
        for correction in ocr_corrections:
            msg = f"✏️ Found: {correction['field']} - {correction['correction_type']}"
            yield f"data: {json.dumps({'step': 'ocr_fix', 'message': msg})}\n\n"
            await asyncio.sleep(0.2)
    else:
        yield f"data: {json.dumps({'step': 'ocr_ok', 'message': '✅ No OCR errors detected'})}\n\n"
    
    await asyncio.sleep(0.2)
    
    # Step 2: Conflict Detection
    yield f"data: {json.dumps({'step': 'conflicts', 'message': '⚖️ Detecting regulatory conflicts...'})}\n\n"
    await asyncio.sleep(0.3)
    
    corrected_invoice = resolver_agent._apply_corrections(invoice, ocr_corrections)
    conflicts = resolver_agent._detect_conflicts(corrected_invoice, validation_result)
    
    if conflicts:
        for conflict in conflicts:
            msg = f"⚠️ Conflict: {conflict['conflict_type']} - {conflict['description'][:60]}..."
            yield f"data: {json.dumps({'step': 'conflict_found', 'message': msg})}\n\n"
            await asyncio.sleep(0.2)
    else:
        yield f"data: {json.dumps({'step': 'no_conflicts', 'message': '✅ No conflicts detected'})}\n\n"
    
    await asyncio.sleep(0.2)
    
    # Step 3: Temporal Rules
    yield f"data: {json.dumps({'step': 'temporal', 'message': '📅 Applying temporal rules...'})}\n\n"
    await asyncio.sleep(0.3)
    
    temporal = resolver_agent._apply_temporal_rules(corrected_invoice)
    if temporal.get("fy_transition_warning"):
        warning_msg = temporal.get('fy_transition_warning')
        msg_data = {'step': 'temporal_warn', 'message': f"⚠️ {warning_msg}"}
        yield f"data: {json.dumps(msg_data)}\n\n"
    else:
        yield f"data: {json.dumps({'step': 'temporal_ok', 'message': '✅ Temporal rules applied'})}\n\n"
    
    await asyncio.sleep(0.2)
    
    # Step 4: LLM Resolution
    yield f"data: {json.dumps({'step': 'llm', 'message': '🤖 GPT-4o resolving conflicts...'})}\n\n"
    
    try:
        result = resolver_agent._llm_resolve(
            corrected_invoice,
            validation_result,
            conflicts,
            ocr_corrections,
            temporal,
            {},  # stateful
            {}   # historical
        )
        
        confidence = result.get("confidence_score", 0)
        recommendation = result.get("final_recommendation", "ESCALATE")
        
        if recommendation == "APPROVE":
            yield f"data: {json.dumps({'step': 'complete', 'message': f'✅ Resolved: APPROVE (Confidence: {confidence:.0%})'})}\n\n"
        elif recommendation == "REJECT":
            yield f"data: {json.dumps({'step': 'complete', 'message': f'❌ Resolved: REJECT (Confidence: {confidence:.0%})'})}\n\n"
        else:
            yield f"data: {json.dumps({'step': 'complete', 'message': f'⚠️ Escalate to Human (Confidence: {confidence:.0%})'})}\n\n"
        
        await asyncio.sleep(0.2)
        yield f"data: {json.dumps({'step': 'result', 'result': result})}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'step': 'error', 'message': f'Error: {str(e)}'})}\n\n"


@router.get("/{upload_id}/stream")
async def stream_resolution(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Stream resolution progress using Server-Sent Events.
    
    Note: Can run even if validation hasn't been stored yet - will use
    empty validation result and focus on OCR/conflict detection.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if not upload.extraction_result:
        raise HTTPException(status_code=400, detail="Document not extracted yet")
    
    # Use validation result if available, otherwise empty dict
    validation_result = upload.validation_result or {}
    
    invoice = upload.extraction_result.get("extracted_fields", {})
    
    return StreamingResponse(
        generate_resolution_stream(upload_id, invoice, validation_result),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/{upload_id}")
def get_resolution(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """Get existing resolution result."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if upload.validation_result and upload.validation_result.get("resolution"):
        return {
            "upload_id": upload_id,
            **upload.validation_result["resolution"]
        }
    
    raise HTTPException(status_code=404, detail="No resolution found. Run resolution first.")
