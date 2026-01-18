"""
LLM-Based Reporter Agent Service

Generates comprehensive, actionable compliance reports by synthesizing outputs
from the Extractor, Validator, and Resolver agents.
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm_client import get_llm_client, get_model_name, get_current_provider


class ActionItem(BaseModel):
    """Action item from report."""
    priority: str  # HIGH, MEDIUM, LOW
    action: str
    owner: str
    deadline: str
    status: str = "PENDING"


class ReportSection(BaseModel):
    """Report section."""
    title: str
    content: str


class ReporterAgent:
    """
    LLM-powered Reporter Agent for generating compliance reports.
    
    Capabilities:
    - Generate executive summaries for management
    - Create detailed audit reports
    - Produce actionable items with priorities
    - Format reports for different audiences
    """
    
    def __init__(self):
        # Use configurable LLM client
        self.client = None  # Will be set dynamically
        self.model = None  # Will be set dynamically
    
    def generate_report(
        self,
        upload_id: int,
        extraction_result: Dict,
        validation_result: Dict,
        resolver_result: Optional[Dict] = None,
        report_type: str = "executive_summary"
    ) -> Dict:
        """
        Generate a comprehensive compliance report.
        
        Args:
            upload_id: The upload ID
            extraction_result: Output from Extractor Agent
            validation_result: Output from Validator Agent
            resolver_result: Output from Resolver Agent (optional)
            report_type: Type of report to generate
            
        Returns:
            Complete report with all sections
        """
        extracted = extraction_result.get("extracted_fields", {})
        
        # Build context for LLM
        context = self._build_context(extracted, validation_result, resolver_result)
        
        # Generate report using LLM
        report = self._generate_llm_report(upload_id, context, report_type)
        
        return report
    
    def _build_context(
        self,
        extracted: Dict,
        validation_result: Dict,
        resolver_result: Optional[Dict]
    ) -> Dict:
        """Build comprehensive context for report generation."""
        
        # Extract key metrics
        invoice_num = extracted.get("invoice_number", "Unknown")
        vendor = extracted.get("vendor_name") or extracted.get("seller_name", "Unknown")
        total = extracted.get("total_amount") or extracted.get("grand_total", 0)
        invoice_date = extracted.get("invoice_date", "Unknown")
        
        # Validation metrics
        val_status = validation_result.get("overall_status", "UNKNOWN")
        compliance_score = validation_result.get("compliance_score", 0)
        checks_passed = validation_result.get("checks_passed", 0)
        checks_failed = validation_result.get("checks_failed", 0)
        checks_warned = validation_result.get("checks_warned", 0)
        failed_checks = validation_result.get("validation_results", [])
        
        # Resolver metrics
        final_decision = "PENDING"
        confidence = 0
        resolutions = []
        risks = []
        
        if resolver_result:
            final_decision = resolver_result.get("final_recommendation", "PENDING")
            confidence = resolver_result.get("confidence_score", 0)
            resolutions = resolver_result.get("conflict_resolutions", [])
            risks = resolver_result.get("key_risks", [])
        
        return {
            "invoice": {
                "number": invoice_num,
                "vendor": vendor,
                "total": total,
                "date": invoice_date,
                "gstin": extracted.get("seller_gstin") or extracted.get("gstin")
            },
            "validation": {
                "status": val_status,
                "score": compliance_score,
                "passed": checks_passed,
                "failed": checks_failed,
                "warned": checks_warned,
                "failed_checks": failed_checks
            },
            "resolution": {
                "decision": final_decision,
                "confidence": confidence,
                "resolutions": resolutions,
                "risks": risks,
                "human_review": resolver_result.get("requires_human_review", False) if resolver_result else False
            }
        }
    
    def _generate_llm_report(
        self,
        upload_id: int,
        context: Dict,
        report_type: str
    ) -> Dict:
        """Generate report using LLM."""
        
        prompt = f"""Generate a compliance report for invoice analysis.

## Context
```json
{json.dumps(context, indent=2, default=str)}
```

## Report Type: {report_type}

