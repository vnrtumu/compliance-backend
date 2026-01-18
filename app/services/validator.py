"""
LLM-Based Validator Agent Service

Uses GPT-4o to perform intelligent compliance validation on extracted invoice data.
Validates against 45 checklist items with context-aware reasoning.
"""

import json
from openai import OpenAI
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from pydantic import BaseModel
from typing import Literal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.validation_checklist import ValidationChecklist


class ValidationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


class OverallStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


# Pydantic models for structured LLM output
class LLMValidationCheck(BaseModel):
    check_code: str
    check_name: str
    category: str
    status: Literal["PASSED", "FAILED", "WARNING", "SKIPPED"]
    reason: str
    confidence: float = 1.0
    requires_human_review: bool = False
    auto_reject: bool = False
    suggested_action: Optional[str] = None


class HumanInterventionInfo(BaseModel):
    required: bool = False
    reasons: List[str] = []
    failed_checks: List[Dict] = []
    approval_level_required: Optional[str] = None
    recommended_actions: List[str] = []


class LLMValidationResult(BaseModel):
    overall_decision: Literal["APPROVE", "REJECT", "REVIEW"]
    compliance_score: float
    checks: List[LLMValidationCheck]
    human_intervention: HumanInterventionInfo
    llm_reasoning: str
    detected_anomalies: List[str] = []


# Company policy context for LLM
COMPANY_CONTEXT = """
## Company Details
- Company GSTIN: 27AABCF9999K1ZX
- Company PAN: AABCF9999K
- State: Maharashtra (27)
- FY Turnover: ₹15 Crores

## Approval Matrix
- Level 1 (Auto-Approve): Up to ₹50,000 if compliance score ≥95%
- Level 2 (Manager): ₹50,001 - ₹2,00,000
- Level 3 (Senior Manager): ₹2,00,001 - ₹5,00,000
- Level 4 (Director): ₹5,00,001 - ₹20,00,000
- Level 5 (CFO): ₹20,00,001 - ₹1,00,00,000
- Level 6 (Board): Above ₹1 Crore

## Special Rules
- First-time vendors require Senior Manager approval + bank verification
- Related party PANs: AABCT1234F (same PAN different branches)
- Retrospective invoices (>60 days old) require Director approval
- MSME vendors must be paid within 45 days

## TDS Rules
- 194C (Contractors): 1% for individuals/HUF, 2% for others
- 194J (Professional): 10% for professional, 2% for technical/IT services
- 194I (Rent): 10% on land/building (on gross including GST)
- 206AB: Non-filers get 5% TDS (or twice normal rate)

## GST Rules  
- Composition dealers cannot charge GST
- Intra-state: CGST + SGST (equal amounts)
- Inter-state: IGST only
- E-invoice mandatory if seller turnover > ₹5 Crores
"""

VALIDATION_CHECKLIST = """
## Validation Checklist (45 Checks)

### DOCUMENT (7 checks)
- DOC-001: Invoice date not future, not older than 180 days
- DOC-002: Invoice number present and valid format
- DOC-003: Duplicate invoice detection (same vendor, number, amount in 365 days)
- DOC-004: Not a self-invoice (seller ≠ company GSTIN)
- DOC-005: Invoice amount > 0
- DOC-006: All mandatory fields present (GSTIN, invoice number, date, amount)
- DOC-007: FY cutoff compliance (March invoices until April 15)

### GST (12 checks)
- GST-001: GSTIN format valid (15 chars, pattern: ##XXXXX####X#ZX)
- GST-002: GSTIN status ACTIVE (not suspended/cancelled)
- GST-003: State code in GSTIN matches address
- GST-004: HSN/SAC code valid
- GST-005: GST rate correct for HSN/SAC and date (check historical rates)
- GST-006: Intra-state = CGST+SGST; Inter-state = IGST
- GST-007: Tax calculation accuracy (base × rate)
- GST-008: E-invoice required if seller turnover > 5Cr
- GST-009: IRN valid and active (if present)
- GST-010: Composition dealers cannot charge GST
- GST-011: RCM applicability for GTA, imports, etc.
- GST-012: Item-wise validation for mixed supplies

### TDS (10 checks)
- TDS-001: TDS applicability based on service type and threshold
- TDS-002: 194C rate correct (1% or 2%)
- TDS-003: 194J classification - CRITICAL: Technical services (IT, software) = 2%, Professional (legal, accounting) = 10%
- TDS-004: 194I rent rate correct (2% machinery, 10% building)
- TDS-005: TDS on GST for rent (base includes GST)
- TDS-006: 206AB non-filer check (higher TDS if applicable)
- TDS-007: Lower Deduction Certificate applied if available
- TDS-008: 194Q goods purchase TDS if >50L in FY
- TDS-009: Threshold limits respected (30K for 194J, etc.)
- TDS-010: PAN format valid and name match

### ARITHMETIC (5 checks)
- ARITH-001: Line items sum = subtotal
- ARITH-002: Tax calculation correct
- ARITH-003: Grand total = subtotal + taxes - discounts
- ARITH-004: CGST = SGST for intra-state
- ARITH-005: Within PO tolerance (±5% or ±₹1000)

### POLICY (6 checks)
- POL-001: Correct approval level for amount
- POL-002: First-time vendor extra verification
- POL-003: Related party transaction detection
- POL-004: MSME payment terms compliance
- POL-005: Budget availability in cost center
- POL-006: Retrospective invoice (>60 days) needs Director approval

### DATA QUALITY (5 checks)
- DQ-001: Vendor name matches GST portal name (fuzzy match >70%)
- DQ-002: Address completeness with PIN code
- DQ-003: Place of supply correctly determined
- DQ-004: Bank details verified
- DQ-005: Near-duplicate detection (>95% similar)
"""


