# Copyright (c) 2026, FBR Pakistan Integration and contributors
# For license information, please see license.txt
"""
Runs once, right after `bench --site <site> install-app fbr_integration`.

Loads the FBR reference/master data (HS Codes, Scenario IDs, Buyer
Provinces, Sale Types, Tax Payer Types, Invoice Types, FBR UoM, SRO
Schedule/Item numbers) shipped as CSVs in fbr_integration/data/, so the app
is usable immediately without a manual Data Import.
"""

import csv
import os

import frappe

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# doctype -> (csv filename, [fieldnames in column order])
MASTER_DATA_MAP = {
	"Buyer Province": ("buyer_province.csv", ["buyer_province"]),
	"FBR UoM": ("fbr_uom.csv", ["fbr_uom"]),
	"Invoice Type": ("invoice_type.csv", ["invoice_type"]),
	"Sale Type": ("sale_type.csv", ["sale_type"]),
	"SRO Item SNo": ("sro_item_sno.csv", ["sro_item_sno"]),
	"SRO Schedule No": ("sro_schedule_no.csv", ["sro_schedule_no"]),
	"Tax Payer Type": ("tax_payer_type.csv", ["tax_payer_type"]),
	"HS Code": ("hs_code.csv", ["hs_code", "hs_code_detail"]),
	"Scenario ID": ("scenario_id.csv", ["scenario_id", "scenario_detail"]),
}


def after_install():
	for doctype, (filename, fieldnames) in MASTER_DATA_MAP.items():
		_load_master_csv(doctype, filename, fieldnames)

	_create_default_settings()
	frappe.db.commit()


def _load_master_csv(doctype, filename, fieldnames):
	path = os.path.join(DATA_DIR, filename)
	if not os.path.exists(path):
		return

	with open(path, newline="", encoding="utf-8-sig") as f:
		reader = csv.reader(f)
		next(reader, None)  # skip header row

		for row in reader:
			if not row or not row[0].strip():
				continue

			values = {fieldnames[i]: (row[i].strip() if i < len(row) else "") for i in range(len(fieldnames))}
			key_field = fieldnames[0]

			if frappe.db.exists(doctype, {key_field: values[key_field]}):
				continue

			try:
				doc = frappe.new_doc(doctype)
				doc.update(values)
				doc.insert(ignore_permissions=True, ignore_mandatory=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"fbr_integration.install: {doctype} import failed")


def _create_default_settings():
	if frappe.db.exists("DocType", "FBR Invoice Settings") and not frappe.db.get_single_value(
		"FBR Invoice Settings", "integration_type"
	):
		settings = frappe.get_single("FBR Invoice Settings")
		settings.integration_type = "Sandbox"
		settings.enabled = 0
		settings.save(ignore_permissions=True)