Generate a JSON report with:
{{
  "report_id": "RPT-{upload_id}-{datetime.now().strftime('%Y%m%d')}",
  "report_type": "{report_type}",
  "generated_at": "{datetime.now().isoformat()}",
  
  "executive_summary": "<2-3 sentence executive summary>",
  
  "decision": {{
    "status": "APPROVE|REJECT|REVIEW",
    "confidence": 0.0-1.0,
    "rationale": "<brief rationale>"
  }},
  
  "risk_assessment": {{
    "level": "LOW|MEDIUM|HIGH|CRITICAL",
    "score": 0-100,
    "factors": ["<factor1>", "<factor2>"]
  }},
  
  "compliance_stats": {{
    "total_checks": 45,
    "passed": <n>,
    "failed": <n>,
    "warnings": <n>,
    "gst_compliance": "<percentage>%",
    "tds_compliance": "<percentage>%"
  }},
  
  "action_items": [
    {{
      "priority": "HIGH|MEDIUM|LOW",
      "action": "<specific action>",
      "owner": "AP Team|Tax Team|Compliance|Management",
      "deadline": "24 hrs|48 hrs|1 week",
      "regulatory_basis": "<section or circular>"
    }}
  ],
  
  "key_findings": [
    {{
      "category": "GST|TDS|POLICY|DATA",
      "finding": "<description>",
      "impact": "HIGH|MEDIUM|LOW",
      "recommendation": "<what to do>"
    }}
  ],
  
  "recommendations": [
    "<recommendation 1>",
    "<recommendation 2>"
  ],
  
  "approval_workflow": {{
    "current_level": "Auto|Manager|Sr.Manager|Director|CFO",
    "required_level": "<based on amount>",
    "escalation_needed": true/false
  }}
}}