class LLMValidatorAgent:
    """
    LLM-powered Validator Agent using GPT-4o for intelligent compliance validation.
    """
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o"
        self._validation_checks_cache = None
    
    def _get_validation_checks_from_db(self) -> List[Dict]:
        """Fetch active validation checks from database."""
        if self._validation_checks_cache is not None:
            return self._validation_checks_cache
        
        db = SessionLocal()
        try:
            checks = db.query(ValidationChecklist).filter(
                ValidationChecklist.is_active == True
            ).order_by(
                ValidationChecklist.category,
                ValidationChecklist.check_code
            ).all()
            
            self._validation_checks_cache = [
                {
                    "check_code": c.check_code,
                    "check_name": c.check_name,
                    "category": c.category,
                    "subcategory": c.subcategory,
                    "description": c.description,
                    "validation_logic": c.validation_logic,
                    "error_message": c.error_message,
                    "complexity": c.complexity,
                    "auto_reject": c.auto_reject,
                    "requires_manual_review": c.requires_manual_review,
                    "weight": c.weight
                }
                for c in checks
            ]
            return self._validation_checks_cache
        finally:
            db.close()
    
    def _format_validation_checklist(self) -> str:
        """Format validation checks from database into a readable checklist."""
        checks = self._get_validation_checks_from_db()
        
        # Group by category
        by_category = {}
        for check in checks:
            cat = check["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(check)
        
        # Build formatted checklist
        checklist = [f"## Validation Checklist ({len(checks)} Checks)\n"]
        
        for category, cat_checks in sorted(by_category.items()):
            checklist.append(f"\n### {category} ({len(cat_checks)} checks)")
            for check in cat_checks:
                line = f"- {check['check_code']}: {check['description']}"
                if check['auto_reject']:
                    line += " [AUTO-REJECT]"
                if check['requires_manual_review']:
                    line += " [MANUAL-REVIEW]"
                checklist.append(line)
        
        return "\n".join(checklist)
    
    def validate_document(
        self,
        upload_id: int,
        extraction_result: Dict[str, Any],
        vendor_info: Optional[Dict] = None
    ) -> Dict:
        """
        Run LLM-powered validation on extracted invoice data.
        
        Args:
            upload_id: Database ID of the upload
            extraction_result: Result from ExtractorAgent
            vendor_info: Optional vendor registry data
            
        Returns:
            Validation result with checks and human intervention info
        """
        extracted = extraction_result.get("extracted_fields", {})
        
        # Build the validation prompt
        prompt = self._build_validation_prompt(extracted, vendor_info)
        
        # Call GPT-4o for validation
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096
            )
            
            # Parse LLM response
            result = self._parse_llm_response(response.choices[0].message.content)
            result["upload_id"] = upload_id
            
            return result
            
        except Exception as e:
            # Fallback to error response
            return {
                "upload_id": upload_id,
                "overall_status": "REQUIRES_HUMAN_REVIEW",
                "compliance_score": 0,
                "checks_passed": 0,
                "checks_failed": 0,
                "checks_warned": 0,
                "auto_reject": False,
                "validation_results": [],
                "human_intervention": {
                    "required": True,
                    "reasons": [f"LLM validation failed: {str(e)}"],
                    "failed_checks": [],
                    "approval_level_required": None
                },
                "llm_reasoning": f"Error: {str(e)}",
                "detected_anomalies": []
            }
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the validator LLM."""
        return """You are an expert GST and TDS compliance validator for India. 
Your job is to analyze invoice data and validate it against a comprehensive 45-point checklist.

You must:
1. Check each validation point carefully
2. Consider edge cases and historical context (e.g., GST rate changes)
3. Classify services correctly for TDS (technical vs professional is CRITICAL)
4. Detect anomalies and suspicious patterns
5. Provide clear, actionable reasons for failures
6. Flag items requiring human review

IMPORTANT CLASSIFICATIONS:
- IT Services, Software Development, Technical Consulting = 194J @ 2% (TECHNICAL)
- Legal, Accounting, Medical, Architecture = 194J @ 10% (PROFESSIONAL)
- Contractors, Labor = 194C @ 1% (individual) or 2% (company)
- Rent = 194I @ 10% on GROSS amount including GST

