"""
Extraction Schemas

Pydantic models for extraction request/response.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ExtractionRequest(BaseModel):
    """Request to trigger extraction for an upload."""
    upload_id: int


class ExtractedItem(BaseModel):
    """A single line item from an invoice."""
    description: Optional[str] = None
    quantity: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None


class ExtractedFields(BaseModel):
    """Extracted invoice fields."""
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    seller_gstin: Optional[str] = None
    seller_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    buyer_address: Optional[str] = None
    hsn_codes: Optional[List[str]] = None
    items: Optional[List[Dict[str, Any]]] = None
    taxable_amount: Optional[float] = None
    cgst_amount: Optional[float] = None
    sgst_amount: Optional[float] = None
    igst_amount: Optional[float] = None
    total_tax: Optional[float] = None
    total_amount: Optional[float] = None
    irn: Optional[str] = None
    place_of_supply: Optional[str] = None


class ExtractionResult(BaseModel):
    """Result of document extraction."""
    upload_id: int
    is_valid_invoice: bool = Field(..., description="Whether this is a valid GST invoice")
    decision: str = Field(..., description="ACCEPT or REJECT")
    document_type: str = Field(default="unknown", description="Type of document detected")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in extraction")
    rejection_reasons: List[str] = Field(default_factory=list, description="Reasons for rejection")
    extracted_fields: Dict[str, Any] = Field(default_factory=dict, description="Extracted data")

    class Config:
        from_attributes = True
