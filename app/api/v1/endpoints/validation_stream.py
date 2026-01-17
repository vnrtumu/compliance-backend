"""
Streaming Validation Endpoint

Provides real-time streaming of LLM validation progress using Server-Sent Events (SSE).
"""

import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from openai import OpenAI

from app.api import deps
from app.models.upload import Upload
from app.core.config import settings


router = APIRouter()


# Company and checklist context (same as validator.py)
COMPANY_CONTEXT = """Company GSTIN: 27AABCF9999K1ZX, State: Maharashtra (27)
Approval: <50K auto, 50K-2L Manager, 2L-5L Sr.Manager, 5L-20L Director, 20L-1Cr CFO
TDS: 194C=1-2%, 194J=2%(tech)/10%(prof), 194I=10%(rent on gross)
GST: Composition can't charge, Intra=CGST+SGST, Inter=IGST, E-invoice if >5Cr"""

CHECKS_SUMMARY = """45 Checks: DOC(7), GST(12), TDS(10), ARITH(5), POL(6), DQ(5)
Key: GSTIN format/status, TDS classification, Composition GST, 206AB, Related party, Approval level"""


async def generate_validation_stream(upload_id: int, extraction_result: dict):
    """Generate SSE stream for validation progress."""
    
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    extracted = extraction_result.get("extracted_fields", {})
    
    # Step 1: Initializing
    yield f"data: {json.dumps({'step': 'init', 'message': '🔍 Initializing Validator Agent...'})}\n\n"
    await asyncio.sleep(0.3)
    
    # Step 2: Loading checklist
    yield f"data: {json.dumps({'step': 'checklist', 'message': '📋 Loading 45-point validation checklist...'})}\n\n"
    await asyncio.sleep(0.3)
    
    # Step 3: Analyzing invoice
    invoice_num = extracted.get("invoice_number", "Unknown")
    seller = extracted.get("seller_gstin") or extracted.get("gstin") or "Unknown"
    yield f"data: {json.dumps({'step': 'analyze', 'message': f'📄 Analyzing Invoice: {invoice_num}'})}\n\n"
    await asyncio.sleep(0.2)
    
    yield f"data: {json.dumps({'step': 'vendor', 'message': f'🏢 Vendor GSTIN: {seller}'})}\n\n"
    await asyncio.sleep(0.2)
    
    # Step 4: Running checks
    yield f"data: {json.dumps({'step': 'gst', 'message': '🔎 Running GST compliance checks...'})}\n\n"
    await asyncio.sleep(0.3)
    
    yield f"data: {json.dumps({'step': 'tds', 'message': '💰 Analyzing TDS applicability...'})}\n\n"
    await asyncio.sleep(0.3)
    
    yield f"data: {json.dumps({'step': 'policy', 'message': '📜 Checking policy compliance...'})}\n\n"
    await asyncio.sleep(0.3)
    
    # Step 5: Call LLM
    yield f"data: {json.dumps({'step': 'llm', 'message': '🤖 GPT-4o analyzing all 45 checks...'})}\n\n"
    
    try:
        # Build compact prompt
        prompt = f"""Invoice: {json.dumps(extracted, default=str)}

{COMPANY_CONTEXT}
{CHECKS_SUMMARY}

Return JSON with: overall_decision (APPROVE/REJECT/REVIEW), compliance_score (0-100), summary, passed_count, 
failed_checks (array with code, name, reason, auto_reject, human_review),
warning_checks (array), human_intervention (required, approval_level, reasons), anomalies.
Only include failed/warning checks, not passed."""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a GST/TDS compliance validator. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2048
        )
        
        result_text = response.choices[0].message.content
        result = json.loads(result_text)
        
        # Parse result
        failed_checks = result.get("failed_checks", [])
        warning_checks = result.get("warning_checks", [])
        passed_count = result.get("passed_count", 45 - len(failed_checks) - len(warning_checks))
        
        # Stream individual check results
        for check in failed_checks:
            code = check.get('code', '')
            reason = check.get('reason', '')
            msg = {'step': 'check_failed', 'message': f'❌ {code}: {reason}'}
            yield f"data: {json.dumps(msg)}\n\n"
            await asyncio.sleep(0.2)
        
        for check in warning_checks:
            code = check.get('code', '')
            reason = check.get('reason', '')
            msg = {'step': 'check_warning', 'message': f'⚠️ {code}: {reason}'}
            yield f"data: {json.dumps(msg)}\n\n"
            await asyncio.sleep(0.2)
        
        # Build final result
        decision = result.get("overall_decision", "REVIEW")
        score = result.get("compliance_score", 0)
        human_intervention = result.get("human_intervention", {})
        
        # Determine overall status
        decision_map = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REVIEW": "REQUIRES_HUMAN_REVIEW"}
        overall_status = decision_map.get(decision, "REQUIRES_HUMAN_REVIEW")
        auto_reject = any(c.get("auto_reject", False) for c in failed_checks)
        
        # Final result
        final_result = {
            "upload_id": upload_id,
            "overall_status": overall_status,
            "compliance_score": score,
            "checks_passed": passed_count,
            "checks_failed": len(failed_checks),
            "checks_warned": len(warning_checks),
            "auto_reject": auto_reject,
            "validation_results": [
                {"check_code": c.get("code"), "check_name": c.get("name"), "status": "FAILED", 
                 "message": c.get("reason"), "auto_reject": c.get("auto_reject", False)}
                for c in failed_checks
            ] + [
                {"check_code": c.get("code"), "check_name": c.get("name"), "status": "WARNING",
                 "message": c.get("reason"), "requires_human_review": True}
                for c in warning_checks
            ],
            "human_intervention": {
                "required": human_intervention.get("required", len(failed_checks) > 0),
                "reasons": human_intervention.get("reasons", []),
                "approval_level_required": human_intervention.get("approval_level"),
                "failed_checks": failed_checks
            },
            "llm_reasoning": result.get("summary", ""),
            "detected_anomalies": result.get("anomalies", [])
        }
        
        # Complete message
        if decision == "APPROVE":
            yield f"data: {json.dumps({'step': 'complete', 'message': f'✅ Validation PASSED - Score: {score}%'})}\n\n"
        elif decision == "REJECT":
            yield f"data: {json.dumps({'step': 'complete', 'message': f'❌ Validation FAILED - Score: {score}%'})}\n\n"
        else:
            yield f"data: {json.dumps({'step': 'complete', 'message': f'⚠️ Human Review Required - Score: {score}%'})}\n\n"
        
        await asyncio.sleep(0.2)
        yield f"data: {json.dumps({'step': 'result', 'result': final_result})}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'step': 'error', 'message': f'Error: {str(e)}'})}\n\n"


@router.get("/{upload_id}/stream")
async def stream_validation(
    upload_id: int,
    db: Session = Depends(deps.get_db)
):
    """
    Stream validation progress using Server-Sent Events.
    
    Returns real-time updates as the LLM validates the invoice.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    if not upload.extraction_result:
        raise HTTPException(status_code=400, detail="Document not extracted yet")
    
    return StreamingResponse(
        generate_validation_stream(upload_id, upload.extraction_result),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
