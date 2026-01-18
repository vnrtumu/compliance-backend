import os
import shutil
import json
import asyncio
import threading
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.api import deps
from app.core.config import settings
from app.core.db import SessionLocal
from app.schemas.upload import UploadResult, Upload, UploadCreate
from app import crud

router = APIRouter()


def run_background_processing(upload_ids: List[int], batch_id: str):
    """
    Background task to process all invoices through 4 agents.
    Runs in a separate thread with its own database session.
    Processes in batches of 5 to avoid overloading.
    """
    import time
    from app.services.extractor import extractor_agent
    from app.services.validator import validator_agent
    from app.services.resolver import resolver_agent
    from app.services.reporter import reporter_agent
    from app.models.upload import Upload as UploadModel
    from datetime import datetime
    
    BATCH_SIZE = 5
    
    # Process in batches
    for batch_start in range(0, len(upload_ids), BATCH_SIZE):
        batch_ids = upload_ids[batch_start:batch_start + BATCH_SIZE]
        
        for upload_id in batch_ids:
            # Create new db session for each invoice
            db = SessionLocal()
            try:
                upload = db.query(UploadModel).filter(UploadModel.id == upload_id).first()
                if not upload:
                    continue
                
                # Track start time
                start_time = datetime.now()
                
                # Update status to processing
                upload.batch_processing_status = "processing"
                upload.processing_start_time = start_time
                db.commit()
                
                try:
                    # Step 1: Skip extraction if already done (JSON import)
                    if upload.extraction_status != "completed":
                        extraction_result = extractor_agent.analyze_document(upload.storage_path)
                        upload.extraction_status = "completed"
                        upload.extraction_result = extraction_result
                        upload.is_valid = extraction_result.get("is_valid_invoice", False)
                        db.commit()
                        db.refresh(upload)
                    
                    # Step 2: Validation
                    validation_result = validator_agent.validate_document(
                        upload_id=upload_id,
                        extraction_result=upload.extraction_result
                    )
                    upload.validation_result = validation_result
                    upload.compliance_score = validation_result.get("compliance_score")
                    upload.validation_status = validation_result.get("overall_status")
                    db.commit()
                    db.refresh(upload)
                    
                    # Step 3: Resolution
                    invoice = upload.extraction_result.get("extracted_fields", {})
                    resolver_result = resolver_agent.resolve(
                        invoice=invoice,
                        validation_result=validation_result,
                        batch_context=None,
                        historical_decisions=None
                    )
                    upload.resolver_result = resolver_result
                    db.commit()
                    db.refresh(upload)
                    
                    # Step 4: Reporting
                    report = reporter_agent.generate_report(
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
                    
                    # Calculate processing time
                    processing_time = (datetime.now() - start_time).total_seconds()
                    
                    # Update with final results
                    upload.reporter_result = report
                    upload.invoice_status = invoice_status
                    upload.processing_time = processing_time
                    upload.batch_processing_status = "completed"
                    db.commit()
                    
                    print(f"✅ Processed invoice #{upload_id}: {invoice_status}")
                    
                except Exception as e:
                    upload.batch_processing_status = "failed"
                    db.commit()
                    print(f"❌ Failed invoice #{upload_id}: {str(e)}")
                    
            finally:
                db.close()
        
        # Small delay between batches to be gentle on the API
        if batch_start + BATCH_SIZE < len(upload_ids):
            time.sleep(1)


def is_invoice_json(data) -> bool:
    """
    Check if JSON data contains invoice objects.
    Looks for common invoice fields.
    """
    invoice_fields = ['invoice_number', 'invoice_date', 'seller_gstin', 'buyer_gstin', 
                      'total_amount', 'gstin', 'amount', 'date', 'vendor']
    
    if isinstance(data, list) and len(data) > 0:
        # Check first item for invoice fields
        first = data[0] if isinstance(data[0], dict) else {}
        return any(field in first for field in invoice_fields)
    elif isinstance(data, dict):
        return any(field in data for field in invoice_fields)
    return False


def process_json_invoices(db: Session, json_data, source_filename: str, batch_id: str = None) -> List[dict]:
    """
    Process JSON invoice data and store each invoice as a separate upload with extraction_result.
    
    Args:
        db: Database session
        json_data: JSON data containing invoice(s)
        source_filename: Original filename
        batch_id: Optional batch ID to group invoices together
    """
    import uuid
    results = []
    
    # Generate batch_id if not provided
    if not batch_id:
        batch_id = str(uuid.uuid4())
    
    # Normalize to list
    invoices = json_data if isinstance(json_data, list) else [json_data]
    
    for idx, invoice in enumerate(invoices):
        # Extract vendor info (handle nested vendor object)
        vendor = invoice.get("vendor", {})
        if isinstance(vendor, dict):
            vendor_name = vendor.get("name")
            vendor_gstin = vendor.get("gstin")
            vendor_pan = vendor.get("pan")
            vendor_address = vendor.get("address")
        else:
            vendor_name = invoice.get("vendor_name")
            vendor_gstin = invoice.get("vendor_gstin") or invoice.get("seller_gstin")
            vendor_pan = invoice.get("vendor_pan") or invoice.get("seller_pan")
            vendor_address = invoice.get("vendor_address") or invoice.get("seller_address")
        
        # Extract buyer info (handle nested buyer object)
        buyer = invoice.get("buyer", {})
        if isinstance(buyer, dict):
            buyer_name = buyer.get("name")
            buyer_gstin = buyer.get("gstin")
            buyer_address = buyer.get("address")
        else:
            buyer_name = invoice.get("buyer_name")
            buyer_gstin = invoice.get("buyer_gstin")
            buyer_address = invoice.get("buyer_address")
        
        # Normalize JSON fields to match expected extraction format
        normalized_fields = {
            # Copy all original fields
            **invoice,
            # Add normalized vendor fields (ensure GSTIN is properly extracted)
            "seller_name": vendor_name,
            "seller_gstin": vendor_gstin,
            "seller_pan": vendor_pan,
            "seller_address": vendor_address,
            "vendor_name": vendor_name,
            "vendor_gstin": vendor_gstin,
            "vendor_pan": vendor_pan,
            "vendor_address": vendor_address,
            # Add normalized buyer fields
            "buyer_name": buyer_name,
            "buyer_gstin": buyer_gstin,
            "buyer_address": buyer_address,
            # Normalize amount fields
            "invoice_amount": invoice.get("total_amount"),
            "total": invoice.get("total_amount"),
        }
        
        # Create extraction result from JSON data
        extraction_result = {
            "is_valid_invoice": True,
            "decision": "ACCEPT",
            "document_type": "json_import",
            "confidence_score": 1.0,
            "rejection_reasons": [],
            "extracted_fields": normalized_fields,
            "source": "json_import"
        }
        
        # Determine filename
        invoice_num = invoice.get('invoice_number') or invoice.get('invoice_no') or f"invoice_{idx+1}"
        filename = f"{source_filename}_{invoice_num}"
        
        # Create upload record with pre-filled extraction and batch_id
        from app.models.upload import Upload as UploadModel
        db_obj = UploadModel(
            filename=filename,
            content_type="application/json",
            size=len(json.dumps(invoice)),
            storage_path=f"json_import:{source_filename}",
            extraction_status="completed",
            extraction_result=extraction_result,
            is_valid=True,
            batch_id=batch_id,
            batch_processing_status="pending"
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        results.append({
            "id": db_obj.id,
            "filename": filename,
            "invoice_number": invoice_num,
            "vendor_gstin": vendor_gstin,
            "status": "imported"
        })
    
    return results, batch_id


@router.get("/", response_model=List[Upload])
async def get_uploads(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100
):
    """
    Fetch upload history.
    """
    return crud.upload.get_multi(db, skip=skip, limit=limit)


@router.post("/", response_model=List[UploadResult])
async def upload_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(deps.get_db)
):
    results = []
    
    # Ensure upload directory exists
    if not os.path.exists(settings.UPLOAD_DIR):
        os.makedirs(settings.UPLOAD_DIR)
    
    import hashlib
    from app.models.upload import Upload as UploadModel
        
    for file in files:
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        
        try:
            # Read file content
            content = await file.read()
            
            # Compute SHA256 hash
            file_hash = hashlib.sha256(content).hexdigest()
            
            # Check if file already exists
            existing_upload = db.query(UploadModel).filter(UploadModel.file_hash == file_hash).first()
            if existing_upload:
                results.append(UploadResult(
                    filename=file.filename,  # Use uploaded filename in response
                    content_type=file.content_type,
                    size=len(content),
                    status="duplicate",  # Make it clear this is a duplicate
                    id=existing_upload.id,
                    error=f"File already exists as '{existing_upload.filename}' (ID: {existing_upload.id})"
                ))
                continue
            
            # Check if it's a JSON file with invoice data
            if file.content_type == "application/json" or file.filename.endswith('.json'):
                try:
                    json_data = json.loads(content.decode('utf-8'))
                    
                    if is_invoice_json(json_data):
                        # Process as direct invoice import - skip AI extraction
                        import_results, batch_id = process_json_invoices(db, json_data, file.filename)
                        
                        # Get all upload IDs for background processing
                        upload_ids = [r["id"] for r in import_results]
                        
                        # Start background processing in a separate thread
                        processing_thread = threading.Thread(
                            target=run_background_processing,
                            args=(upload_ids, batch_id),
                            daemon=True
                        )
                        processing_thread.start()
                        
                        # Add to results with special status and batch_id
                        results.append(UploadResult(
                            filename=file.filename,
                            content_type=file.content_type,
                            size=len(content),
                            status="json_imported_processing",
                            id=import_results[0]["id"] if import_results else None,
                            imported_count=len(import_results),
                            batch_id=batch_id
                        ))
                        continue
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # Not valid JSON, treat as regular file
            
            # Save file to disk for regular processing
            with open(file_path, "wb") as buffer:
                buffer.write(content)
            
            # Get file size
            file_size = len(content)
            
            # Save to Database
            db_obj = crud.upload.create(
                db, 
                obj_in=UploadCreate(
                    filename=file.filename,
                    content_type=file.content_type,
                    size=file_size,
                    storage_path=file_path,
                    file_hash=file_hash
                )
            )
            
            results.append(UploadResult(
                filename=file.filename,
                content_type=file.content_type,
                size=file_size,
                status="success",
                id=db_obj.id
            ))
        except Exception as e:
            results.append(UploadResult(
                filename=file.filename,
                content_type=file.content_type,
                size=0,
                status="error",
                error=str(e)
            ))
        finally:
            file.file.close()
            
    return results

