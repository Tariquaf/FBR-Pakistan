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
	address_line = ", ".join(
		filter(
			None,
			[
				address_doc.address_line1,
				address_doc.address_line2,
				address_doc.city,
				address_doc.district,
				address_doc.country,
			],
		),
	)
	return address_line, (address_doc.state or "")


def _format_percent(value):
	"""Return a percent string or an empty string for invalid values."""
	try:
		number = float(value)
		return "{:.2f}%".format(number)
	except (TypeError, ValueError):
		return ""


def _normalize_registration_type(registration_type, tax_id):
	"""Prefer an explicit registration type, otherwise infer it from buyer tax id."""
	if registration_type:
		return registration_type
	if not tax_id:
		return "Unregistered"
	return "Registered"


def _get_linked_address(field_name, link_name):
	"""Return the first linked Address name for a named Customer/Company, if available."""
	if not link_name:
		return ""
	return frappe.db.get_value("Address", {field_name: link_name}, "name")


def _get_company_province(company_name):
	"""Return the company province custom field if the explicit address does not provide it."""
	if not company_name:
		return ""
	return frappe.db.get_value("Company", company_name, "custom_province") or ""


def build_payload(doc, integration_type="Sandbox"):
	seller_address, seller_province = build_address(getattr(doc, "company_address", None))
	buyer_address, buyer_province = build_address(getattr(doc, "customer_address", None))

	if not seller_address and getattr(doc, "company", None):
		seller_address, seller_province = build_address(_get_linked_address("company", doc.company))
	if not buyer_address and getattr(doc, "customer", None):
		buyer_address, buyer_province = build_address(_get_linked_address("customer", doc.customer))

	buyer_province = doc.get("custom_buyer_province") or buyer_province
	if not buyer_province and getattr(doc, "customer", None):
		buyer_province = frappe.db.get_value("Customer", doc.customer, "custom_buyer_province") or buyer_province

	seller_province = seller_province or _get_company_province(getattr(doc, "company", None))

	buyer_registration_type = _normalize_registration_type(doc.get("custom_tax_payer_type"), doc.get("tax_id"))
	invoice_type = doc.get("custom_invoice_type") or "Sale Invoice"

	# Validate invoice type per FBR spec section 4.1
	if invoice_type not in ("Sale Invoice", "Debit Note"):
		frappe.throw(
			frappe._("Invalid invoice type. Must be 'Sale Invoice' or 'Debit Note'."),
			title=frappe._("FBR Payload Validation"),
		)

	# For debit notes, invoiceRefNo is mandatory (22-28 digits)
	invoice_ref_no = ""
	if invoice_type == "Debit Note":
		invoice_ref_no = doc.get("custom_invoice_reference_no", "")
		if not invoice_ref_no:
			frappe.throw(
				frappe._("For debit notes, Invoice Reference No. is required."),
				title=frappe._("FBR Payload Validation"),
			)
		if not (22 <= len(str(invoice_ref_no)) <= 28):
			frappe.throw(
				frappe._("Invoice Reference No. must be 22-28 digits (22 for NTN, 28 for CNIC)."),
				title=frappe._("FBR Payload Validation"),
			)

	scenario_id = doc.get("custom_scenario_id")
	
	# ScenarioId is required for Sandbox only (per spec section 4.1.1)
	if integration_type == "Sandbox" and not scenario_id:
		frappe.throw(
			frappe._("Scenario ID is required for Sandbox integration."),
			title=frappe._("FBR Payload Validation"),
		)

	missing = [
		name
		for name, value in {
			"invoiceType": invoice_type,
			"invoiceDate": str(doc.posting_date) if getattr(doc, "posting_date", None) else "",
			"sellerNTNCNIC": getattr(doc, "company_tax_id", ""),
			"sellerBusinessName": getattr(doc, "company", ""),
			"sellerAddress": seller_address,
			"sellerProvince": seller_province,
			"buyerBusinessName": getattr(doc, "customer", ""),
			"buyerAddress": buyer_address,
			"buyerProvince": buyer_province,
			"buyerRegistrationType": buyer_registration_type,
		}.items()
		if not value
	]
	
	# buyerNTNCNIC is required only for Registered buyers (per spec section 4.1)
	if buyer_registration_type == "Registered" and not doc.get("tax_id"):
		missing.append("buyerNTNCNIC")
	elif buyer_registration_type == "Unregistered" and not doc.get("tax_id"):
		# For unregistered buyers, tax_id should be a generic placeholder or empty
		pass

	if missing:
		frappe.throw(
			frappe._(
				"Cannot build FBR payload. Missing required FBR field(s): {0}".format(
					", ".join(missing)
				)
			),
			title=frappe._("FBR Payload Validation"),
		)

	items_list = []
	for idx, item in enumerate(doc.items, start=1):
		sale_type_str = str(item.get("custom_sale_type") or "").lower().replace(" ", "")
		extra_tax = extra_tax_value(item.get("custom_extra_tax"), sale_type_str)

		if scenario_id == "SN006":
			rate_val = "Exempt"
		else:
			rate_val = _format_percent(item.get("custom_sales_tax_rate"))

		item_uom = item.get("custom_fbr_uom") or item.get("uom") or item.get("stock_uom") or ""
		item_hs_code = item.get("custom_hs_code") or ""

		if not rate_val:
			frappe.throw(
				frappe._(
					"Cannot build FBR payload. Item {0} is missing a valid FBR tax rate.".format(idx)
				),
				title=frappe._("FBR Payload Validation"),
			)
		if not item_uom:
			frappe.throw(
				frappe._(
					"Cannot build FBR payload. Item {0} is missing an FBR UoM.".format(idx)
				),
				title=frappe._("FBR Payload Validation"),
			)

		items_list.append({
			"hsCode": item_hs_code,
			"productDescription": item.item_name,
			"rate": rate_val,
			"uoM": item_uom,
			"quantity": safe_float(getattr(item, "qty", None)),
			"totalValues": safe_float(item.get("custom_tax_inclusive_amount")),
			"valueSalesExcludingST": safe_float(getattr(item, "amount", None)),
			"fixedNotifiedValueOrRetailPrice": safe_float(getattr(item, "rate", None)),
			"salesTaxApplicable": safe_float(item.get("custom_sales_tax")),
			"salesTaxWithheldAtSource": safe_float(item.get("custom_sales_tax_withheld_at_source", 0)),
			"extraTax": extra_tax,
			"furtherTax": safe_float(item.get("custom_further_tax")),
			"sroScheduleNo": item.get("custom_sro_schedule_no") or "",
			"fedPayable": safe_float(item.get("custom_fed_payable", 0)),
			"discount": safe_float(getattr(item, "discount_amount", 0)),
			"saleType": item.get("custom_sale_type") or "Goods at standard rate (default)",
			"sroItemSerialNo": item.get("custom_sro_item_sno") or "",
		})

	if not items_list:
		frappe.throw(
			frappe._("Cannot build FBR payload. Sales Invoice must contain at least one item."),
			title=frappe._("FBR Payload Validation"),
		)

	payload = {
		"invoiceType": invoice_type,
		"invoiceDate": str(doc.posting_date),
		"sellerNTNCNIC": doc.company_tax_id,
		"sellerBusinessName": doc.company,
		"sellerAddress": seller_address,
		"sellerProvince": seller_province,
		"buyerNTNCNIC": doc.tax_id or "",
		"buyerBusinessName": doc.customer,
		"buyerAddress": buyer_address,
		"buyerProvince": buyer_province,
		"invoiceRefNo": invoice_ref_no,
		"buyerRegistrationType": buyer_registration_type,
		"items": items_list,
	}
	
	# scenarioId is only included for Sandbox (per spec section 4.1)
	if integration_type == "Sandbox" and scenario_id:
		payload["scenarioId"] = scenario_id
	
	return payload