Return your response as a JSON object with the exact structure specified."""
    
    def _build_validation_prompt(
        self, 
        extracted: Dict,
        vendor_info: Optional[Dict]
    ) -> str:
        """Build the validation prompt with invoice data and context."""
        
        # Get validation checklist from database
        validation_checklist = self._format_validation_checklist()
        
        prompt = f"""
## Invoice Data to Validate

```json
{json.dumps(extracted, indent=2, default=str)}
```

{COMPANY_CONTEXT}

{validation_checklist}

## Vendor Information
{json.dumps(vendor_info, indent=2, default=str) if vendor_info else "Not available - use GSTIN lookup logic"}

## Your Task

Analyze the invoice against the 45 validation checks. BE CONCISE.

Return a JSON object with this structure:
{{
  "overall_decision": "APPROVE" | "REJECT" | "REVIEW",
  "compliance_score": <0-100>,
  "summary": "<2-3 sentence summary>",
  "passed_count": <number of passed checks>,
  "failed_checks": [
    {{
      "code": "GST-001",
      "name": "GSTIN Format",
      "status": "FAILED",
      "reason": "<brief reason>",
      "auto_reject": true,
      "human_review": false
    }}
  ],
  "warning_checks": [
    {{
      "code": "POL-006",
      "name": "Retrospective Invoice",
      "status": "WARNING",
      "reason": "<brief reason>",
      "human_review": true
    }}
  ],
  "human_intervention": {{
    "required": true,
    "approval_level": "Director" | null,
    "reasons": ["<reason 1>", "<reason 2>"]
  }},
  "anomalies": ["<any suspicious patterns>"]
}}

IMPORTANT: Only include failed_checks and warning_checks arrays. Do NOT include passed checks.

Now validate and return JSON:"""
        
        return prompt
    
    def _parse_llm_response(self, response_text: str) -> Dict:
        """Parse and validate the LLM response."""
        try:
            result = json.loads(response_text)
            
            # Get failed and warning checks
            failed_checks = result.get("failed_checks", [])
            warning_checks = result.get("warning_checks", [])
            passed_count = result.get("passed_count", 45 - len(failed_checks) - len(warning_checks))
            
            # Combine all checks for validation_results
            all_checks = []
            for check in failed_checks:
                all_checks.append({
                    "check_code": check.get("code"),
                    "check_name": check.get("name"),
                    "category": check.get("code", "").split("-")[0] if check.get("code") else "UNKNOWN",
                    "status": "FAILED",
                    "message": check.get("reason"),
                    "requires_human_review": check.get("human_review", False),
                    "auto_reject": check.get("auto_reject", False)
                })
            
            for check in warning_checks:
                all_checks.append({
                    "check_code": check.get("code"),
                    "check_name": check.get("name"),
                    "category": check.get("code", "").split("-")[0] if check.get("code") else "UNKNOWN",
                    "status": "WARNING",
                    "message": check.get("reason"),
                    "requires_human_review": check.get("human_review", True),
                    "auto_reject": False
                })
            
            # Check for auto-reject
            auto_reject = any(c.get("auto_reject", False) for c in failed_checks)
            
            # Map overall decision to status
            decision_map = {
                "APPROVE": "APPROVED",
                "REJECT": "REJECTED", 
                "REVIEW": "REQUIRES_HUMAN_REVIEW"
            }
            
            # Build human intervention info
            human_intervention = result.get("human_intervention", {})
            
            return {
                "overall_status": decision_map.get(result.get("overall_decision"), "REQUIRES_HUMAN_REVIEW"),
                "compliance_score": result.get("compliance_score", 0),
                "checks_passed": passed_count,
                "checks_failed": len(failed_checks),
                "checks_warned": len(warning_checks),
                "checks_skipped": 0,
                "auto_reject": auto_reject,
                "validation_results": all_checks,
                "human_intervention": {
                    "required": human_intervention.get("required", len(failed_checks) > 0 or len(warning_checks) > 0),
                    "reasons": human_intervention.get("reasons", []),
                    "failed_checks": failed_checks,
                    "approval_level_required": human_intervention.get("approval_level")
                },
                "llm_reasoning": result.get("summary", ""),
                "detected_anomalies": result.get("anomalies", [])
            }
            
        except json.JSONDecodeError as e:
            return {
                "overall_status": "REQUIRES_HUMAN_REVIEW",
                "compliance_score": 0,
                "checks_passed": 0,
                "checks_failed": 0,
                "checks_warned": 0,
                "checks_skipped": 0,
                "auto_reject": False,
                "validation_results": [],
                "human_intervention": {
                    "required": True,
                    "reasons": [f"Failed to parse LLM response: {str(e)}"],
                    "failed_checks": [],
                    "approval_level_required": None
                },
                "llm_reasoning": response_text[:500],
                "detected_anomalies": []
            }


# Singleton instance
validator_agent = LLMValidatorAgent()
