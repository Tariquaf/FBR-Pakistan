import importlib
import sys
import types


class DummyDoc:
    def __init__(self, doctype):
        self.doctype = doctype
        self.values = {}

    def update(self, values):
        self.values.update(values)
        return self

    def insert(self, *args, **kwargs):
        self.inserted = True
        return self


def load_install_module():
    created = []

    def new_doc(doctype):
        doc = DummyDoc(doctype)
        created.append(doc)
        return doc

    frappe_stub = types.ModuleType("frappe")
    frappe_stub.db = types.SimpleNamespace(exists=lambda *args, **kwargs: False)
    frappe_stub.new_doc = new_doc
    frappe_stub.log_error = lambda *args, **kwargs: None
    frappe_stub.get_single = lambda *args, **kwargs: types.SimpleNamespace(save=lambda *a, **k: None)
    frappe_stub.get_single_value = lambda *args, **kwargs: None

    sys.modules["frappe"] = frappe_stub
    sys.modules.pop("fbr_integration.fbr_integration.setup.install", None)

    module = importlib.import_module("fbr_integration.fbr_integration.setup.install")
    return module, created


def test_parent_accounts_are_created_before_children():
    install, created = load_install_module()

    accounts = [
        {"account_name": "Current Liabilities", "is_group": 1},
        {"account_name": "Duties and Taxes", "parent_account": "Current Liabilities", "is_group": 1},
        {"account_name": "Sales Tax", "parent_account": "Duties and Taxes", "is_group": 0},
    ]

    install._create_accounts_from_data(accounts)

    assert [doc.values["account_name"] for doc in created] == [
        "Current Liabilities",
        "Duties and Taxes",
        "Sales Tax",
    ]
