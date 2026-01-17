import os
import shutil
import json
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session
from app.api import deps
from app.core.config import settings
from app.schemas.upload import UploadResult, Upload, UploadCreate
from app import crud

router = APIRouter()


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


def process_json_invoices(db: Session, json_data, source_filename: str) -> List[dict]:
    """
    Process JSON invoice data and store each invoice as a separate upload with extraction_result.
    """
    results = []
    
    # Normalize to list
    invoices = json_data if isinstance(json_data, list) else [json_data]
    
    for idx, invoice in enumerate(invoices):
        # Create extraction result from JSON data
        extraction_result = {
            "is_valid_invoice": True,
            "decision": "ACCEPT",
            "document_type": "json_import",
            "confidence_score": 1.0,
            "rejection_reasons": [],
            "extracted_fields": invoice,
            "source": "json_import"
        }
        
        # Determine filename
        invoice_num = invoice.get('invoice_number') or invoice.get('invoice_no') or f"invoice_{idx+1}"
        filename = f"{source_filename}_{invoice_num}"
        
        # Create upload record with pre-filled extraction
        from app.models.upload import Upload as UploadModel
        db_obj = UploadModel(
            filename=filename,
            content_type="application/json",
            size=len(json.dumps(invoice)),
            storage_path=f"json_import:{source_filename}",
            extraction_status="completed",
            extraction_result=extraction_result,
            is_valid=True
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        results.append({
            "id": db_obj.id,
            "filename": filename,
            "invoice_number": invoice_num,
            "status": "imported"
        })
    
    return results


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
        
    for file in files:
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        
        try:
            # Read file content first to check if it's a JSON invoice array
            content = await file.read()
            
            # Check if it's a JSON file with invoice data
            if file.content_type == "application/json" or file.filename.endswith('.json'):
                try:
                    json_data = json.loads(content.decode('utf-8'))
                    
                    if is_invoice_json(json_data):
                        # Process as direct invoice import - skip AI extraction
                        import_results = process_json_invoices(db, json_data, file.filename)
                        
                        # Add to results with special status
                        results.append(UploadResult(
                            filename=file.filename,
                            content_type=file.content_type,
                            size=len(content),
                            status="json_imported",
                            id=import_results[0]["id"] if import_results else None,
                            imported_count=len(import_results)
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
                    storage_path=file_path
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

