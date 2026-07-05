# Copyright (c) 2026, FBR Pakistan Integration and contributors
# For license information, please see license.txt

import frappe

from fbr_integration.fbr_integration.fbr_api import send_invoice_to_fbr


@frappe.whitelist()
def send_to_fbr_si(name):
	"""
	Called by the "Send to FBR" client script button on Sales Invoice.

	Returns:
		{"success": True, "invoice_no": "..."}
		{"success": False, "error": "..."}
	"""
	doc = frappe.get_doc("Sales Invoice", name)

	if doc.docstatus != 1:
		return {"success": False, "error": frappe._("Sales Invoice must be submitted before sending to FBR.")}

	if doc.custom_fbr_invoice_no:
		return {"success": False, "error": frappe._("This invoice was already sent to FBR.")}

	try:
		send_invoice_to_fbr(doc)
		return {"success": True, "invoice_no": doc.get("custom_fbr_invoice_no", "")}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "fbr_integration.send_to_fbr_si")
		frappe.clear_last_message()
		return {"success": False, "error": str(e)}
