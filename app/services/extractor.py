"""
Extractor Agent Service

This service uses OpenAI GPT-4o with vision capabilities to analyze uploaded
documents (invoices) and extract structured data for GST compliance validation.
"""

import os
import base64
import json
from typing import Optional, Dict, Any, List
from pathlib import Path
from openai import OpenAI
import pymupdf  # PyMuPDF for PDF handling

from app.core.config import settings


class ExtractorAgent:
    """
    AI-powered document extractor that analyzes invoices and determines
    if they are valid for compliance processing.
    """

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o"

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Convert an image file to base64 string."""
        with open(image_path, "rb") as image_file:
            return base64.standard_b64encode(image_file.read()).decode("utf-8")

    def _pdf_to_images(self, pdf_path: str) -> List[str]:
        """
        Convert PDF pages to images and return list of base64 encoded images.
        Only processes the first page for efficiency.
        """
        images = []
        doc = pymupdf.open(pdf_path)
        
        # Process only first page for initial analysis
        for page_num in range(min(1, len(doc))):
            page = doc[page_num]
            # Render page to image with good resolution
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            
            # Save temporarily and encode
            temp_path = f"/tmp/page_{page_num}.png"
            pix.save(temp_path)
            images.append(self._encode_image_to_base64(temp_path))
            os.remove(temp_path)
        
        doc.close()
        return images

    def _get_image_from_file(self, file_path: str) -> List[str]:
        """Get base64 encoded images from file (PDF or image)."""
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext == ".pdf":
            return self._pdf_to_images(file_path)
        elif file_ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
            return [self._encode_image_to_base64(file_path)]
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

    def analyze_document(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a document and extract GST invoice information.
        
        Returns:
            Dict containing:
            - is_valid_invoice: bool - Whether this is a valid GST invoice
            - decision: str - "ACCEPT" or "REJECT"
            - extracted_fields: dict - Extracted invoice data
            - confidence_score: float - Confidence in the extraction (0-1)
            - rejection_reasons: list - Reasons for rejection if any
            - document_type: str - Type of document detected
        """
        if not os.path.exists(file_path):
            return {
                "is_valid_invoice": False,
                "decision": "REJECT",
                "extracted_fields": {},
                "confidence_score": 0.0,
                "rejection_reasons": ["File not found"],
                "document_type": "unknown"
            }

        try:
            images = self._get_image_from_file(file_path)
        except Exception as e:
            return {
                "is_valid_invoice": False,
                "decision": "REJECT",
                "extracted_fields": {},
                "confidence_score": 0.0,
                "rejection_reasons": [f"Error processing file: {str(e)}"],
                "document_type": "unknown"
            }

        # Build the extraction prompt
        extraction_prompt = """You are a GST Invoice Compliance Validator Agent. Analyze this document and extract information.

First, determine if this is a valid GST/Tax invoice. A valid GST invoice must contain:
1. Invoice number and date
2. Seller's GSTIN (15-character alphanumeric)
3. Buyer's GSTIN (if B2B transaction)
4. HSN/SAC codes for items
5. Taxable value and tax amounts (CGST/SGST or IGST)
6. Total amount

Extract the following fields if present:
- invoice_number: The invoice/bill number
- invoice_date: Date of the invoice
- seller_name: Name of the seller/supplier
- seller_gstin: Seller's 15-digit GSTIN
- seller_address: Seller's address
- buyer_name: Name of the buyer
- buyer_gstin: Buyer's 15-digit GSTIN (if B2B)
- buyer_address: Buyer's address
- hsn_codes: List of HSN/SAC codes
- items: List of items with description, quantity, rate, amount
- taxable_amount: Total taxable value
- cgst_amount: Central GST amount
- sgst_amount: State GST amount
- igst_amount: Integrated GST amount
- total_tax: Total tax amount
- total_amount: Grand total
- irn: E-invoice IRN if present (64-character hash)
- place_of_supply: State/UT of supply

Respond with a JSON object in this exact format:
{
    "is_valid_invoice": true/false,
    "decision": "ACCEPT" or "REJECT",
    "document_type": "gst_invoice" | "bill_of_supply" | "receipt" | "purchase_order" | "other",
    "confidence_score": 0.0 to 1.0,
    "rejection_reasons": ["reason1", "reason2"] or [],
    "extracted_fields": {
        "invoice_number": "...",
        "invoice_date": "...",
        "seller_name": "...",
        "seller_gstin": "...",
        "seller_address": "...",
        "buyer_name": "...",
        "buyer_gstin": "...",
        "buyer_address": "...",
        "hsn_codes": [...],
        "items": [{"description": "...", "quantity": ..., "rate": ..., "amount": ...}],
        "taxable_amount": ...,
        "cgst_amount": ...,
        "sgst_amount": ...,
        "igst_amount": ...,
        "total_tax": ...,
        "total_amount": ...,
        "irn": "...",
        "place_of_supply": "..."
    }
}

If a field is not present or not applicable, use null for that field.
Only respond with the JSON object, no additional text.

CRITICAL INSTRUCTIONS FOR REJECTION:
1. If the image is NOT a document (e.g. a photo of a person, SELFIE, CHILD, animal, landscape, random object), set "is_valid_invoice": false, "decision": "REJECT", "rejection_reasons": ["Not a document/invoice", "Random image detected", "Photo of person/object"].
2. If the document is not an invoice (e.g. valid ID card, subway map, handwriting, random text), set "is_valid_invoice": false.
3. If "seller_gstin" is NOT found or visible, set "is_valid_invoice": false, "decision": "REJECT", "rejection_reasons": ["Missing Seller GSTIN"]."""

        # Build the message with images
        content = [{"type": "text", "text": extraction_prompt}]
        
        for img_base64 in images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_base64}",
                    "detail": "high"
                }
            })

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=4096,
                temperature=0.1
            )

            # Parse the response
            result_text = response.choices[0].message.content.strip()
            
            # Clean up the response if it has markdown code blocks
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            # --- STRICT EDGE CASE HANDLING ---
            # 1. Programmatic check for GSTIN (Critical for compliance)
            extracted = result.get("extracted_fields", {})
            seller_gstin = extracted.get("seller_gstin")
            
            # 2. Strict Document Type Check
            valid_doc_types = ["gst_invoice", "bill_of_supply", "receipt", "purchase_order"]
            doc_type = result.get("document_type", "unknown").lower()
            
            # 3. Confidence Check
            confidence = result.get("confidence_score", 0.0)
            
            reasons = result.get("rejection_reasons", [])
            
            should_reject = False
            
            if not result.get("is_valid_invoice", False):
                should_reject = True # Already rejected by LLM
                
            elif doc_type not in valid_doc_types:
                should_reject = True
                reasons.append(f"Invalid document type: {doc_type}")
                
            elif not seller_gstin:
                should_reject = True
                reasons.append("Missing Seller GSTIN (Enforced)")
                
            elif confidence < 0.6: # Reject low confidence extractions
                should_reject = True
                reasons.append(f"Low confidence score: {confidence}")

            if should_reject:
                result["is_valid_invoice"] = False
                result["decision"] = "REJECT"
                result["rejection_reasons"] = reasons
                
            return result

        except json.JSONDecodeError as e:
            return {
                "is_valid_invoice": False,
                "decision": "REJECT",
                "extracted_fields": {},
                "confidence_score": 0.0,
                "rejection_reasons": [f"Failed to parse AI response: {str(e)}"],
                "document_type": "unknown",
                "raw_response": result_text if 'result_text' in locals() else None
            }
        except Exception as e:
            return {
                "is_valid_invoice": False,
                "decision": "REJECT",
                "extracted_fields": {},
                "confidence_score": 0.0,
                "rejection_reasons": [f"AI analysis failed: {str(e)}"],
                "document_type": "unknown"
            }


# Singleton instance
extractor_agent = ExtractorAgent()
