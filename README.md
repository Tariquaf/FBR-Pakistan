# FBR Integration (ERPNext / Frappe v15)

A ready-to-install Frappe app that connects ERPNext Sales Invoices to
Pakistan's **FBR IRIS Digital Invoicing** system, built from the
[FBR-Pakistan integration guide](https://github.com/ERPNEXT-PAKISTAN/FBR-Pakistan).

Instead of manually creating doctypes/fields/scripts through the UI (as the
original guide describes step-by-step), this package ships everything as
installable app code: doctypes, custom fields (as fixtures), server-side tax
calculation, the FBR API client, and the client-side "Send to FBR" button.

---

## Features

- **One-click "Send to FBR"** button on submitted Sales Invoices
- **Automatic tax breakup** (Sales Tax, Further Tax, Extra Tax, Other Tax 1/2)
  computed from each line's Item Tax Template, both live in the browser and
  again on save (server-side, authoritative)
- **Full FBR response stored** on the Sales Invoice (invoice no., status,
  status code, per-item statuses, raw response)
- **9 FBR master doctypes** shipped with the app: HS Code, Scenario ID,
  FBR UoM, SRO Item SNo, SRO Schedule No, Sale Type, Tax Payer Type,
  Invoice Type, Buyer Province
- **Master data auto-loaded on install** from the official FBR CSVs
  (HS Codes, scenarios, provinces, UoMs, etc. — no manual Data Import needed)
- **FBR Invoice Settings** — single doctype to toggle Sandbox/Production and
  store API URL + Security Token (stored as a Password field)
- Custom fields wired onto **Item**, **Customer**, **Sales Invoice**, and
  **Sales Invoice Item** with `fetch_from` so HS Code/UoM/Sale Type/Tax Payer
  Type/Buyer Province flow automatically from the Item and Customer masters

---

## Compatibility

- Frappe: v15.x
- ERPNext: v15.x
- Python: >= 3.10

---

## Installation

```bash
cd ~/frappe-bench

# Copy this app into apps/fbr_integration, e.g. by extracting the provided
# zip there, or by pushing it to your own git remote and using bench get-app.
# If you already have it locally:
cp -r /path/to/fbr_integration apps/fbr_integration

bench --site site1.local install-app fbr_integration
bench build
bench --site site1.local migrate
bench restart
```

If you'd rather host it on GitHub first:

```bash
cd apps/fbr_integration
git init
git add .
git commit -m "FBR Integration v1.0.0"
git remote add origin https://github.com/<your-org>/fbr_integration.git
git push -u origin main

# On the target bench:
bench get-app https://github.com/<your-org>/fbr_integration.git --branch main
bench --site site1.local install-app fbr_integration
```

### System dependency: wkhtmltopdf (patched)

ERPNext's PDF/print flow (used for printing the FBR invoice with its QR code)
needs the patched wkhtmltopdf build:

```bash
sudo apt install -y fontconfig xfonts-75dpi xfonts-base \
  libxrender1 libxext6 libfontconfig1 libfreetype6 libjpeg-turbo8

wget -O wkhtmltox.deb \
  https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_amd64.deb
sudo apt install -y ./wkhtmltox.deb
wkhtmltopdf --version

bench set-config -g wkhtmltopdf_path "$(which wkhtmltopdf)"
bench restart
```

Python dependencies (`requests`, `qrcode`, `pillow`, `python-barcode`) install
automatically from `pyproject.toml` when the app is installed.

---

## Configuration

1. Go to **FBR Invoice Settings** (single doctype).
2. Check **Enabled**.
3. Set **Integration Type** to `Sandbox` or `Production`.
4. Fill in the matching **API URL** and **Security Token** (token is stored
   as a Password field, not shown in the UI once saved).

---

## Usage

1. On the **Item** master, set HS Code / FBR UoM / Sale Type / SRO Schedule
   No / SRO Item SNo. On the **Customer** master, set Tax Payer Type / Buyer
   Province. These fetch automatically onto new Sales Invoices and their
   items.
2. Create and submit a Sales Invoice as usual — the FBR tax breakup fields
   recalculate on every save.
3. Click **Send to FBR** (visible once the invoice is submitted).
4. On success: the FBR Invoice No. and full response are stored on the
   invoice, and a confirmation dialog is shown.

---

## Reference data

Master data (HS Codes, Scenario IDs, Buyer Provinces, Sale Types, Tax Payer
Types, Invoice Types, FBR UoM, SRO Schedule/Item numbers) is imported
automatically the first time the app is installed, from the CSVs in
`fbr_integration/data/`. To refresh it later (e.g. after an FBR HS Code
update), re-run:

```bash
bench --site site1.local execute fbr_integration.setup.install.after_install
```

---

## Extending / customizing

- **Auto-send on submit instead of a button**: in `hooks.py`, uncomment the
  `on_submit` line under `doc_events["Sales Invoice"]` (and remove/ignore the
  client-side button if you don't want it visible).
- **Different Chart of Accounts tax names**: update the `tax_type` string
  matches in `fbr_integration/fbr_integration/tax_calculation.py` and
  `public/js/sales_invoice.js` to match your own GL tax account labels
  (defaults: General Sales Tax, Further Tax, Extra Tax, Other Tax 1, Other Tax 2).
- **Reports/Workspace/Print Format**: this package intentionally ships the
  data model + integration logic; add your own Report/Workspace/Print Format
  fixtures under `fbr_integration/fixtures/` if you need them exported the
  same way custom fields are.

---

## Troubleshooting

**UnicodeDecodeError (0x96 / 0x92, etc.)** — re-save any JS/PY file you edit
as UTF-8.

**"FBR Integration is disabled"** — check **Enabled** in FBR Invoice
Settings.

**"Please configure the API URL and Security Token..."** — the Sandbox or
Production URL/token fields are blank for the selected Integration Type.

---

## License / commercial use

MIT — see `LICENSE`. This project can be distributed commercially.

## Support

Open an issue with your Frappe/ERPNext version, the exact error from the
Error Log, and a screenshot if it's a UI issue.
