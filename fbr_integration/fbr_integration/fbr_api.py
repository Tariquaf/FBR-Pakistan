# Copyright (c) 2026, FBR Pakistan Integration and contributors
# For license information, please see license.txt
"""
Builds the FBR IRIS Digital Invoicing payload from a submitted Sales Invoice
and posts it to FBR's Sandbox or Production endpoint, per the FBR-Pakistan
integration guide (PRAL Digital Invoicing API).
"""

import json

import frappe
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REDUCED_SALE_TYPES = ("goodsatreducedrate", "reducedrate", "rr")


def safe_float(val):
	"""Return a non-negative float, or 0 for blank / invalid / negative input."""
	try:
		num = float(val)
		return num if num >= 0 else 0
	except (TypeError, ValueError):
		return 0


def extra_tax_value(val, sale_type_str):
	"""
	FBR expects an empty string (not 0) for extraTax when the sale type is a
	reduced-rate type, or when the value is blank/zero/negative.
	"""
	if sale_type_str in REDUCED_SALE_TYPES:
		return ""
	try:
		num = float(val)
		return num if num > 0 else ""
	except (TypeError, ValueError):
		return ""


def get_fbr_settings():
	settings = frappe.get_single("FBR Invoice Settings")

	if not settings.enabled:
		frappe.throw(
			frappe._("FBR Integration is disabled. Enable it in FBR Invoice Settings first."),
			title=frappe._("FBR Integration Disabled"),
		)

	if settings.integration_type == "Sandbox":
		api_url = settings.sandbox_api_url
		token = settings.get_password("sandbox_security_token", raise_exception=False)
	elif settings.integration_type == "Production":
		api_url = settings.production_api_url
		token = settings.get_password("production_security_token", raise_exception=False)
	else:
		frappe.throw(frappe._("Invalid FBR Integration Type. Set it to Sandbox or Production."))

	if not api_url or not token:
		frappe.throw(
			frappe._("Please configure the API URL and Security Token in FBR Invoice Settings for {0}.").format(
				settings.integration_type
			)
		)

	return settings, api_url, token


def build_address(address_name):
	"""Returns (address_line, province) for a given Address doctype name."""
	if not address_name:
		return "", ""
	address_doc = frappe.get_doc("Address", address_name)
	address_line = ", ".join(filter(None, [address_doc.address_line1, address_doc.city]))
	return address_line, (address_doc.state or "")


def build_payload(doc):
	seller_address, seller_province = build_address(getattr(doc, "company_address", None))
	buyer_address, buyer_province = build_address(getattr(doc, "customer_address", None))

	# Prefer the explicit link fields when set; fall back to values fetched onto the address
	seller_province = seller_province or ""
	buyer_province = doc.get("custom_buyer_province") or buyer_province

	items_list = []
	for item in doc.items:
		sale_type_str = str(item.get("custom_sale_type") or "").lower().replace(" ", "")
		extra_tax = extra_tax_value(item.get("custom_extra_tax"), sale_type_str)

		if doc.get("custom_scenario_id") == "SN006":
			rate_val = "Exempt"
		else:
			rate_val = "{:.2f}%".format(safe_float(item.get("custom_sales_tax_rate")))

		items_list.append({
			"hsCode": item.get("custom_hs_code"),
			"productDescription": item.item_name,
			"rate": rate_val,
			"uoM": item.get("custom_fbr_uom"),
			"quantity": safe_float(item.qty),
			"totalValues": safe_float(item.get("custom_tax_inclusive_amount")),
			"valueSalesExcludingST": safe_float(item.amount),
			"fixedNotifiedValueOrRetailPrice": safe_float(item.rate),
			"salesTaxApplicable": safe_float(item.get("custom_sales_tax")),
			"salesTaxWithheldAtSource": 0,
			"extraTax": extra_tax,
			"furtherTax": safe_float(item.get("custom_further_tax")),
			"sroScheduleNo": item.get("custom_sro_schedule_no"),
			"fedPayable": 0,
			"discount": safe_float(item.discount_amount),
			"saleType": item.get("custom_sale_type"),
			"sroItemSerialNo": item.get("custom_sro_item_sno"),
		})

	return {
		"invoiceType": doc.get("custom_invoice_type"),
		"invoiceDate": str(doc.posting_date),
		"sellerNTNCNIC": doc.company_tax_id,
		"sellerBusinessName": doc.company,
		"sellerAddress": seller_address,
		"sellerProvince": seller_province,
		"buyerNTNCNIC": doc.tax_id,
		"buyerBusinessName": doc.customer,
		"buyerAddress": buyer_address,
		"buyerProvince": buyer_province,
		"invoiceRefNo": doc.name,
		"scenarioId": doc.get("custom_scenario_id"),
		"buyerRegistrationType": doc.get("custom_tax_payer_type"),
		"items": items_list,
	}


def send_invoice_to_fbr(doc, method=None):
	settings, api_url, token = get_fbr_settings()
	payload = build_payload(doc)

	headers = {
		"Authorization": f"Bearer {token}",
		"Content-Type": "application/json",
	}

	frappe.logger().info(f"Sending Sales Invoice {doc.name} to FBR ({settings.integration_type})")

	try:
		response = requests.post(api_url, headers=headers, json=payload, verify=bool(settings.ssl_applied))
		response.raise_for_status()
		res_json = response.json()
	except requests.exceptions.RequestException as e:
		doc.custom_fbr_responsed = "Error"
		doc.custom_fbr_digital_invoice_response = str(e)
		doc.save(ignore_permissions=True)
		frappe.throw(frappe._("FBR request failed: {0}").format(str(e)), title=frappe._("FBR Error"))
		return

	frappe.logger().info(f"FBR response for {doc.name}: {json.dumps(res_json, indent=2)}")

	validation = res_json.get("validationResponse", {})
	if validation.get("statusCode") == "00":
		invoice_item_nos = [
			status.get("invoiceNo", "")
			for status in validation.get("invoiceStatuses", [])
			if status.get("invoiceNo")
		]

		doc.custom_fbr_integration_type = settings.integration_type
		doc.custom_fbr_invoice_no = res_json.get("invoiceNumber", "")
		doc.custom_fbr_submission_time = res_json.get("dated") or frappe.utils.now_datetime()
		doc.custom_fbr_invoice_status = validation.get("status", "")
		doc.custom_fbr_invoice_status_code = validation.get("statusCode", "")
		doc.custom_fbr_invoice_error = validation.get("error", "")
		doc.custom_fbr_invoice_statuses = json.dumps(validation.get("invoiceStatuses", []), indent=2)
		doc.custom_fbr_invoice_item_no = ", ".join(invoice_item_nos)
		doc.custom_fbr_qr_code = res_json.get("invoiceNumber", "")
		doc.custom_fbr_digital_invoice_response = json.dumps(res_json, indent=2)
		doc.custom_fbr_responsed = "Success"
		doc.save(ignore_permissions=True)
		return res_json

	doc.custom_fbr_responsed = "Error"
	doc.custom_fbr_digital_invoice_response = json.dumps(res_json, indent=2)
	doc.save(ignore_permissions=True)
	frappe.throw(
		frappe._("FBR rejected the invoice: {0}").format(json.dumps(res_json)),
		title=frappe._("FBR Error"),
	)


def after_submit_invoice(doc, method=None):
	"""Optional: wire this into hooks.py doc_events['Sales Invoice']['on_submit']
	if you want invoices pushed to FBR automatically on submit instead of via
	the 'Send to FBR' button."""
	send_invoice_to_fbr(doc)
