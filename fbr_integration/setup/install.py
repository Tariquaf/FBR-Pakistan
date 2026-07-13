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
from frappe.utils import cint, flt

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

	_load_accounts()
	_create_default_settings()
	frappe.db.commit()


def _load_accounts():
    path = os.path.join(DATA_DIR, "accounts.csv")

    if not os.path.exists(path):
        return

    companies = frappe.get_all("Company", pluck="name")

    if not companies:
        return

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for company in companies:
        _import_accounts_for_company(company, rows)


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


def _import_accounts_for_company(company, rows):
	abbr = frappe.db.get_value("Company", company, "abbr")

	# Existing accounts lookup
	account_lookup = {
		d.account_name: d.name
		for d in frappe.get_all(
			"Account",
			filters={"company": company},
			fields=["name", "account_name"],
		)
	}

	pending = list(rows)

	while pending:
		imported = 0
		remaining = []

		for row in pending:
			account_name = (row.get("Account Name") or "").strip()

			if not account_name:
				continue

			parent_name = (row.get("Parent Account") or "").strip()
			root_type = (row.get("Root Type") or "").strip()
			account_type = (row.get("Account Type") or "").strip()

			is_group = cint(row.get("Is Group") or 0)

			tax_rate = flt(row.get("Tax Rate") or 0)

			# Already exists
			if account_name in account_lookup:
				imported += 1
				continue

			parent = None

			if parent_name:
				parent = account_lookup.get(parent_name)

				# Parent not imported yet
				if not parent:
					remaining.append(row)
					continue

			try:
				doc = frappe.new_doc("Account")

				doc.account_name = account_name
				doc.company = company
				doc.parent_account = parent
				doc.root_type = root_type
				doc.is_group = is_group

				if account_type:
					doc.account_type = account_type

				if frappe.get_meta("Account").has_field("tax_rate"):
					doc.tax_rate = tax_rate

				doc.insert(ignore_permissions=True)

				account_lookup[account_name] = doc.name

				imported += 1

			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Failed importing account '{account_name}' ({company})",
				)
				pass

		if not remaining:
			break

		if imported == 0:
			frappe.log_error(
				"\n".join(
					f"{r.get('Account Name')} --> {r.get('Parent Account')}"
					for r in remaining
				),
				f"Accounts still pending for company {company}",
			)
			break

		pending = remaining


def _create_default_settings():
	if frappe.db.exists("DocType", "FBR Invoice Settings") and not frappe.db.get_single_value(
		"FBR Invoice Settings", "integration_type"
	):
		settings = frappe.get_single("FBR Invoice Settings")
		settings.integration_type = "Sandbox"
		settings.enabled = 0
		settings.save(ignore_permissions=True)
