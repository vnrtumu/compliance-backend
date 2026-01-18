"""
Reporter API Endpoint

Provides endpoints for report generation with streaming support.
"""

import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import datetime

from app.api import deps
from app.models.upload import Upload
from app.services.reporter import reporter_agent
from app.core.config import settings


router = APIRouter()


class ReportRequest(BaseModel):
    """Report generation request."""
    report_type: str = "executive_summary"  # executive_summary, detailed_audit, exception


class ReportResponse(BaseModel):
    """Report response."""
    upload_id: int
    report_id: str
    report_type: str
    generated_at: str
    executive_summary: str
    decision: Dict
    risk_assessment: Dict
    compliance_stats: Dict
    action_items: list
    key_findings: list
    recommendations: list


@router.post("/{upload_id}")
def generate_report(
    upload_id: int,
    request: ReportRequest = ReportRequest(),
    db: Session = Depends(deps.get_db)
):
    """
    Generate a compliance report for an invoice.
    
    Synthesizes outputs from Extractor, Validator, and Resolver
    to produce actionable reports.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if not upload.extraction_result:
        raise HTTPException(status_code=400, detail="Document not extracted yet")
    
    # Get validation and resolution results
    validation_result = upload.validation_result or {}
    resolver_result = upload.resolver_result
    
    # Generate report
    report = reporter_agent.generate_report(
        upload_id=upload_id,
        extraction_result=upload.extraction_result,
        validation_result=validation_result,
        resolver_result=resolver_result,
        report_type=request.report_type
    )
    
    # Store report in dedicated column
    from app import crud
    
    # Extract decision and set invoice status
    decision_status = report.get("decision", {}).get("status", "REVIEW")
    if decision_status == "APPROVE":
        invoice_status = "APPROVED"
    elif decision_status == "REJECT":
        invoice_status = "REJECTED"
    else:
        invoice_status = "HUMAN_REVIEW_NEEDED"
    
    # Calculate processing time if start time exists
    processing_time = None
    if upload.processing_start_time:
        processing_time = (datetime.now() - upload.processing_start_time).total_seconds()
    
    crud.upload.update(db, db_obj=upload, obj_in={
        "reporter_result": report,
        "invoice_status": invoice_status,
        "processing_time": processing_time
    })
    
    return report


async def generate_report_stream(upload_id: int, extraction_result: dict, validation_result: dict, resolver_result: dict, db: Session):
    """Generate SSE stream for report generation progress."""
    from openai import OpenAI
    from app import crud
    
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    # Step 1: Collecting data
    yield f"data: {json.dumps({'step': 'collect', 'message': '📥 Collecting invoice data...'})}\n\n"
    await asyncio.sleep(0.3)
    
    extracted = extraction_result.get("extracted_fields", {})
    invoice_num = extracted.get("invoice_number", "Unknown")
    vendor = extracted.get("vendor_name") or extracted.get("seller_name", "Unknown")
    
    yield f"data: {json.dumps({'step': 'invoice', 'message': f'📄 Invoice: {invoice_num}'})}\n\n"
    await asyncio.sleep(0.2)
    
    yield f"data: {json.dumps({'step': 'vendor', 'message': f'🏢 Vendor: {vendor}'})}\n\n"
    await asyncio.sleep(0.2)
    
    # Step 2: Analyzing validation
    yield f"data: {json.dumps({'step': 'validation', 'message': '🔍 Analyzing validation results...'})}\n\n"
    await asyncio.sleep(0.3)
    
    checks_passed = validation_result.get("checks_passed", 0)
    checks_failed = validation_result.get("checks_failed", 0)
    score = validation_result.get("compliance_score", 0)
    
    yield f"data: {json.dumps({'step': 'stats', 'message': f'📊 {checks_passed} passed, {checks_failed} failed, Score: {score}%'})}\n\n"
    await asyncio.sleep(0.2)
    
    # Step 3: Processing resolutions
    if resolver_result:
        yield f"data: {json.dumps({'step': 'resolver', 'message': '⚖️ Processing resolutions...'})}\n\n"
        await asyncio.sleep(0.3)
        
        resolutions = resolver_result.get("conflict_resolutions", [])
        if resolutions:
            yield f"data: {json.dumps({'step': 'resolutions', 'message': f'📋 {len(resolutions)} conflict resolutions found'})}\n\n"
        await asyncio.sleep(0.2)
    
    # Step 4: Generating report with LLM
    yield f"data: {json.dumps({'step': 'llm', 'message': '🤖 GPT-4o generating report...'})}\n\n"
    
    try:
        report = reporter_agent.generate_report(
            upload_id=upload_id,
            extraction_result=extraction_result,
            validation_result=validation_result,
            resolver_result=resolver_result,
            report_type="executive_summary"
        )
        
        await asyncio.sleep(0.3)
        
        # Stream key sections
        decision = report.get("decision", {})
        status = decision.get("status", "UNKNOWN")
        status_emoji = {"APPROVE": "✅", "REJECT": "❌", "REVIEW": "⚠️"}.get(status, "❓")
        
        yield f"data: {json.dumps({'step': 'decision', 'message': f'{status_emoji} Decision: {status}'})}\n\n"
        await asyncio.sleep(0.2)
        
        risk = report.get("risk_assessment", {})
        risk_level = risk.get("level", "UNKNOWN")
        yield f"data: {json.dumps({'step': 'risk', 'message': f'🎯 Risk Level: {risk_level}'})}\n\n"
        await asyncio.sleep(0.2)
        
        actions = report.get("action_items", [])
        if actions:
            yield f"data: {json.dumps({'step': 'actions', 'message': f'🚨 {len(actions)} action items generated'})}\n\n"
            await asyncio.sleep(0.2)
        
        yield f"data: {json.dumps({'step': 'complete', 'message': '✅ Report generated successfully!'})}\n\n"
        await asyncio.sleep(0.2)
        
        # Generate text version
        text_report = reporter_agent.generate_text_report(report)
        report["text_report"] = text_report
        
        # Save report to database and set invoice status
        upload = db.query(Upload).filter(Upload.id == upload_id).first()
        if upload:
            # Extract decision and set invoice status
            decision_status = report.get("decision", {}).get("status", "REVIEW")
            if decision_status == "APPROVE":
                invoice_status = "APPROVED"
            elif decision_status == "REJECT":
                invoice_status = "REJECTED"
            else:
                invoice_status = "HUMAN_REVIEW_NEEDED"
            
            # Calculate processing time if start time exists
            processing_time = None
            if upload.processing_start_time:
                processing_time = (datetime.now() - upload.processing_start_time).total_seconds()
            
            crud.upload.update(db, db_obj=upload, obj_in={
                "reporter_result": report,
                "invoice_status": invoice_status,
                "processing_time": processing_time
            })
            
            # Explicitly commit to ensure data is saved
            db.commit()
            db.refresh(upload)
        
        yield f"data: {json.dumps({'step': 'result', 'result': report})}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'step': 'error', 'message': f'❌ Error: {str(e)}'})}\n\n"


@router.get("/{upload_id}/stream")
async def stream_report(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Stream report generation progress using Server-Sent Events.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if not upload.extraction_result:
        raise HTTPException(status_code=400, detail="Document not extracted yet")
    
    validation_result = upload.validation_result or {}
    resolver_result = upload.resolver_result
    
    
    return StreamingResponse(
        generate_report_stream(upload_id, upload.extraction_result, validation_result, resolver_result, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/{upload_id}")
def get_report(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """Get existing report."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if upload.validation_result and upload.validation_result.get("report"):
        return upload.validation_result["report"]
    
    raise HTTPException(status_code=404, detail="No report found. Generate one first.")


@router.get("/{upload_id}/text")
def get_text_report(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """Get report as formatted text."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if upload.validation_result and upload.validation_result.get("report"):
        report = upload.validation_result["report"]
        text = reporter_agent.generate_text_report(report)
        return {"text_report": text}
    
    raise HTTPException(status_code=404, detail="No report found.")
