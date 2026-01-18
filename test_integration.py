import sys
import os
import json
from unittest.mock import MagicMock

# Add app to path
sys.path.append("/Users/venkatreddy/Desktop/AgenticAITest/compliance-backend")

# Mock OpenAI before importing validator to avoid API key errors during test
sys.modules["openai"] = MagicMock()

from app.services.validator import validator_agent
from app.services.gst_client import gst_client

def test_gst_integration():
    print("Testing GST Client Integration...")
    
    # Test 1: Direct Client Call
    print("\n1. Testing GSTClient direct call...")
    gstin = "27AABCT1234F1ZP" # Known mock GSTIN
    res = gst_client.validate_gstin(gstin)
    print(f"Result: {json.dumps(res, indent=2)}")
    
    if res.get("valid") == True:
        print("✅ GSTClient.validate_gstin PASSED")
    else:
        print("❌ GSTClient.validate_gstin FAILED")
        
    # Test 2: Validation Enrichment
    print("\n2. Testing Validator Enrichment...")
    
    # Dummy extraction result
    dummy_extraction = {
        "extracted_fields": {
            "invoice_number": "INV-123",
            "invoice_date": "2024-01-01",
            "vendor_gstin": "27AABCT1234F1ZP",
            "line_items": [
                {"description": "Test Item", "hsn_sac": "998311", "amount": 1000}
            ],
            "total_amount": 1000
        }
    }
    
    # We want to check if _build_validation_prompt calls the gst_client
    # and includes the data in the prompt.
    
    # Mocking the client calls inside validator to trace them, 
    # but strictly we want to see if the REAL client works. 
    # Let's trust the Real client call from Test 1, and here checking if logic flows.
    
    try:
        # We need to mock _build_validation_prompt to inspect the vendor_info 
        # passed to it, because validate_document calls it.
        original_build = validator_agent._build_validation_prompt
        
        captured_vendor_info = None
        
        def side_effect(extracted, vendor_info):
            nonlocal captured_vendor_info
            captured_vendor_info = vendor_info
            return "Mock Prompt"
            
        validator_agent._build_validation_prompt = side_effect
        
        # Run validation (will fail at LLM step but we catch exception)
        validator_agent.validate_document(123, dummy_extraction)
        
        # Restore
        validator_agent._build_validation_prompt = original_build
        
        if captured_vendor_info and "portal_verification" in captured_vendor_info:
            print("✅ Validator Agent enriched vendor_info with portal_verification data")
            print(json.dumps(captured_vendor_info["portal_verification"], indent=2))
        else:
            print("❌ Validator Agent FAILED to enrich vendor_info")
            
    except Exception as e:
        print(f"❌ Test Exception: {e}")

if __name__ == "__main__":
    test_gst_integration()
