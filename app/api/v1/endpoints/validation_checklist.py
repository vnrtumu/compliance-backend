"""
Validation Checklist API Endpoints

CRUD operations for the validation checklist.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.api import deps
from app.models.validation_checklist import ValidationChecklist

router = APIRouter()


class ValidationCheckSchema(BaseModel):
    id: int
    check_code: str
    check_name: str
    category: str
    subcategory: Optional[str]
    description: str
    complexity: str
    complexity_score: int
    weight: float
    is_automated: bool
    requires_api_call: bool
    auto_reject: bool
    requires_manual_review: bool
    is_active: bool
    
    class Config:
        from_attributes = True


class ValidationChecklistSummary(BaseModel):
    total_checks: int
    by_category: dict
    by_complexity: dict
    automated_count: int
    api_required_count: int
    auto_reject_count: int


@router.get("/", response_model=List[ValidationCheckSchema])
def get_all_checks(
    db: Session = Depends(deps.get_db),
    category: Optional[str] = None,
    complexity: Optional[str] = None,
    active_only: bool = True
):
    """
    Get all validation checks with optional filters.
    """
    query = db.query(ValidationChecklist)
    
    if active_only:
        query = query.filter(ValidationChecklist.is_active == True)
    if category:
        query = query.filter(ValidationChecklist.category == category.upper())
    if complexity:
        query = query.filter(ValidationChecklist.complexity == complexity.upper())
    
    return query.order_by(ValidationChecklist.check_code).all()


@router.get("/summary", response_model=ValidationChecklistSummary)
def get_checklist_summary(db: Session = Depends(deps.get_db)):
    """
    Get summary statistics of the validation checklist.
    """
    checks = db.query(ValidationChecklist).filter(ValidationChecklist.is_active == True).all()
    
    by_category = {}
    by_complexity = {}
    
    for check in checks:
        by_category[check.category] = by_category.get(check.category, 0) + 1
        by_complexity[check.complexity] = by_complexity.get(check.complexity, 0) + 1
    
    return {
        "total_checks": len(checks),
        "by_category": by_category,
        "by_complexity": by_complexity,
        "automated_count": sum(1 for c in checks if c.is_automated),
        "api_required_count": sum(1 for c in checks if c.requires_api_call),
        "auto_reject_count": sum(1 for c in checks if c.auto_reject)
    }


@router.get("/{check_code}", response_model=ValidationCheckSchema)
def get_check_by_code(check_code: str, db: Session = Depends(deps.get_db)):
    """
    Get a specific validation check by its code.
    """
    check = db.query(ValidationChecklist).filter(
        ValidationChecklist.check_code == check_code.upper()
    ).first()
    
    if not check:
        raise HTTPException(status_code=404, detail="Validation check not found")
    
    return check


@router.post("/seed")
def seed_checklist(db: Session = Depends(deps.get_db)):
    """
    Seed the validation checklist with initial data.
    Only works if table is empty.
    """
    existing = db.query(ValidationChecklist).count()
    if existing > 0:
        return {"message": f"Checklist already has {existing} entries. Skipping seed."}
    
    from app.data.validation_checklist_seed import get_seed_data
    
    seed_data = get_seed_data()
    for item in seed_data:
        check = ValidationChecklist(**item)
        db.add(check)
    
    db.commit()
    
    return {"message": f"Successfully seeded {len(seed_data)} validation checks"}
