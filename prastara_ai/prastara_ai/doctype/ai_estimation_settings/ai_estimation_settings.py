import frappe
from frappe.model.document import Document

class AIEstimationSettings(Document):
	pass

@frappe.whitelist()
def test_openai_connection():
	from prastara_ai.api.ai_service import AIService
	try:
		service = AIService()
		if not service.client:
			return {"status": "error", "message": "Client not initialized. Check if the API key is provided and the 'openai' python library is installed."}
			
		# Simple test: attempt to list models (requires valid key)
		service.client.models.list()
		return {"status": "success", "message": "Successfully connected to OpenAI!"}
	except Exception as e:
		return {"status": "error", "message": f"Connection failed: {str(e)}"}
