# Copyright (c) 2026, FBR Pakistan Integration and contributors
# For license information, please see license.txt
"""
Recomputes the FBR tax breakup (Sales Tax, Further Tax, Extra Tax,
Other Tax 1/2 and the Tax Inclusive Amount) on every Sales Invoice Item,
reading the rates from the Item Tax Template attached to each row.

This is the app equivalent of the "FBR Tax Calculation" Server Script
described in the FBR-Pakistan integration guide
(DocType Event: Sales Invoice, Before Save).

Map your own Chart of Accounts tax account names to the tax_type checks
below if your GL account labels differ from the defaults:
	General Sales Tax, Further Tax, Extra Tax, Other Tax 1, Other Tax 2
"""

import frappe


def calculate_fbr_taxes(doc, method=None):
	for item in doc.items:
		# Reset tax values
		item.custom_sales_tax_rate = 0
		item.custom_further_tax_rate = 0
		item.custom_extra_tax_rate = 0
		item.custom_other_tax_1_rate = 0
		item.custom_other_tax_2_rate = 0

		item.custom_sales_tax = 0
		item.custom_further_tax = 0
		item.custom_extra_tax = 0
		item.custom_other_tax_1 = 0
		item.custom_other_tax_2 = 0

		item.custom_total_tax_amount = 0
		item.custom_tax_inclusive_amount = item.amount or 0

		if not item.item_tax_template:
			continue

		tax_details = frappe.get_all(
			"Item Tax Template Detail",
			filters={"parent": item.item_tax_template},
			fields=["tax_type", "tax_rate"],
		)

		for tax in tax_details:
			tax_type = tax.tax_type or ""

			# Update the tax account names below if your Chart of Accounts differs
			if "General Sales Tax" in tax_type:
				item.custom_sales_tax_rate = tax.tax_rate or 0
			elif "Further Tax" in tax_type:
				item.custom_further_tax_rate = tax.tax_rate or 0
			elif "Extra Tax" in tax_type:
				item.custom_extra_tax_rate = tax.tax_rate or 0
			elif "Other Tax 1" in tax_type:
				item.custom_other_tax_1_rate = tax.tax_rate or 0
			elif "Other Tax 2" in tax_type:
				item.custom_other_tax_2_rate = tax.tax_rate or 0

		if not item.amount:
			continue

		item.custom_sales_tax = (item.amount * item.custom_sales_tax_rate) / 100
		item.custom_further_tax = (item.amount * item.custom_further_tax_rate) / 100
		item.custom_extra_tax = (item.amount * item.custom_extra_tax_rate) / 100
		item.custom_other_tax_1 = (item.amount * item.custom_other_tax_1_rate) / 100
		item.custom_other_tax_2 = (item.amount * item.custom_other_tax_2_rate) / 100

		item.custom_total_tax_amount = (
			item.custom_sales_tax
			+ item.custom_further_tax
			+ item.custom_extra_tax
			+ item.custom_other_tax_1
			+ item.custom_other_tax_2
		)

		item.custom_tax_inclusive_amount = item.amount + item.custom_total_tax_amount
