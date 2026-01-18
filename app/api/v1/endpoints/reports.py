"""
Reports API Endpoints

Provides aggregated statistics and analytics for compliance reports.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict

from app.api import deps
from app.models.upload import Upload


router = APIRouter()


@router.get("/statistics")
def get_reports_statistics(db: Session = Depends(deps.get_db)) -> Dict[str, Any]:
    """
    Get aggregated compliance statistics for the reports dashboard.
    
    Returns:
        - Overview metrics (total invoices, compliance rates, scores)
        - Category breakdown by validation check types
        - Trend data for last 30 days
        - Critical alerts
    """
    
    # Get all uploads
    all_uploads = db.query(Upload).all()
    total_invoices = len(all_uploads)
    
    # Filter uploads with validation results
    validated_uploads = [u for u in all_uploads if u.validation_result]
    
    # Calculate overview metrics
    overview = calculate_overview_metrics(all_uploads, validated_uploads)
    
    # Calculate category breakdown
    category_breakdown = calculate_category_breakdown(validated_uploads)
    
    # Get trend data (last 30 days)
    trend_data = calculate_trend_data(db)
    
    # Generate alerts
    alerts = generate_alerts(validated_uploads)
    
    # Get recent invoices (last 10 with reports)
    recent_invoices = []
    for upload in sorted(all_uploads, key=lambda x: x.created_at or datetime.min, reverse=True)[:10]:
        recent_invoices.append({
            "id": upload.id,
            "filename": upload.filename,
            "invoice_status": upload.invoice_status,
            "compliance_score": upload.compliance_score,
            "created_at": upload.created_at.isoformat() if upload.created_at else None,
            "has_report": upload.reporter_result is not None
        })
    
    return {
        "overview": overview,
        "category_breakdown": category_breakdown,
        "trend_data": trend_data,
        "alerts": alerts,
        "recent_invoices": recent_invoices
    }


@router.get("/dashboard-stats")
def get_dashboard_statistics(db: Session = Depends(deps.get_db)) -> Dict[str, Any]:
    """
    Get key statistics for dashboard stat cards.
    
    Returns:
        - total_invoices: Total count of all uploads
        - approved: Count of approved invoices
        - rejected: Count of rejected invoices  
        - pending_review: Count of invoices requiring human review
        - compliance_rate: Percentage of approved invoices
    """
    
    # Get all uploads
    all_uploads = db.query(Upload).all()
    total_invoices = len(all_uploads)
    
    # Count by invoice_status (set by Reporter agent)
    approved = sum(1 for u in all_uploads if u.invoice_status == "APPROVED")
    rejected = sum(1 for u in all_uploads if u.invoice_status == "REJECTED")
    pending_review = sum(1 for u in all_uploads if u.invoice_status == "HUMAN_REVIEW_NEEDED")
    
    # Count active flags (invoices with failed checks)
    active_flags = 0
    for upload in all_uploads:
        if upload.validation_result:
            failed = upload.validation_result.get("checks_failed", 0)
            if failed > 0:
                active_flags += 1
    
    # Calculate compliance rate
    validated_count = approved + rejected + pending_review
    compliance_rate = round((approved / validated_count) * 100, 1) if validated_count > 0 else 0.0
    
    return {
        "total_invoices": total_invoices,
        "approved": approved,
        "rejected": rejected,
        "pending_review": pending_review,
        "active_flags": active_flags,
        "compliance_rate": compliance_rate
    }


def calculate_overview_metrics(all_uploads: List[Upload], validated_uploads: List[Upload]) -> Dict[str, Any]:
    """Calculate overall compliance metrics."""
    
    total = len(all_uploads)
    if total == 0:
        return {
            "total_invoices": 0,
            "gst_compliance_rate": 0.0,
            "tds_accuracy": 0.0,
            "avg_validation_score": 0.0,
            "regulatory_flags": 0,
            "trend_7d": "0%"
        }
    
    # GST Compliance: invoices with passing GST checks
    gst_compliant = 0
    tds_compliant = 0
    total_score = 0.0
    regulatory_flags = 0
    
    for upload in validated_uploads:
        val_result = upload.validation_result
        if not val_result:
            continue
            
        # Check GST compliance (B-* checks)
        validation_results = val_result.get("validation_results", [])
        gst_checks = [v for v in validation_results if v.get("check_code", "").startswith("B-")]
        gst_passed = all(v.get("status") == "PASS" for v in gst_checks) if gst_checks else True
        if gst_passed:
            gst_compliant += 1
            
        # Check TDS compliance (D-* checks)
        tds_checks = [v for v in validation_results if v.get("check_code", "").startswith("D-")]
        tds_passed = all(v.get("status") == "PASS" for v in tds_checks) if tds_checks else True
        if tds_passed:
            tds_compliant += 1
        
        # Add compliance score
        if upload.compliance_score:
            total_score += upload.compliance_score
            
        # Count regulatory flags (failed checks)
        failed_checks = val_result.get("checks_failed", 0)
        if failed_checks > 0 or upload.validation_status == "REJECTED":
            regulatory_flags += 1
    
    validated_count = len(validated_uploads) if validated_uploads else 1
    
    return {
        "total_invoices": total,
        "gst_compliance_rate": round((gst_compliant / validated_count) * 100, 1) if validated_count > 0 else 0.0,
        "tds_accuracy": round((tds_compliant / validated_count) * 100, 1) if validated_count > 0 else 0.0,
        "avg_validation_score": round(total_score / validated_count, 1) if validated_count > 0 else 0.0,
        "regulatory_flags": regulatory_flags,
        "trend_7d": "+0%"  # TODO: Calculate actual trend
    }


def calculate_category_breakdown(validated_uploads: List[Upload]) -> Dict[str, Dict[str, float]]:
    """Calculate average scores by validation category."""
    
    # Category definitions (based on check code prefixes)
    categories = {
        "A": {"name": "document_authenticity", "max_points": 8},
        "B": {"name": "gst_compliance", "max_points": 18},
        "C": {"name": "arithmetic_extraction", "max_points": 10},
        "D": {"name": "tds_compliance", "max_points": 12},
        "E": {"name": "policy_rules", "max_points": 10}
    }
    
    # Aggregate scores per category
    category_scores = defaultdict(list)
    
    for upload in validated_uploads:
        val_result = upload.validation_result
        if not val_result:
            continue
            
        validation_results = val_result.get("validation_results", [])
        
        # Group by category prefix
        has_categorized_checks = False
        for category_prefix, category_info in categories.items():
            category_checks = [v for v in validation_results if v.get("check_code", "").startswith(f"{category_prefix}-")]
            
            if category_checks:
                has_categorized_checks = True
                # Calculate pass rate for this category
                passed = sum(1 for v in category_checks if v.get("status") == "PASS")
                total_checks = len(category_checks)
                pass_rate = (passed / total_checks) if total_checks > 0 else 0
                
                # Convert to points
                score = pass_rate * category_info["max_points"]
                category_scores[category_info["name"]].append(score)
        
        # If no categorized checks, derive from overall compliance_score
        if not has_categorized_checks and upload.compliance_score:
            # Distribute the score proportionally across categories
            total_max = sum(c["max_points"] for c in categories.values())
            score_ratio = upload.compliance_score / 100.0  # Normalize to 0-1
            
            for category_info in categories.values():
                category_score = score_ratio * category_info["max_points"]
                category_scores[category_info["name"]].append(category_score)
    
    # Calculate averages
    breakdown = {}
    for category_prefix, category_info in categories.items():
        category_name = category_info["name"]
        scores = category_scores.get(category_name, [])
        
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        
        breakdown[category_name] = {
            "score": avg_score,
            "max": category_info["max_points"]
        }
    
    return breakdown


def calculate_trend_data(db: Session) -> List[Dict[str, Any]]:
    """Get compliance score trends for last 30 days."""
    
    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    # Query uploads grouped by date
    results = db.query(
        func.date(Upload.created_at).label('date'),
        func.avg(Upload.compliance_score).label('avg_score'),
        func.count(Upload.id).label('count')
    ).filter(
        Upload.created_at >= thirty_days_ago,
        Upload.compliance_score.isnot(None)
    ).group_by(
        func.date(Upload.created_at)
    ).order_by(
        func.date(Upload.created_at)
    ).all()
    
    trend_data = []
    for row in results:
        trend_data.append({
            "date": row.date.isoformat() if row.date else None,
            "score": round(row.avg_score, 1) if row.avg_score else 0,
            "count": row.count
        })
    
    return trend_data


def generate_alerts(validated_uploads: List[Upload]) -> List[Dict[str, Any]]:
    """Generate critical compliance alerts based on recent validations."""
    
    alerts = []
    
    # Count common failure types
    gst_state_errors = 0
    tds_errors = 0
    missing_fields = 0
    
    for upload in validated_uploads[-20:]:  # Last 20 uploads
        val_result = upload.validation_result
        if not val_result:
            continue
            
        validation_results = val_result.get("validation_results", [])
        
        for check in validation_results:
            if check.get("status") != "PASS":
                check_code = check.get("check_code", "")
                message = check.get("message", "")
                
                if "state" in message.lower() or "B-07" in check_code:
                    gst_state_errors += 1
                elif check_code.startswith("D-"):
                    tds_errors += 1
                elif "missing" in message.lower():
                    missing_fields += 1
    
    # Generate alerts
    if gst_state_errors > 0:
        alerts.append({
            "type": "error",
            "icon": "⚠️",
            "message": f"{gst_state_errors} invoices have GST state code mismatches requiring immediate review",
            "count": gst_state_errors
        })
    
    if tds_errors > 0:
        alerts.append({
            "type": "warning",
            "icon": "ℹ️",
            "message": f"{tds_errors} invoices have TDS deduction rate discrepancies",
            "count": tds_errors
        })
    
    if missing_fields > 0:
        alerts.append({
            "type": "warning",
            "icon": "📋",
            "message": f"{missing_fields} invoices have missing required fields",
            "count": missing_fields
        })
    
    # Default alert if no data
    if not alerts:
        alerts.append({
            "type": "info",
            "icon": "✅",
            "message": "All recent invoices are compliant. No critical alerts at this time.",
            "count": 0
        })
    
    return alerts