def send_invoice_to_fbr(doc, method=None):
	"""
	Sends a Sales Invoice to FBR IRIS Digital Invoicing system.
	Calls the POST endpoint (postinvoicedata) with the invoice payload.
	Stores the FBR response and invoice number on successful validation.
	"""
	settings, api_url, token = get_fbr_settings()
	payload = build_payload(doc, integration_type=settings.integration_type)

	headers = {
		"Authorization": f"Bearer {token}",
		"Content-Type": "application/json",
	}

	frappe.logger().info(f"Sending Sales Invoice {doc.name} to FBR ({settings.integration_type})")
	frappe.logger().debug(f"FBR Payload: {json.dumps(payload, indent=2)}")

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

	# Parse validation response per spec section 4.1.3
	validation = res_json.get("validationResponse", {})
	status_code = validation.get("statusCode", "")

	# Success: statusCode "00" means Valid
	if status_code == "00":
		invoice_item_nos = []
		invoice_item_errors = []
		
		# Parse per-item statuses from spec section 4.1.3
		for item_status in validation.get("invoiceStatuses", []):
			item_no = item_status.get("invoiceNo", "")
			item_status_code = item_status.get("statusCode", "")
			
			if item_no:
				invoice_item_nos.append(item_no)
			
			# Check if any item has statusCode "01" (invalid)
			if item_status_code == "01":
				invoice_item_errors.append({
					"itemSNo": item_status.get("itemSNo", ""),
					"error": item_status.get("error", ""),
					"errorCode": item_status.get("errorCode", "")
				})

		# If any item is invalid, mark as error
		if invoice_item_errors:
			doc.custom_fbr_responsed = "Error"
			doc.custom_fbr_digital_invoice_response = json.dumps(res_json, indent=2)
			doc.save(ignore_permissions=True)
			error_details = "; ".join([f"Item {e['itemSNo']}: {e['error']}" for e in invoice_item_errors])
			frappe.throw(
				frappe._("FBR rejected some items: {0}").format(error_details),
				title=frappe._("FBR Error"),
			)
			return

		# Store successful response per spec section 4.1.3
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

	# Failure: statusCode "01" or any other value means Invalid
	doc.custom_fbr_responsed = "Error"
	doc.custom_fbr_digital_invoice_response = json.dumps(res_json, indent=2)
	doc.save(ignore_permissions=True)
	
	error_msg = validation.get("error", "Unknown error")
	error_code = validation.get("errorCode", "")
	if error_code:
		error_msg = f"[{error_code}] {error_msg}"
	
	frappe.throw(
		frappe._("FBR rejected the invoice: {0}").format(error_msg),
		title=frappe._("FBR Error"),
	)