IMPORTANT:
- Be specific and actionable
- Cite regulations (Section 194J, CBDT Circular, etc.)
- Prioritize action items correctly
- Calculate risk based on failed checks severity"""

        try:
            # Get LLM client and model for current provider
            provider = get_current_provider()
            model = get_model_name()
            client = get_llm_client()
            
            print(f"🤖 Using LLM Provider: {provider}")
            print(f"📦 Model: {model}")
            
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert GST/TDS compliance report generator. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2048
            )
            
            report = json.loads(response.choices[0].message.content)
            
            # Add metadata
            report["upload_id"] = upload_id
            report["invoice_details"] = context["invoice"]
            report["llm_metadata"] = {
                "provider": provider,
                "model": model,
                "generated_at": datetime.now().isoformat()
            }
            
            return report
            
        except Exception as e:
            # Get provider info for error reporting
            provider = get_current_provider()
            model = get_model_name()
            
            # Determine error type
            error_type = type(e).__name__
            error_message = str(e)
            
            # Create detailed error report
            error_details = {
                "llm_provider": provider,
                "llm_model": model,
                "error_type": error_type,
                "error_message": error_message,
            }
            
            # Check for specific error types
            if "402" in error_message or "Insufficient Balance" in error_message:
                error_details["issue"] = "INSUFFICIENT_BALANCE"
                error_details["suggestion"] = f"The {provider.upper()} API account has insufficient balance. Please add credits or switch to a different LLM provider in Settings."
            elif "401" in error_message or "Unauthorized" in error_message:
                error_details["issue"] = "INVALID_API_KEY"
                error_details["suggestion"] = f"The API key for {provider.upper()} is invalid or missing. Please check your .env configuration."
            elif "429" in error_message or "rate limit" in error_message.lower():
                error_details["issue"] = "RATE_LIMIT_EXCEEDED"
                error_details["suggestion"] = f"The {provider.upper()} API rate limit has been exceeded. Please wait or switch providers."
            else:
                error_details["issue"] = "UNKNOWN_ERROR"
                error_details["suggestion"] = "An unexpected error occurred. Please check logs for more details."
            
            print(f"❌ LLM Error Details:")
            print(f"   Provider: {provider}")
            print(f"   Model: {model}")
            print(f"   Error Type: {error_type}")
            print(f"   Error: {error_message}")
            print(f"   Suggestion: {error_details['suggestion']}")
            
            return {
                "report_id": f"RPT-{upload_id}-ERROR",
                "report_type": report_type,
                "error": error_message,
                "error_details": error_details,
                "generated_at": datetime.now().isoformat(),
                "executive_summary": f"📋 Executive Summary\nReport generation failed: {error_message}\n\n🤖 LLM Provider: {provider}\n📦 Model: {model}\n❌ Issue: {error_details['issue']}\n💡 Suggestion: {error_details['suggestion']}"
            }
    
    def generate_text_report(self, report: Dict) -> str:
        """Convert JSON report to formatted text."""
        
        lines = []
        lines.append("=" * 60)
        lines.append(f"📊 COMPLIANCE REPORT - {report.get('report_id', 'Unknown')}")
        lines.append("=" * 60)
        lines.append("")
        
        # Decision
        decision = report.get("decision", {})
        status_emoji = {"APPROVE": "✅", "REJECT": "❌", "REVIEW": "⚠️"}.get(decision.get("status"), "❓")
        lines.append(f"Decision: {status_emoji} {decision.get('status', 'UNKNOWN')}")
        lines.append(f"Confidence: {int(decision.get('confidence', 0) * 100)}%")
        lines.append("")
        
        # Executive Summary
        lines.append("📋 EXECUTIVE SUMMARY")
        lines.append("-" * 40)
        lines.append(report.get("executive_summary", "No summary available"))
        lines.append("")
        
        # Risk Assessment
        risk = report.get("risk_assessment", {})
        lines.append(f"🎯 RISK LEVEL: {risk.get('level', 'UNKNOWN')} ({risk.get('score', 0)}/100)")
        lines.append("")
        
        # Compliance Stats
        stats = report.get("compliance_stats", {})
        lines.append("📈 COMPLIANCE STATS")
        lines.append("-" * 40)
        lines.append(f"• Checks: {stats.get('passed', 0)} passed | {stats.get('failed', 0)} failed | {stats.get('warnings', 0)} warnings")
        lines.append(f"• GST Compliance: {stats.get('gst_compliance', 'N/A')}")
        lines.append(f"• TDS Compliance: {stats.get('tds_compliance', 'N/A')}")
        lines.append("")
        
        # Action Items
        actions = report.get("action_items", [])
        if actions:
            lines.append("🚨 ACTION ITEMS")
            lines.append("-" * 40)
            for i, action in enumerate(actions, 1):
                priority_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(action.get("priority"), "⚪")
                lines.append(f"{i}. {priority_emoji} [{action.get('priority')}] {action.get('action')}")
                lines.append(f"   Owner: {action.get('owner')} | Deadline: {action.get('deadline')}")
            lines.append("")
        
        # Key Findings
        findings = report.get("key_findings", [])
        if findings:
            lines.append("🔍 KEY FINDINGS")
            lines.append("-" * 40)
            for finding in findings:
                impact_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(finding.get("impact"), "⚪")
                lines.append(f"• [{finding.get('category')}] {impact_emoji} {finding.get('finding')}")
                lines.append(f"  → {finding.get('recommendation')}")
            lines.append("")
        
        # Recommendations
        recommendations = report.get("recommendations", [])
        if recommendations:
            lines.append("💡 RECOMMENDATIONS")
            lines.append("-" * 40)
            for rec in recommendations:
                lines.append(f"• {rec}")
            lines.append("")
        
        # Approval Workflow
        workflow = report.get("approval_workflow", {})
        if workflow:
            lines.append("👤 APPROVAL WORKFLOW")
            lines.append("-" * 40)
            lines.append(f"• Current Level: {workflow.get('current_level', 'N/A')}")
            lines.append(f"• Required Level: {workflow.get('required_level', 'N/A')}")
            if workflow.get("escalation_needed"):
                lines.append("• ⚠️ ESCALATION REQUIRED")
        
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"Generated: {report.get('generated_at', 'Unknown')}")
        lines.append("=" * 60)
        
        return "\n".join(lines)


# Singleton instance
reporter_agent = ReporterAgent()
