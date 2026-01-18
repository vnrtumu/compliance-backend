import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

class GSTClient:
    """Client for interacting with the mock GST Portal."""
    
    def __init__(self):
        self.base_url = settings.GST_SERVER_URL
        
    def validate_gstin(self, gstin: str) -> Dict[str, Any]:
        """Validate GSTIN and get taxpayer details."""
        try:
            response = httpx.post(
                f"{self.base_url}/api/gst/validate-gstin",
                json={"gstin": gstin},
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
            return {"valid": False, "error": "API_ERROR", "status_code": response.status_code}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_hsn_rate(self, code: str, date: Optional[str] = None) -> Dict[str, Any]:
        """Get GST rate for HSN/SAC code."""
        try:
            params = {"code": code}
            if date:
                params["date"] = date
                
            response = httpx.get(
                f"{self.base_url}/api/gst/hsn-rate",
                params=params,
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
            return {"error": "API_ERROR"}
        except Exception:
            return {"error": "CONNECTION_ERROR"}

    def check_einvoice_eligibility(self, gstin: str) -> Dict[str, Any]:
        """Check if e-invoicing is required for the seller."""
        try:
            response = httpx.post(
                f"{self.base_url}/api/einvoice/eligibility",
                json={"seller_gstin": gstin},
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json()
            return {"error": "API_ERROR"}
        except Exception:
            return {"error": "CONNECTION_ERROR"}

# Singleton instance
gst_client = GSTClient()
