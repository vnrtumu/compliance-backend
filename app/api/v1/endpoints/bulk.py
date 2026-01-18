"""
Bulk Processing API Endpoints

Provides endpoints for bulk invoice processing and consolidated reporting.
"""

import uuid
import json
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api import deps
from app.models.upload import Upload
from app.services.bulk_processor import bulk_processor
from app import crud


router = APIRouter()


class BulkProcessRequest(BaseModel):
    """Request to process multiple invoices."""
    upload_ids: Optional[List[int]] = None  # Process specific upload IDs
    batch_id: Optional[str] = None  # Or process all in a batch


class BatchStatusResponse(BaseModel):
    """Batch processing status response."""
    batch_id: str
    total_invoices: int
    pending: int
    processing: int
    completed: int
    failed: int


@router.post("/process")
async def process_bulk_invoices(
    request: BulkProcessRequest,
    db: Session = Depends(deps.get_db)
):
    """
    Process multiple invoices through all 4 agents (Extractor, Validator, Resolver, Reporter).
    
    Either provide:
    - upload_ids: List of specific upload IDs to process
    - batch_id: Process all invoices in a batch
    
    Returns processing results with statistics.
    """
    upload_ids = []
    
    if request.upload_ids:
        upload_ids = request.upload_ids
    elif request.batch_id:
        # Get all upload IDs for this batch
        uploads = db.query(Upload).filter(Upload.batch_id == request.batch_id).all()
        upload_ids = [u.id for u in uploads]
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either upload_ids or batch_id"
        )
    
    if not upload_ids:
        raise HTTPException(
            status_code=404,
            detail="No invoices found to process"
        )
    
    # Process the batch
    result = await bulk_processor.process_batch(upload_ids, db)
    
    return result


@router.get("/status/{batch_id}", response_model=BatchStatusResponse)
def get_batch_status(
    batch_id: str,
    db: Session = Depends(deps.get_db)
):
    """
    Get processing status for a batch of invoices.
    """
    uploads = db.query(Upload).filter(Upload.batch_id == batch_id).all()
    
    if not uploads:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    pending = sum(1 for u in uploads if u.batch_processing_status == "pending" or u.batch_processing_status is None)
    processing = sum(1 for u in uploads if u.batch_processing_status == "processing")
    completed = sum(1 for u in uploads if u.batch_processing_status == "completed")
    failed = sum(1 for u in uploads if u.batch_processing_status == "failed")
    
    return BatchStatusResponse(
        batch_id=batch_id,
        total_invoices=len(uploads),
        pending=pending,
        processing=processing,
        completed=completed,
        failed=failed
    )


@router.post("/report/{batch_id}")
def generate_bulk_report(
    batch_id: str,
    db: Session = Depends(deps.get_db)
):
    """
    Generate consolidated report for a batch of invoices.
    
    Returns vendor-wise breakdown, common issues, and aggregate statistics.
    """
    report = bulk_processor.generate_bulk_report(batch_id, db)
    
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    
    return report


@router.get("/report/{batch_id}")
def get_bulk_report(
    batch_id: str,
    db: Session = Depends(deps.get_db)
):
    """
    Get existing or generate new bulk report for a batch.
    """
    return generate_bulk_report(batch_id, db)


async def generate_processing_stream(upload_ids: List[int], batch_id: str, db: Session):
    """Generate SSE stream for bulk processing progress."""
    total = len(upload_ids)
    
    yield f"data: {json.dumps({'step': 'start', 'message': f'🚀 Starting bulk processing of {total} invoices...', 'batch_id': batch_id})}\n\n"
    await asyncio.sleep(0.3)
    
    processed = 0
    approved = 0
    rejected = 0
    needs_review = 0
    
    for upload_id in upload_ids:
        try:
            yield f"data: {json.dumps({'step': 'processing', 'message': f'📄 Processing invoice {processed + 1}/{total}...', 'upload_id': upload_id})}\n\n"
            
            # Process single invoice
            result = await bulk_processor.process_single_invoice(upload_id, db)
            
            processed += 1
            
            if result.get("status") == "completed":
                status = result.get("invoice_status", "UNKNOWN")
                if status == "APPROVED":
                    approved += 1
                    emoji = "✅"
                elif status == "REJECTED":
                    rejected += 1
                    emoji = "❌"
                else:
                    needs_review += 1
                    emoji = "⚠️"
                
                msg = f"{emoji} Invoice {processed}/{total}: {status}"
                yield f"data: {json.dumps({'step': 'completed', 'message': msg, 'upload_id': upload_id, 'status': status})}\n\n"
            else:
                error_msg = result.get('error', 'Unknown')
                msg = f"❌ Invoice {processed}/{total}: Error - {error_msg}"
                yield f"data: {json.dumps({'step': 'error', 'message': msg, 'upload_id': upload_id})}\n\n"
            
            await asyncio.sleep(0.1)
            
        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'message': f'❌ Error processing invoice {upload_id}: {str(e)}'})}\n\n"
    
    # Final summary
    yield f"data: {json.dumps({'step': 'summary', 'message': f'📊 Batch complete: {approved} approved, {rejected} rejected, {needs_review} need review'})}\n\n"
    
    # Generate final report
    yield f"data: {json.dumps({'step': 'report', 'message': '📝 Generating consolidated report...'})}\n\n"
    await asyncio.sleep(0.3)
    
    report = bulk_processor.generate_bulk_report(batch_id, db)
    yield f"data: {json.dumps({'step': 'complete', 'message': '✅ Bulk processing complete!', 'result': report})}\n\n"


@router.post("/process/stream")
async def stream_bulk_processing(
    request: BulkProcessRequest,
    db: Session = Depends(deps.get_db)
):
    """
    Stream bulk processing progress using Server-Sent Events.
    
    Provides real-time updates as each invoice is processed.
    """
    upload_ids = []
    batch_id = request.batch_id or str(uuid.uuid4())
    
    if request.upload_ids:
        upload_ids = request.upload_ids
        # Update all with batch_id
        for uid in upload_ids:
            upload = crud.upload.get(db, id=uid)
            if upload:
                crud.upload.update(db, db_obj=upload, obj_in={"batch_id": batch_id})
    elif request.batch_id:
        uploads = db.query(Upload).filter(Upload.batch_id == request.batch_id).all()
        upload_ids = [u.id for u in uploads]
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either upload_ids or batch_id"
        )
    
    if not upload_ids:
        raise HTTPException(
            status_code=404,
            detail="No invoices found to process"
        )
    
    return StreamingResponse(
        generate_processing_stream(upload_ids, batch_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/batches")
def list_batches(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 20
):
    """
    List all batch IDs with their status summary.
    """
    # Get distinct batch IDs
    batches = db.query(Upload.batch_id).filter(Upload.batch_id.isnot(None)).distinct().offset(skip).limit(limit).all()
    
    result = []
    for (batch_id,) in batches:
        uploads = db.query(Upload).filter(Upload.batch_id == batch_id).all()
        result.append({
            "batch_id": batch_id,
            "total_invoices": len(uploads),
            "approved": sum(1 for u in uploads if u.invoice_status == "APPROVED"),
            "rejected": sum(1 for u in uploads if u.invoice_status == "REJECTED"),
            "needs_review": sum(1 for u in uploads if u.invoice_status == "HUMAN_REVIEW_NEEDED"),
            "completed": sum(1 for u in uploads if u.batch_processing_status == "completed"),
            "pending": sum(1 for u in uploads if u.batch_processing_status in ("pending", None))
        })
    
    return result