def validate_invoice_with_fbr(doc):
	"""
	Optional: Validates a Sales Invoice with FBR BEFORE submission.
	Calls the Validate endpoint (validateinvoicedata) per spec section 4.2.
	Returns validation result but does not modify the document.
	"""
	settings, api_url, token = get_fbr_settings()
	payload = build_payload(doc, integration_type=settings.integration_type)

	# Use Validate endpoint URL instead of Post endpoint
	validate_url = api_url.replace("postinvoicedata", "validateinvoicedata")

	headers = {
		"Authorization": f"Bearer {token}",
		"Content-Type": "application/json",
	}

	frappe.logger().info(f"Validating Sales Invoice {doc.name} with FBR ({settings.integration_type})")

	try:
		response = requests.post(validate_url, headers=headers, json=payload, verify=bool(settings.ssl_applied))
		response.raise_for_status()
		res_json = response.json()
		return res_json
	except requests.exceptions.RequestException as e:
		frappe.logger().error(f"FBR validation request failed: {e}")
		return None



def after_submit_invoice(doc, method=None):
	"""Optional: wire this into hooks.py doc_events['Sales Invoice']['on_submit']
	if you want invoices pushed to FBR automatically on submit instead of via
	the 'Send to FBR' button."""
	send_invoice_to_fbr(doc)
