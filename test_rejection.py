import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.append("/Users/venkatreddy/Desktop/AgenticAITest/compliance-backend")

# Mock dependencies
sys.modules["openai"] = MagicMock()
sys.modules["app.core.db"] = MagicMock()

# Import after mocking
from app.services.extractor import extractor_agent
from app.services.bulk_processor import bulk_processor

def test_extractor_gstin_enforcement():
    print("\n1. Testing Extractor GSTIN Enforcement...")
    
    # Mock LLM response
    mock_content = """{
        "is_valid_invoice": true,
        "decision": "ACCEPT",
        "document_type": "gst_invoice",
        "extracted_fields": {
            "invoice_number": "123",
            "seller_name": "No GST Seller"
        }
    }"""
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=mock_content))]
    
    # MOCK the OpenAI client call on the agent
    extractor_agent.client.chat.completions.create.return_value = mock_response
    
    # MOCK the image loader using patch.object to clean up after
    with patch.object(extractor_agent, '_get_image_from_file', return_value=["base64img"]), \
         patch("os.path.exists", return_value=True):
        
        result = extractor_agent.analyze_document("dummy.jpg")
    
    # Verify
    if result["is_valid_invoice"] == False and "Missing Seller GSTIN (Enforced)" in str(result.get("rejection_reasons")):
        print("✅ Extractor correctly REJECTED invoice missing GSTIN (Programmatic Check worked)")
    else:
        print("❌ Extractor FAILED to reject invoice missing GSTIN")
        print(result)

async def test_bulk_processor_halt():
    print("\n2. Testing Bulk Processor Halt on Rejection...")
    
    mock_db = MagicMock()
    mock_upload = MagicMock()
    mock_upload.extraction_status = "pending"
    mock_upload.is_valid = False # Primary check
    mock_upload.extraction_result = {"is_valid_invoice": False, "rejection_reasons": ["Mock Reason"]} # Fallback check
    
    # Mock Validator to ensure it's NOT called
    from app.services.validator import validator_agent
    validator_agent.validate_document = MagicMock()
    
    def side_effect(db, db_obj, obj_in):
        if "is_valid" in obj_in:
             mock_upload.is_valid = obj_in["is_valid"]
             mock_upload.extraction_result = obj_in["extraction_result"]
    
    # Mock CRUD
    with patch("app.services.bulk_processor.crud") as mock_crud:
        mock_crud.upload.get.return_value = mock_upload
        mock_crud.upload.update.side_effect = side_effect
        
        # Patch analyze_document specifically for this test
        mock_return = {
            "is_valid_invoice": False, 
            "decision": "REJECT", 
            "document_type": "unknown", 
            "rejection_reasons": ["Not a document"]
        }
        
        with patch.object(extractor_agent, 'analyze_document', return_value=mock_return):
            result = await bulk_processor.process_single_invoice(123, mock_db)
        
        # Verify
        if result["status"] == "completed" and result["invoice_status"] == "REJECTED":
            print("✅ BulkProcessor stopped and returned REJECTED status")
        else:
            print(f"❌ BulkProcessor did not return REJECTED status. Got: {result.get('status')} / {result.get('invoice_status')}")
            
        if not validator_agent.validate_document.called:
            print("✅ Validator Agent was NOT called (Efficiency Pass)")
        else:
            print("❌ Validator Agent WAS called (Fail - wasted tokens)")

def test_extractor_strict_checks():
    print("\n3. Testing Extractor Strict Checks (Doc Type & Confidence)...")
    
    # Case A: Invalid Document Type
    mock_content_a = """{
        "is_valid_invoice": true,
        "decision": "ACCEPT",
        "document_type": "id_card",
        "confidence_score": 0.9,
        "extracted_fields": {
            "seller_gstin": "27AABCT1234F1ZP"
        }
    }"""
    
    mock_response_a = MagicMock()
    mock_response_a.choices = [MagicMock(message=MagicMock(content=mock_content_a))]
    
    # Case B: Low Confidence
    mock_content_b = """{
        "is_valid_invoice": true,
        "decision": "ACCEPT",
        "document_type": "gst_invoice",
        "confidence_score": 0.4,
        "extracted_fields": {
             "seller_gstin": "27AABCT1234F1ZP"
        }
    }"""
    
    mock_response_b = MagicMock()
    mock_response_b.choices = [MagicMock(message=MagicMock(content=mock_content_b))]
    
    with patch.object(extractor_agent, '_get_image_from_file', return_value=["base64img"]), \
         patch("os.path.exists", return_value=True):
         
        # Run Case A
        extractor_agent.client.chat.completions.create.return_value = mock_response_a
        result_a = extractor_agent.analyze_document("dummy.jpg")
        
        if result_a["is_valid_invoice"] == False and "Invalid document type: id_card" in str(result_a.get("rejection_reasons")):
             print("✅ Correctly rejected invalid document type 'id_card'")
        else:
             print(f"❌ Failed to reject invalid document type: {result_a}")
             
        # Run Case B
        extractor_agent.client.chat.completions.create.return_value = mock_response_b
        result_b = extractor_agent.analyze_document("dummy.jpg")
        
        if result_b["is_valid_invoice"] == False and "confidence" in str(result_b.get("rejection_reasons")):
             print("✅ Correctly rejected low confidence extraction (0.4)")
        else:
             print(f"❌ Failed to reject low confidence: {result_b}")

if __name__ == "__main__":
    test_extractor_gstin_enforcement()
    asyncio.run(test_bulk_processor_halt())
    test_extractor_strict_checks()
