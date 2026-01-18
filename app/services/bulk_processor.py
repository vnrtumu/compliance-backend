"""
Bulk Invoice Processing Service

Orchestrates concurrent processing of multiple invoices through all 4 agents.
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.upload import Upload
from app.services.extractor import extractor_agent
from app.services.validator import validator_agent
from app.services.resolver import resolver_agent
from app.services.reporter import reporter_agent
from app import crud


class BulkProcessor:
    """Handles bulk invoice processing operations."""
    
    def __init__(self, max_concurrent: int = 5):
        """
        Initialize bulk processor.
        
        Args:
            max_concurrent: Maximum number of concurrent LLM calls to prevent rate limiting
        """
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_single_invoice(self, upload_id: int, db: Session) -> Dict[str, Any]:
        """
        Process a single invoice through all 4 agents.
        
        Args:
            upload_id: The upload ID to process
            db: Database session
            
        Returns:
            Dict with processing results and status
        """
        async with self.semaphore:  # Limit concurrent LLM calls
            try:
                # Get upload record
                upload = crud.upload.get(db, id=upload_id)
                if not upload:
                    return {
                        "upload_id": upload_id,
                        "status": "error",
                        "error": "Upload not found"
                    }
                
                # Track start time locally to avoid timezone issues
                start_time = datetime.now()
                
                # Update status
                crud.upload.update(db, db_obj=upload, obj_in={
                    "batch_processing_status": "processing",
                    "processing_start_time": start_time
                })
                
                # Step 1: Extraction (skip if already done via JSON import)
                if upload.extraction_status != "completed":
                    extraction_result = await asyncio.to_thread(
                        extractor_agent.analyze_document,
                        upload.storage_path
                    )
                    crud.upload.update(db, db_obj=upload, obj_in={
                        "extraction_status": "completed",
                        "extraction_result": extraction_result,
                        "is_valid": extraction_result.get("is_valid_invoice", False)
                    })
                    # Refresh to get updated data
                    db.refresh(upload)
                
                    # Refresh to get updated data
                    db.refresh(upload)
                
                # Check if valid invoice before proceeding
                # Check both the DB flag AND the raw JSON result to be safe
                is_valid_db = upload.is_valid
                is_valid_json = upload.extraction_result.get("is_valid_invoice", True) if upload.extraction_result else False
                
                if (is_valid_db is False) or (is_valid_json is False):
                    # Auto-reject invalid documents
                    reasons = upload.extraction_result.get("rejection_reasons", ["Invalid Document"])
                    mock_report = {
                        "decision": {"status": "REJECT"},
                        "summary": f"Document rejected during extraction: {', '.join(reasons)}",
                        "validation_results": []
                    }
                    
                    crud.upload.update(db, db_obj=upload, obj_in={
                        "invoice_status": "REJECTED",
                        "batch_processing_status": "completed",
                        "processing_time": (datetime.now() - start_time).total_seconds(),
                        "reporter_result": mock_report
                    })
                    
                    return {
                        "upload_id": upload_id,
                        "status": "completed",
                        "invoice_status": "REJECTED",
                        "error": "Document rejected: Not a valid invoice"
                    }

                # Step 2: Validation
                validation_result = await asyncio.to_thread(
                    validator_agent.validate_document,
                    upload_id=upload_id,
                    extraction_result=upload.extraction_result
                )
                crud.upload.update(db, db_obj=upload, obj_in={
                    "validation_result": validation_result,
                    "compliance_score": validation_result.get("compliance_score"),
                    "validation_status": validation_result.get("overall_status")
                })
                db.refresh(upload)
                
                # Step 3: Resolution
                invoice = upload.extraction_result.get("extracted_fields", {})
                resolver_result = await asyncio.to_thread(
                    resolver_agent.resolve,
                    invoice=invoice,
                    validation_result=validation_result,
                    batch_context=None,
                    historical_decisions=None
                )
                crud.upload.update(db, db_obj=upload, obj_in={
                    "resolver_result": resolver_result
                })
                db.refresh(upload)
                
                # Step 4: Reporting
                report = await asyncio.to_thread(
                    reporter_agent.generate_report,
                    upload_id=upload_id,
                    extraction_result=upload.extraction_result,
                    validation_result=validation_result,
                    resolver_result=resolver_result,
                    report_type="executive_summary"
                )
                
                # Extract decision and set invoice status
                decision_status = report.get("decision", {}).get("status", "REVIEW")
                if decision_status == "APPROVE":
                    invoice_status = "APPROVED"
                elif decision_status == "REJECT":
                    invoice_status = "REJECTED"
                else:
                    invoice_status = "HUMAN_REVIEW_NEEDED"
                
                # Calculate processing time using local start_time
                processing_time = (datetime.now() - start_time).total_seconds()
                
                # Update with final results
                crud.upload.update(db, db_obj=upload, obj_in={
                    "reporter_result": report,
                    "invoice_status": invoice_status,
                    "processing_time": processing_time,
                    "batch_processing_status": "completed"
                })
                
                return {
                    "upload_id": upload_id,
                    "status": "completed",
                    "invoice_status": invoice_status,
                    "compliance_score": validation_result.get("compliance_score"),
                    "processing_time": processing_time
                }
                
            except Exception as e:
                # Mark as failed
                try:
                    upload = crud.upload.get(db, id=upload_id)
                    if upload:
                        crud.upload.update(db, db_obj=upload, obj_in={
                            "batch_processing_status": "failed"
                        })
                except:
                    pass
                
                return {
                    "upload_id": upload_id,
                    "status": "error",
                    "error": str(e)
                }
    
    async def process_batch(self, upload_ids: List[int], db: Session) -> Dict[str, Any]:
        """
        Process multiple invoices sequentially through all 4 agents.
        
        Note: Sequential processing to avoid SQLAlchemy session conflicts.
        Each invoice is fully processed before moving to the next.
        
        Args:
            upload_ids: List of upload IDs to process
            db: Database session
            
        Returns:
            Dict with batch results and statistics
        """
        batch_start = datetime.now()
        
        results = []
        
        # Process invoices sequentially to avoid DB session conflicts
        for upload_id in upload_ids:
            try:
                result = await self.process_single_invoice(upload_id, db)
                results.append(result)
            except Exception as e:
                results.append({
                    "upload_id": upload_id,
                    "status": "error",
                    "error": str(e)
                })
        
        # Calculate statistics
        completed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "completed")
        failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "error")
        
        # Count by invoice status
        approved = sum(1 for r in results if isinstance(r, dict) and r.get("invoice_status") == "APPROVED")
        rejected = sum(1 for r in results if isinstance(r, dict) and r.get("invoice_status") == "REJECTED")
        needs_review = sum(1 for r in results if isinstance(r, dict) and r.get("invoice_status") == "HUMAN_REVIEW_NEEDED")
        
        # Calculate average scores
        scores = [r.get("compliance_score", 0) for r in results if isinstance(r, dict) and r.get("compliance_score")]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        total_time = (datetime.now() - batch_start).total_seconds()
        
        return {
            "total_invoices": len(upload_ids),
            "completed": completed,
            "failed": failed,
            "approved": approved,
            "rejected": rejected,
            "needs_review": needs_review,
            "average_compliance_score": avg_score,
            "total_processing_time": total_time,
            "results": results
        }
    
    def generate_bulk_report(self, batch_id: str, db: Session) -> Dict[str, Any]:
        """
        Generate consolidated report for a batch of invoices.
        
        Args:
            batch_id: The batch ID to generate report for
            db: Database session
            
        Returns:
            Consolidated report with statistics and vendor breakdown
        """
        # Get all uploads in this batch
        uploads = db.query(Upload).filter(Upload.batch_id == batch_id).all()
        
        if not uploads:
            return {"error": "No uploads found for batch"}
        
        # Aggregate statistics
        total = len(uploads)
        completed = sum(1 for u in uploads if u.batch_processing_status == "completed")
        failed = sum(1 for u in uploads if u.batch_processing_status == "failed")
        
        approved = sum(1 for u in uploads if u.invoice_status == "APPROVED")
        rejected = sum(1 for u in uploads if u.invoice_status == "REJECTED")
        needs_review = sum(1 for u in uploads if u.invoice_status == "HUMAN_REVIEW_NEEDED")
        
        # Calculate average score
        scores = [u.compliance_score for u in uploads if u.compliance_score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Vendor-wise breakdown (group by GSTIN)
        vendor_breakdown = {}
        for upload in uploads:
            if upload.extraction_result:
                fields = upload.extraction_result.get("extracted_fields", {})
                vendor_gstin = fields.get("vendor_gstin") or fields.get("seller_gstin", "Unknown")
                vendor_name = fields.get("vendor_name") or fields.get("seller_name", "Unknown")
                
                if vendor_gstin not in vendor_breakdown:
                    vendor_breakdown[vendor_gstin] = {
                        "vendor_name": vendor_name,
                        "vendor_gstin": vendor_gstin,
                        "invoice_count": 0,
                        "approved": 0,
                        "rejected": 0,
                        "needs_review": 0,
                        "total_amount": 0
                    }
                
                vendor_breakdown[vendor_gstin]["invoice_count"] += 1
                if upload.invoice_status == "APPROVED":
                    vendor_breakdown[vendor_gstin]["approved"] += 1
                elif upload.invoice_status == "REJECTED":
                    vendor_breakdown[vendor_gstin]["rejected"] += 1
                elif upload.invoice_status == "HUMAN_REVIEW_NEEDED":
                    vendor_breakdown[vendor_gstin]["needs_review"] += 1
                
                # Add total amount (handle None values)
                total_amount = fields.get("total_amount") or fields.get("invoice_amount") or 0
                vendor_breakdown[vendor_gstin]["total_amount"] += total_amount
        
        # Identify common issues
        common_issues = {}
        for upload in uploads:
            if upload.validation_result:
                failed_checks = [
                    check for check in upload.validation_result.get("validation_results", [])
                    if check.get("status") == "FAIL"
                ]
                for check in failed_checks:
                    check_code = check.get("check_code", "unknown")
                    if check_code not in common_issues:
                        common_issues[check_code] = {
                            "check_code": check_code,
                            "description": check.get("check_description", ""),
                            "occurrence_count": 0
                        }
                    common_issues[check_code]["occurrence_count"] += 1
        
        # Sort by most common
        common_issues_list = sorted(
            common_issues.values(),
            key=lambda x: x["occurrence_count"],
            reverse=True
        )[:10]  # Top 10
        
        return {
            "batch_id": batch_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_invoices": total,
                "completed": completed,
                "failed": failed,
                "approved": approved,
                "rejected": rejected,
                "needs_review": needs_review,
                "average_compliance_score": avg_score
            },
            "vendor_breakdown": list(vendor_breakdown.values()),
            "common_issues": common_issues_list,
            "invoices": [
                {
                    "upload_id": u.id,
                    "invoice_number": u.extraction_result.get("extracted_fields", {}).get("invoice_number", "Unknown") if u.extraction_result else "Unknown",
                    "vendor_name": u.extraction_result.get("extracted_fields", {}).get("vendor_name", "Unknown") if u.extraction_result else "Unknown",
                    "status": u.invoice_status,
                    "compliance_score": u.compliance_score,
                    "processing_time": u.processing_time
                }
                for u in uploads
            ]
        }


# Singleton instance
bulk_processor = BulkProcessor(max_concurrent=5)
