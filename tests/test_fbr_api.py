import sys
import types
import unittest

from unittest.mock import patch

# Create a minimal frappe stub so unit tests can run outside a Frappe site.
frappe_stub = types.ModuleType("frappe")
frappe_stub.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)
frappe_stub.throw = lambda *args, **kwargs: (_ for _ in ()).throw(Exception(args[0] if args else "frappe.throw called"))
frappe_stub._ = lambda msg: msg
frappe_stub.get_single = lambda *args, **kwargs: types.SimpleNamespace(
    enabled=True,
    integration_type="Sandbox",
    sandbox_api_url="https://example.com",
    production_api_url="https://example.com",
    get_password=lambda *args, **kwargs: "token",
)
frappe_stub.logger = lambda *args, **kwargs: types.SimpleNamespace(info=lambda *args, **kwargs: None)
frappe_stub.utils = types.SimpleNamespace(now_datetime=lambda: "2025-04-21 00:00:00")
sys.modules["frappe"] = frappe_stub

# Stub requests and urllib3 so the module imports without the packages being installed.
requests_stub = types.ModuleType("requests")
requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
requests_stub.post = lambda *args, **kwargs: None
sys.modules["requests"] = requests_stub

urllib3_stub = types.ModuleType("urllib3")
urllib3_stub.disable_warnings = lambda *args, **kwargs: None
urllib3_stub.exceptions = types.SimpleNamespace(InsecureRequestWarning=Exception)
sys.modules["urllib3"] = urllib3_stub

from fbr_integration.fbr_integration.fbr_api import (
    _format_percent,
    _normalize_registration_type,
    build_payload,
    safe_float,
)


class DummyItem:
    def __init__(self, **attributes):
        self.__dict__.update(attributes)

    def get(self, name, default=None):
        return self.__dict__.get(name, default)


class DummyDoc:
    def __init__(self, **attributes):
        self.__dict__.update(attributes)

    def get(self, name, default=None):
        return self.__dict__.get(name, default)


class TestFbrApiHelpers(unittest.TestCase):
    def test_safe_float_works_for_values(self):
        self.assertEqual(safe_float("100"), 100.0)
        self.assertEqual(safe_float("-1"), 0)
        self.assertEqual(safe_float(None), 0)
        self.assertEqual(safe_float("abc"), 0)

    def test_format_percent_returns_percentage_string(self):
        self.assertEqual(_format_percent(18), "18.00%")
        self.assertEqual(_format_percent("5"), "5.00%")
        self.assertEqual(_format_percent("bad"), "")

    def test_normalize_registration_type_infers_from_tax_id(self):
        self.assertEqual(_normalize_registration_type(None, None), "Unregistered")
        self.assertEqual(_normalize_registration_type(None, "1234"), "Registered")
        self.assertEqual(_normalize_registration_type("Unregistered", "1234"), "Unregistered")


class TestBuildPayload(unittest.TestCase):
    @patch("fbr_integration.fbr_integration.fbr_api.build_address")
    @patch("fbr_integration.fbr_integration.fbr_api.frappe.db.get_value")
    def test_build_payload_missing_required_fields_throws(self, mock_db, mock_build_address):
        mock_build_address.return_value = ("", "")
        mock_db.return_value = None

        doc = DummyDoc(
            company="Test Company",
            company_tax_id="1234567",
            customer="Test Customer",
            tax_id="",
            posting_date="2025-04-21",
            name="INV-001",
            items=[],
        )

        with self.assertRaises(Exception) as context:
            build_payload(doc)

        self.assertIn("Missing required FBR field(s)", str(context.exception))

    @patch("fbr_integration.fbr_integration.fbr_api.build_address")
    @patch("fbr_integration.fbr_integration.fbr_api.frappe.db.get_value")
    def test_build_payload_requires_items(self, mock_db, mock_build_address):
        mock_build_address.return_value = ("Seller Address", "Sindh")
        mock_db.return_value = None

        doc = DummyDoc(
            company="Test Company",
            company_tax_id="1234567",
            customer="Test Customer",
            tax_id="1234567",
            posting_date="2025-04-21",
            name="INV-001",
            custom_scenario_id="SN001",
            items=[],
        )

        with self.assertRaises(Exception) as context:
            build_payload(doc)

        self.assertIn("must contain at least one item", str(context.exception))

    @patch("fbr_integration.fbr_integration.fbr_api.build_address")
    @patch("fbr_integration.fbr_integration.fbr_api.frappe.db.get_value")
    def test_build_payload_success(self, mock_db, mock_build_address):
        mock_build_address.return_value = ("Seller Address", "Sindh")
        # get_value is used for fallback buyer province and company province only
        mock_db.return_value = None

        invoice_item = DummyItem(
            item_name="Test Product",
            custom_fbr_uom="Numbers, pieces, units",
            custom_sales_tax_rate=18,
            custom_hs_code="0101.2100",
            qty=1,
            amount=1000,
            rate=1000,
            custom_sales_tax=180,
            custom_further_tax=120,
            custom_extra_tax=0,
            custom_sale_type="Goods at standard rate (default)",
            custom_sro_schedule_no="",
            custom_sro_item_sno="",
        )

        doc = DummyDoc(
            company="Test Company",
            company_tax_id="1234567",
            customer="Test Customer",
            tax_id="1234567",
            posting_date="2025-04-21",
            name="INV-001",
            custom_scenario_id="SN001",
            custom_tax_payer_type="Registered",
            items=[invoice_item],
        )

        payload = build_payload(doc)

        self.assertEqual(payload["invoiceType"], "Sale Invoice")
        self.assertEqual(payload["sellerProvince"], "Sindh")
        self.assertEqual(payload["buyerProvince"], "Sindh")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["rate"], "18.00%")
        self.assertEqual(payload["items"][0]["uoM"], "Numbers, pieces, units")
        self.assertEqual(payload["items"][0]["salesTaxApplicable"], 180.0)


if __name__ == "__main__":
    unittest.main()
