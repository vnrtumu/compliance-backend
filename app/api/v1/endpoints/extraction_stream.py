"""
Streaming Extraction API Endpoints

Endpoints for streaming document extraction with real-time updates.
"""

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api import deps
from app import crud
from app.services.extractor import extractor_agent

router = APIRouter()


async def extraction_stream_generator(upload_id: int, db: Session):
    """
    Generator that yields Server-Sent Events for extraction progress.
    """
    # Get the upload record
    upload = crud.upload.get(db, id=upload_id)
    if not upload:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Upload not found'})}\n\n"
        return

    # Update status to processing
    crud.upload.update(db, db_obj=upload, obj_in={"extraction_status": "processing"})

    # Stream: Starting
    yield f"data: {json.dumps({'type': 'status', 'step': 'starting', 'message': '🚀 Starting AI analysis...'})}\n\n"
    await asyncio.sleep(0.5)

    # Stream: Loading document
    yield f"data: {json.dumps({'type': 'status', 'step': 'loading', 'message': f'📄 Loading document: {upload.filename}'})}\n\n"
    await asyncio.sleep(0.5)

    # Stream: Converting to image (if PDF)
    if upload.filename.lower().endswith('.pdf'):
        yield f"data: {json.dumps({'type': 'status', 'step': 'converting', 'message': '🔄 Converting PDF to image for vision analysis...'})}\n\n"
        await asyncio.sleep(0.5)

    # Stream: Sending to AI
    yield f"data: {json.dumps({'type': 'status', 'step': 'analyzing', 'message': '🤖 Sending to GPT-4o Vision for analysis...'})}\n\n"
    await asyncio.sleep(0.3)

    yield f"data: {json.dumps({'type': 'status', 'step': 'analyzing', 'message': '🔍 Extracting invoice fields...'})}\n\n"
    
    # Perform actual extraction (this is the slow part)
    try:
        result = extractor_agent.analyze_document(upload.storage_path)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Extraction failed: {str(e)}'})}\n\n"
        crud.upload.update(db, db_obj=upload, obj_in={"extraction_status": "failed"})
        return

    # Stream: Processing results
    yield f"data: {json.dumps({'type': 'status', 'step': 'processing', 'message': '⚙️ Processing extraction results...'})}\n\n"
    await asyncio.sleep(0.3)

    # Update database
    update_data = {
        "extraction_status": "completed",
        "extraction_result": result,
        "is_valid": result.get("is_valid_invoice", False)
    }
    crud.upload.update(db, db_obj=upload, obj_in=update_data)

    # Stream: Decision
    decision = result.get("decision", "REJECT")
    if decision == "ACCEPT":
        yield f"data: {json.dumps({'type': 'status', 'step': 'decision', 'message': '✅ Document ACCEPTED for compliance processing'})}\n\n"
    else:
        reasons = result.get("rejection_reasons", [])
        reason_text = reasons[0] if reasons else "Does not meet requirements"
        yield f"data: {json.dumps({'type': 'status', 'step': 'decision', 'message': f'❌ Document REJECTED: {reason_text}'})}\n\n"

    await asyncio.sleep(0.3)

    # Stream: Complete with full result
    yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"


@router.get("/{upload_id}/stream")
async def stream_extraction(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Stream extraction analysis with real-time updates using Server-Sent Events.
    """
    return StreamingResponse(
        extraction_stream_generator(upload_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
