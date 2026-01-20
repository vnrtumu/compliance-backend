"""
LLM-Based Resolver Agent Service (LangChain Version)

Handles conflicts, ambiguities, and edge cases flagged by the Validator Agent.
Provides reasoning, confidence scores, and human review recommendations.
Uses LangChain for LLM abstraction.
"""

import json
import re
from typing import Dict, List, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings
from app.services.llm_client import get_vision_model


class Conflict(BaseModel):
    """Represents a detected conflict or ambiguity."""
    conflict_type: str
    description: str
    gst_interpretation: Optional[str] = None
    tds_interpretation: Optional[str] = None
    affected_fields: List[str] = Field(default_factory=list)


class Resolution(BaseModel):
    """Resolution for a conflict."""
    conflict_type: str
    chosen_interpretation: str
    reasoning: str
    confidence: float
    regulatory_basis: str


class OCRCorrection(BaseModel):
    """OCR error correction."""
    field: str
    original: str
    corrected: str
    correction_type: str
    confidence: float


class HistoricalDeviation(BaseModel):
    """Deviation from historical decision."""
    historical_decision: str
    current_decision: str
    reason_for_deviation: str
    regulatory_basis: str


# Pydantic model for LLM resolution output
class ResolverOutput(BaseModel):
    """Structured output from resolver LLM."""
    final_recommendation: str = Field(description="APPROVE, REJECT, or ESCALATE")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence in recommendation")
    requires_human_review: bool = Field(description="Whether human review is required")
    reasoning: str = Field(description="Detailed reasoning for the decision")
    conflict_resolutions: List[Dict] = Field(default_factory=list)
    ocr_summary: str = Field(default="")
    temporal_summary: str = Field(default="")
    historical_deviation_note: str = Field(default="")
    key_risks: List[str] = Field(default_factory=list)


# GST Rate History (key dates)
GST_RATE_HISTORY = {
    "9954": {  # Construction
        "2017-07-01": 18,
        "2019-04-01": 12,  # Affordable housing
    },
    "9983": {  # Other professional services
        "2017-07-01": 18,
    },
    "998314": {  # IT Services
        "2017-07-01": 18,
    }
}

# Known conflict patterns
CONFLICT_PATTERNS = {
    "rent_tds_gst": {
        "description": "TDS on rent should be calculated on gross amount including GST",
        "regulation": "Section 194I, CBDT Circular 23/2017"
    },
    "it_services_classification": {
        "description": "IT services may be technical (2%) or professional (10%) under 194J",
        "regulation": "Section 194J, Finance Act 2020"
    },
    "composition_gst": {
        "description": "Composition dealers cannot charge GST on invoices",
        "regulation": "Section 10 CGST Act"
    },
    "206ab_vs_ldc": {
        "description": "Lower Deduction Certificate overrides 206AB higher rate",
        "regulation": "Section 197, clarified by CBDT"
    },
    "gta_rcm": {
        "description": "GTA services may be under RCM or forward charge based on option",
        "regulation": "Notification 13/2017-CT(Rate)"
    }
}

# System prompt for resolver
RESOLVER_SYSTEM_PROMPT = """You are an expert GST/TDS compliance resolver. 
Your job is to analyze conflicts, OCR errors, temporal rules, and historical precedents 
to make final compliance recommendations.

Key responsibilities:
1. Resolve regulatory conflicts (GST vs TDS, 206AB vs LDC, etc.)
2. Validate OCR corrections and flag suspicious changes
3. Apply rules based on invoice date, not processing date
4. Flag suspicious historical precedents
5. Provide clear reasoning with regulatory citations

Return only valid JSON with your analysis and recommendations."""


