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
import json
import os

import frappe

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ACCOUNTS_DATA_FILE = "accounts.json"

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

	_create_accounts_from_data_file()
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


def _create_accounts_from_data_file():
	path = os.path.join(DATA_DIR, ACCOUNTS_DATA_FILE)
	if not os.path.exists(path):
		return

	try:
		with open(path, encoding="utf-8-sig") as f:
			payload = json.load(f)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"fbr_integration.install: failed to load {ACCOUNTS_DATA_FILE}")
		return

	if isinstance(payload, dict):
		accounts = payload.get("accounts") or payload.get("data")
	else:
		accounts = payload

	if not isinstance(accounts, list):
		return

	_create_accounts_from_data(accounts)


def _create_accounts_from_data(accounts):
	if not accounts:
		return

	account_docs = []
	for raw_account in accounts:
		if not isinstance(raw_account, dict):
			continue

		values = _normalize_account_data(raw_account)
		if not values.get("account_name"):
			continue

		account_docs.append(values)

	groups = [values for values in account_docs if values.get("is_group")]
	children = [values for values in account_docs if not values.get("is_group")]

	for values in groups + children:
		try:
			if frappe.db.exists("Account", {"account_name": values["account_name"]}):
				continue

			doc = frappe.new_doc("Account")
			doc.update(values)
			doc.insert(ignore_permissions=True, ignore_mandatory=True)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"fbr_integration.install: Account import failed for {values.get('account_name')}",
			)


def _normalize_account_data(raw_account):
	mapping = {
		"account_name": ["account_name", "Account Name", "name"],
		"parent_account": ["parent_account", "Parent Account", "parent"],
		"root_type": ["root_type", "Root Type"],
		"account_type": ["account_type", "Account Type"],
		"tax_rate": ["tax_rate", "Tax Rate"],
		"is_group": ["is_group", "Is Group"],
	}

	values = {}
	for target, aliases in mapping.items():
		for alias in aliases:
			if alias in raw_account:
				value = raw_account.get(alias)
				break
		else:
			continue

		if target == "is_group":
			if isinstance(value, str):
				normalized_value = value.strip().lower()
				if normalized_value in {"1", "true", "yes", "y"}:
					value = 1
				elif normalized_value in {"0", "false", "no", "n", ""}:
					value = 0
				else:
					value = 1 if normalized_value else 0
			else:
				value = int(value) if value is not None else 0

		values[target] = value

	return values


def _create_default_settings():
	if frappe.db.exists("DocType", "FBR Invoice Settings") and not frappe.db.get_single_value(
		"FBR Invoice Settings", "integration_type"
	):
		settings = frappe.get_single("FBR Invoice Settings")
		settings.integration_type = "Sandbox"
		settings.enabled = 0
		settings.save(ignore_permissions=True)