class ResolverAgent:
    """
    LangChain-powered Resolver Agent for handling conflicts and edge cases.
    
    Capabilities:
    - Detect and resolve regulatory conflicts (GST vs TDS)
    - Fix OCR errors (O↔0, I↔1, truncated GSTINs)
    - Apply temporal rules based on invoice date
    - Perform stateful validation across batch
    - Analyze historical decisions (flag 15% incorrect ones)
    """
    
    def __init__(self):
        # Use GPT-4o for resolver (complex reasoning required)
        self.model = get_vision_model(temperature=0.1, max_tokens=2048)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", RESOLVER_SYSTEM_PROMPT),
            ("human", "{resolution_context}")
        ])
    
    def resolve(
        self,
        invoice: Dict,
        validation_result: Dict,
        batch_context: Optional[Dict] = None,
        historical_decisions: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Main resolution method - handles all conflicts and edge cases.
        
        Args:
            invoice: Extracted invoice data
            validation_result: Result from Validator Agent
            batch_context: Context for stateful validation (aggregate TDS, etc.)
            historical_decisions: Past decisions for comparison
            
        Returns:
            Resolution result with recommendations and confidence
        """
        # Step 1: Fix OCR errors first
        ocr_corrections = self._fix_ocr_errors(invoice)
        corrected_invoice = self._apply_corrections(invoice, ocr_corrections)
        
        # Step 2: Detect conflicts
        conflicts = self._detect_conflicts(corrected_invoice, validation_result)
        
        # Step 3: Apply temporal rules
        temporal_adjustments = self._apply_temporal_rules(corrected_invoice)
        
        # Step 4: Stateful validation
        stateful_issues = self._check_stateful(corrected_invoice, batch_context)
        
        # Step 5: Analyze against historical (detect bad precedents)
        historical_analysis = self._analyze_historical(
            corrected_invoice, 
            validation_result,
            historical_decisions
        )
        
        # Step 6: Call LLM to resolve conflicts and make final recommendation
        resolution = self._llm_resolve(
            corrected_invoice,
            validation_result,
            conflicts,
            ocr_corrections,
            temporal_adjustments,
            stateful_issues,
            historical_analysis
        )
        
        return resolution
    
    def _fix_ocr_errors(self, invoice: Dict) -> List[Dict]:
        """Detect and fix common OCR errors."""
        corrections = []
        
        gstin = invoice.get("seller_gstin") or invoice.get("gstin") or ""
        pan = (gstin[2:12] if len(gstin) >= 12 else "") or invoice.get("pan", "")
        
        # Check GSTIN format and try corrections
        gstin_pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$'
        
        if gstin and not re.match(gstin_pattern, gstin.upper()):
            # Try O → 0 and I → 1 replacements
            corrected_gstin = gstin.upper()
            
            # Common OCR errors
            ocr_swaps = [
                ("O", "0"), ("0", "O"),
                ("I", "1"), ("1", "I"),
                ("S", "5"), ("5", "S"),
                ("B", "8"), ("8", "B"),
                ("Z", "2"), ("2", "Z"),
            ]
            
            for old, new in ocr_swaps:
                test_gstin = corrected_gstin.replace(old, new)
                if re.match(gstin_pattern, test_gstin):
                    corrections.append({
                        "field": "seller_gstin",
                        "original": gstin,
                        "corrected": test_gstin,
                        "correction_type": f"OCR swap {old}→{new}",
                        "confidence": 0.85
                    })
                    break
        
        # Check for truncated GSTIN
        if gstin and 10 <= len(gstin) < 15:
            corrections.append({
                "field": "seller_gstin",
                "original": gstin,
                "corrected": None,  # Need lookup
                "correction_type": "truncated_gstin",
                "confidence": 0.5,
                "note": "GSTIN appears truncated, needs vendor registry lookup"
            })
        
        # Check PAN format
        pan_pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
        if pan and not re.match(pan_pattern, pan.upper()):
            for old, new in [("O", "0"), ("I", "1"), ("0", "O"), ("1", "I")]:
                test_pan = pan.upper().replace(old, new)
                if re.match(pan_pattern, test_pan):
                    corrections.append({
                        "field": "pan",
                        "original": pan,
                        "corrected": test_pan,
                        "correction_type": f"OCR swap {old}→{new}",
                        "confidence": 0.85
                    })
                    break
        
        # Check for missing decimal in amounts
        total = invoice.get("total_amount") or invoice.get("grand_total")
        taxable = invoice.get("taxable_value") or invoice.get("subtotal")
        
        if total and taxable:
            try:
                total_val = float(str(total).replace(",", ""))
                taxable_val = float(str(taxable).replace(",", ""))
                
                # If total is 100x taxable, likely missing decimal
                if total_val > taxable_val * 50 and total_val < taxable_val * 200:
                    corrections.append({
                        "field": "total_amount",
                        "original": total,
                        "corrected": total_val / 100,
                        "correction_type": "missing_decimal",
                        "confidence": 0.7
                    })
            except:
                pass
        
        return corrections
    
    def _apply_corrections(self, invoice: Dict, corrections: List[Dict]) -> Dict:
        """Apply OCR corrections to invoice data."""
        corrected = invoice.copy()
        
        for correction in corrections:
            if correction.get("corrected") and correction.get("confidence", 0) >= 0.8:
                field = correction["field"]
                if field in corrected:
                    corrected[field] = correction["corrected"]
                elif field == "seller_gstin" and "gstin" in corrected:
                    corrected["gstin"] = correction["corrected"]
        
        return corrected
    
    def _detect_conflicts(self, invoice: Dict, validation_result: Dict) -> List[Dict]:
        """Detect conflicts between GST and TDS rules."""
        conflicts = []
        
        vendor_type = invoice.get("vendor_type", "").lower()
        service_desc = invoice.get("description", "").lower()
        
        # Conflict 1: Rent TDS base
        if "rent" in vendor_type or "194i" in str(invoice.get("tds_section", "")).lower():
            gst_amount = (
                float(invoice.get("cgst_amount", 0) or 0) +
                float(invoice.get("sgst_amount", 0) or 0) +
                float(invoice.get("igst_amount", 0) or 0)
            )
            if gst_amount > 0:
                conflicts.append({
                    "conflict_type": "rent_tds_gst",
                    "description": "Rent invoice with GST - TDS base should include GST amount",
                    "gst_interpretation": f"GST of ₹{gst_amount} charged",
                    "tds_interpretation": "TDS @ 10% on gross amount including GST",
                    "affected_fields": ["tds_amount", "taxable_value"],
                    "regulation": CONFLICT_PATTERNS["rent_tds_gst"]["regulation"]
                })
        
        # Conflict 2: IT Services classification
        it_keywords = ["software", "it ", "tech", "development", "programming", "coding"]
        prof_keywords = ["legal", "accounting", "medical", "architect", "consult"]
        
        has_it = any(kw in service_desc for kw in it_keywords)
        has_prof = any(kw in service_desc for kw in prof_keywords)
        
        if has_it and has_prof:
            conflicts.append({
                "conflict_type": "it_services_classification",
                "description": "Invoice has both IT and professional services - different TDS rates apply",
                "gst_interpretation": "Single GST rate applies to combined service",
                "tds_interpretation": "IT services @ 2%, Professional @ 10% - need to split",
                "affected_fields": ["tds_rate", "tds_amount"],
                "regulation": CONFLICT_PATTERNS["it_services_classification"]["regulation"]
            })
        
        # Conflict 3: 206AB vs Lower Deduction Certificate
        failed_checks = validation_result.get("validation_results", [])
        has_206ab = any("206AB" in str(c.get("check_code", "")) for c in failed_checks)
        has_ldc = invoice.get("lower_deduction_cert") is not None
        
        if has_206ab and has_ldc:
            conflicts.append({
                "conflict_type": "206ab_vs_ldc",
                "description": "Vendor is 206AB non-filer but has Lower Deduction Certificate",
                "gst_interpretation": "N/A",
                "tds_interpretation": "LDC rate should override 206AB higher rate",
                "affected_fields": ["tds_rate"],
                "regulation": CONFLICT_PATTERNS["206ab_vs_ldc"]["regulation"]
            })
        
        return conflicts
    
    def _apply_temporal_rules(self, invoice: Dict) -> Dict:
        """Apply rules based on invoice date, not processing date."""
        adjustments = {}
        
        invoice_date_str = invoice.get("invoice_date")
        if not invoice_date_str:
            return {"error": "No invoice date available"}
        
        try:
            # Parse date
            for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
                try:
                    invoice_date = datetime.strptime(invoice_date_str, fmt)
                    break
                except:
                    continue
            else:
                return {"error": f"Could not parse date: {invoice_date_str}"}
            
            adjustments["invoice_date"] = invoice_date.isoformat()
            adjustments["rules_applied_for"] = invoice_date.strftime("%Y-%m-%d")
            
            # Check for FY transition (March-April boundary)
            if invoice_date.month == 3 and invoice_date.day >= 25:
                adjustments["fy_transition_warning"] = "Invoice near FY cutoff - verify correct FY booking"
            
            if invoice_date.month == 4 and invoice_date.day <= 15:
                adjustments["fy_transition_warning"] = "April invoice - check if relates to previous FY"
            
            # Check GST rate changes
            hsn = invoice.get("hsn_code") or invoice.get("sac_code")
            if hsn and hsn in GST_RATE_HISTORY:
                rates = GST_RATE_HISTORY[hsn]
                applicable_rate = None
                
                for effective_date, rate in sorted(rates.items(), reverse=True):
                    if invoice_date >= datetime.strptime(effective_date, "%Y-%m-%d"):
                        applicable_rate = rate
                        break
                
                if applicable_rate:
                    adjustments["temporal_gst_rate"] = {
                        "hsn": hsn,
                        "applicable_rate": applicable_rate,
                        "as_of_date": invoice_date.strftime("%Y-%m-%d")
                    }
            
            # TDS rate changes (Finance Act 2020 - IT services 2% from April 2020)
            if invoice_date >= datetime(2020, 4, 1):
                adjustments["tds_194j_it_rate"] = 2  # Technical services @ 2%
            else:
                adjustments["tds_194j_it_rate"] = 10  # Pre-2020 all 194J @ 10%
            
        except Exception as e:
            adjustments["error"] = str(e)
        
        return adjustments
    
    def _check_stateful(self, invoice: Dict, batch_context: Optional[Dict]) -> Dict:
        """Perform stateful validation across batch."""
        issues = {}
        
        if not batch_context:
            return {"note": "No batch context provided for stateful validation"}
        
        vendor_pan = invoice.get("pan") or ""
        if len(invoice.get("seller_gstin", "")) >= 12:
            vendor_pan = invoice["seller_gstin"][2:12]
        
        # Aggregate TDS threshold check
        vendor_ytd = batch_context.get("vendor_payments", {}).get(vendor_pan, 0)
        current_amount = float(invoice.get("total_amount", 0) or 0)
        
        # 194J threshold is ₹30,000
        if vendor_ytd < 30000 and (vendor_ytd + current_amount) >= 30000:
            issues["threshold_crossed"] = {
                "type": "194J",
                "previous_ytd": vendor_ytd,
                "current_invoice": current_amount,
                "new_ytd": vendor_ytd + current_amount,
                "action": "TDS now applicable as threshold crossed"
            }
        
        # Duplicate detection
        invoice_key = f"{vendor_pan}_{invoice.get('invoice_number')}_{invoice.get('total_amount')}"
        if invoice_key in batch_context.get("processed_invoices", set()):
            issues["duplicate_detected"] = {
                "key": invoice_key,
                "action": "Possible duplicate - verify before processing"
            }
        
        # Sequential invoice number check
        vendor_invoices = batch_context.get("vendor_invoice_numbers", {}).get(vendor_pan, [])
        current_num = invoice.get("invoice_number", "")
        if vendor_invoices and current_num:
            # Check if current number fits sequence
            issues["sequence_check"] = {
                "vendor": vendor_pan,
                "recent_invoices": vendor_invoices[-5:],
                "current": current_num
            }
        
        return issues
    
    def _analyze_historical(
        self, 
        invoice: Dict, 
        validation_result: Dict,
        historical_decisions: Optional[List[Dict]]
    ) -> Dict:
        """Analyze against historical decisions - detect bad precedents."""
        analysis = {
            "historical_match_found": False,
            "deviations": [],
            "suspicious_precedents": []
        }
        
        if not historical_decisions:
            return analysis
        
        # Find similar historical cases
        vendor_gstin = invoice.get("seller_gstin") or invoice.get("gstin")
        
        for hist in historical_decisions:
            if hist.get("gstin") == vendor_gstin or hist.get("vendor_id") == invoice.get("vendor_id"):
                analysis["historical_match_found"] = True
                
                hist_decision = hist.get("decision", "")
                hist_reason = hist.get("reason", "")
                
                # Current decision
                current_status = validation_result.get("overall_status", "")
                
                # Check for suspicious patterns (the 15% incorrect ones)
                suspicious_patterns = [
                    "approved despite GST mismatch",
                    "rejected for valid reason",
                    "manual override without justification",
                    "threshold ignored",
                    "composition dealer charged GST"
                ]
                
                for pattern in suspicious_patterns:
                    if pattern.lower() in hist_reason.lower():
                        analysis["suspicious_precedents"].append({
                            "historical_decision": hist_decision,
                            "historical_reason": hist_reason,
                            "flag": f"Suspicious pattern: {pattern}",
                            "recommendation": "Validate against regulations, not this precedent"
                        })
                
                # Note deviations
                if hist_decision.upper() != current_status.upper():
                    analysis["deviations"].append({
                        "historical_decision": hist_decision,
                        "current_decision": current_status,
                        "note": "Decision differs from historical precedent"
                    })
        
        return analysis
    
    def _llm_resolve(
        self,
        invoice: Dict,
        validation_result: Dict,
        conflicts: List[Dict],
        ocr_corrections: List[Dict],
        temporal_adjustments: Dict,
        stateful_issues: Dict,
        historical_analysis: Dict
    ) -> Dict:
        """Use LangChain LLM to resolve conflicts and make final recommendation."""
        
        resolution_context = f"""You are an expert GST/TDS compliance resolver. Analyze and resolve the following:

## Invoice Data
```json
{json.dumps(invoice, indent=2, default=str)}
```

## Validation Result
- Status: {validation_result.get('overall_status')}
- Score: {validation_result.get('compliance_score')}%
- Failed Checks: {len(validation_result.get('validation_results', []))}

## Conflicts to Resolve
{json.dumps(conflicts, indent=2) if conflicts else "None detected"}

## OCR Corrections Applied
{json.dumps(ocr_corrections, indent=2) if ocr_corrections else "None needed"}

## Temporal Rules
{json.dumps(temporal_adjustments, indent=2)}

## Stateful Issues
{json.dumps(stateful_issues, indent=2)}

## Historical Analysis
{json.dumps(historical_analysis, indent=2)}

## Your Task
Resolve all conflicts and provide a final recommendation. Return JSON:
{{
  "final_recommendation": "APPROVE" | "REJECT" | "ESCALATE",
  "confidence_score": 0.0-1.0,
  "requires_human_review": true/false,
  "reasoning": "<your detailed reasoning>",
  "conflict_resolutions": [
    {{"conflict_type": "...", "resolution": "...", "regulatory_basis": "..."}}
  ],
  "ocr_summary": "<summary of corrections>",
  "temporal_summary": "<summary of date-based adjustments>",
  "historical_deviation_note": "<if deviating from precedent, explain why>",
  "key_risks": ["<risk 1>", "<risk 2>"]
}}

IMPORTANT:
- If confidence < 0.70, set requires_human_review to true
- Cite specific regulations (Section 194J, CBDT Circular, etc.)
- Flag any suspicious historical precedents
- Apply rules as of invoice date, not today"""

        try:
            # Create chain and invoke
            chain = self.prompt | self.model
            
            response = chain.invoke({
                "resolution_context": resolution_context
            })
            
            result = json.loads(response.content)
            
            # Ensure human review if confidence < 70%
            if result.get("confidence_score", 0) < 0.70:
                result["requires_human_review"] = True
            
            # Add metadata
            result["conflicts_detected"] = len(conflicts)
            result["ocr_corrections_count"] = len(ocr_corrections)
            result["ocr_corrections"] = ocr_corrections
            result["temporal_adjustments"] = temporal_adjustments
            result["stateful_issues"] = stateful_issues
            result["historical_analysis"] = historical_analysis
            
            return result
            
        except Exception as e:
            return {
                "final_recommendation": "ESCALATE",
                "confidence_score": 0,
                "requires_human_review": True,
                "reasoning": f"LLM resolution failed: {str(e)}",
                "error": str(e)
            }


# Singleton instance
resolver_agent = ResolverAgent()
