"""PayPal-Umsätze über die PayPal Transaction Search API holen
und in ERPNext als Bank Transactions anlegen.

Jeder PayPal-Umsatz wird eine Bank Transaction mit dem Bruttobetrag.
Eine PayPal-Gebühr wird eine eigene Bank Transaction ("PayPal-Gebühr ...").
So können Banking-Regeln Gebühren (4970) und Umbuchungen (1360) getrennt erkennen.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe import _
from frappe.utils import escape_html, flt, get_datetime, getdate, now_datetime
from frappe.utils.data import get_system_timezone

LIVE_URL = "https://api-m.paypal.com"
SANDBOX_URL = "https://api-m.sandbox.paypal.com"

CHUNK = timedelta(days=30)  # PayPal erlaubt höchstens 31 Tage pro Abfrage
API_DELAY = timedelta(hours=3)  # neue Umsätze erscheinen bei PayPal mit bis zu 3 Std. Verzug
OVERLAP = timedelta(days=3)  # jedes Mal etwas zurückgehen, doppelte werden übersprungen
TIMEOUT = 60
OK_STATUS = {"S", "V"}  # S = erfolgreich, V = storniert (Storno kommt als eigener Umsatz)
ROLES = ("System Manager", "Accounts Manager")

EVENT_LABELS = {
	"T00": "Zahlung",
	"T01": "Gebühr",
	"T02": "Währungsumrechnung",
	"T03": "Einzahlung vom Bankkonto",
	"T04": "Auszahlung auf Bankkonto",
	"T11": "Rückzahlung/Storno",
	"T12": "Korrektur",
}


# ---------------------------------------------------------------- PayPal API


def _base_url(settings):
	return SANDBOX_URL if settings.sandbox else LIVE_URL


def _get_token(settings):
	response = requests.post(
		f"{_base_url(settings)}/v1/oauth2/token",
		auth=(settings.client_id, settings.get_password("client_secret")),
		data={"grant_type": "client_credentials"},
		headers={"Accept": "application/json"},
		timeout=TIMEOUT,
	)
	if response.status_code != 200:
		frappe.throw(
			_("PayPal-Anmeldung fehlgeschlagen ({0}): {1}").format(response.status_code, response.text[:300])
		)
	return response.json()["access_token"]


def _fmt(dt):
	return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(settings, token, start, end):
	details, page = [], 1
	while True:
		response = requests.get(
			f"{_base_url(settings)}/v1/reporting/transactions",
			headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
			params={
				"start_date": _fmt(start),
				"end_date": _fmt(end),
				"fields": "transaction_info,payer_info",
				"balance_affecting_records_only": "Y",
				"page_size": 500,
				"page": page,
			},
			timeout=TIMEOUT,
		)
		if response.status_code != 200:
			frappe.throw(
				_("PayPal-Abfrage fehlgeschlagen ({0}): {1}").format(response.status_code, response.text[:500])
			)
		data = response.json()
		details.extend(data.get("transaction_details") or [])
		if page >= int(data.get("total_pages") or 1):
			return details
		page += 1


def _windows(start, end):
	while start < end:
		stop = min(start + CHUNK, end)
		yield start, stop
		start = stop


# ---------------------------------------------------------------- Umwandeln


def _local_date(paypal_timestamp):
	dt = datetime.strptime(paypal_timestamp, "%Y-%m-%dT%H:%M:%S%z")
	return dt.astimezone(ZoneInfo(get_system_timezone())).date()


def _party_name(payer_info):
	name = payer_info.get("payer_name") or {}
	full = name.get("alternate_full_name") or " ".join(
		filter(None, [name.get("given_name"), name.get("surname")])
	)
	return full or None


def _to_rows(details, currency, start_date):
	"""PayPal-Datensätze in Zeilen für Bank Transactions umwandeln."""
	rows, skipped = [], []
	for detail in details:
		info = detail.get("transaction_info") or {}
		payer = detail.get("payer_info") or {}
		tid = info.get("transaction_id")
		amount = info.get("transaction_amount") or {}
		if not tid:
			continue
		if amount.get("currency_code") != currency:
			# Fremdwährung: PayPal bucht die Umrechnung als eigenen Umsatz in EUR (T0200).
			skipped.append(f"{tid}: Währung {amount.get('currency_code')}")
			continue
		if info.get("transaction_status") not in OK_STATUS:
			skipped.append(f"{tid}: Status {info.get('transaction_status')}")
			continue

		date = _local_date(info["transaction_initiation_date"])
		if start_date and date < start_date:
			continue

		code = info.get("transaction_event_code") or ""
		label = EVENT_LABELS.get(code[:3], "Vorgang")
		name = _party_name(payer)
		invoice = info.get("invoice_id")
		description = " | ".join(
			filter(
				None,
				[
					f"PayPal [{code}] {label}",
					info.get("transaction_subject"),
					info.get("transaction_note"),
					name,
					payer.get("email_address"),
					f"Rechnung {invoice}" if invoice else None,
				],
			)
		)
		base = {
			"date": date,
			"currency": currency,
			"party_name": name,
			"code": code,
			"reference": info.get("paypal_reference_id") or tid,
		}

		gross = flt(amount.get("value"), 2)
		if gross:
			rows.append({**base, "transaction_id": tid, "amount": gross, "description": description})

		fee = flt((info.get("fee_amount") or {}).get("value"), 2)  # Gebühr ist negativ, Erstattung positiv
		if fee:
			fee_text = f"PayPal-Gebühr [{code}] zu {tid}" + (f" | {name}" if name else "")
			rows.append({**base, "transaction_id": f"{tid}-FEE", "amount": fee, "description": fee_text})
	return rows, skipped


# ---------------------------------------------------------------- ERPNext


def _settings():
	return frappe.get_single("PayPal Sync Settings")


def _check_settings(settings):
	missing = [f for f in ("client_id", "client_secret", "bank_account", "start_date") if not settings.get(f)]
	if missing:
		frappe.throw(_("In den PayPal Sync Settings fehlt: {0}").format(", ".join(missing)))


def _company_and_currency(settings):
	bank = frappe.db.get_value("Bank Account", settings.bank_account, ["company", "account"], as_dict=True)
	currency = frappe.db.get_value("Account", bank.account, "account_currency") or frappe.get_cached_value(
		"Company", bank.company, "default_currency"
	)
	return bank.company, currency


def _exists(transaction_id, bank_account):
	return frappe.db.exists("Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account})


def _insert(row, settings, company):
	amount = row["amount"]
	doc = frappe.new_doc("Bank Transaction")
	doc.update(
		{
			"date": row["date"],
			"bank_account": settings.bank_account,
			"company": company,
			"currency": row["currency"],
			"deposit": amount if amount > 0 else 0,
			"withdrawal": -amount if amount < 0 else 0,
			"description": row["description"],
			"reference_number": row["reference"],
			"transaction_id": row["transaction_id"],
			"bank_party_name": row["party_name"],
		}
	)
	doc.insert()
	doc.submit()
	return doc.name


def _utc_now():
	return datetime.now(timezone.utc).replace(microsecond=0)


def _sync(settings, start, end, dry_run=False):
	token = _get_token(settings)
	company, currency = _company_and_currency(settings)
	start_date = getdate(settings.start_date)
	result = {"created": 0, "existing": 0, "skipped": [], "preview": []}

	for window_start, window_end in _windows(start, end):
		rows, skipped = _to_rows(_fetch(settings, token, window_start, window_end), currency, start_date)
		result["skipped"] += skipped
		for row in rows:
			if _exists(row["transaction_id"], settings.bank_account):
				result["existing"] += 1
			elif dry_run:
				result["preview"].append(row)
			else:
				_insert(row, settings, company)
				result["created"] += 1
		if not dry_run:
			frappe.db.set_single_value(
				"PayPal Sync Settings", "last_sync_until", window_end.astimezone(timezone.utc).replace(tzinfo=None)
			)
			frappe.db.commit()
	return result


def _sync_range(settings):
	start = datetime.combine(getdate(settings.start_date), time.min, tzinfo=timezone.utc)
	if settings.last_sync_until:
		last = get_datetime(settings.last_sync_until).replace(tzinfo=timezone.utc)
		start = max(start, last - OVERLAP)
	return start, _utc_now() - API_DELAY


def run_job():
	settings = _settings()
	_check_settings(settings)
	try:
		start, end = _sync_range(settings)
		result = _sync(settings, start, end)
		message = _("{0} neu angelegt, {1} schon vorhanden, {2} übersprungen.").format(
			result["created"], result["existing"], len(result["skipped"])
		)
		if result["skipped"]:
			message += "\n" + "\n".join(result["skipped"][:20])
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="PayPal Sync fehlgeschlagen")
		message = _("Fehler beim Abruf, siehe Error Log „PayPal Sync fehlgeschlagen“.")
	frappe.db.set_single_value("PayPal Sync Settings", {"last_result": message, "last_sync_on": now_datetime()})
	frappe.db.commit()


def scheduled_sync():
	if frappe.db.get_single_value("PayPal Sync Settings", "enabled"):
		run_job()


# ---------------------------------------------------------------- Knöpfe im Formular


@frappe.whitelist()
def test_connection():
	frappe.only_for(ROLES)
	settings = _settings()
	token = _get_token(settings)
	end = _utc_now() - API_DELAY
	_fetch(settings, token, end - timedelta(days=1), end)
	return _("Verbindung zu PayPal klappt, die Umsatzsuche ist freigeschaltet.")


@frappe.whitelist()
def dry_run():
	"""Letzte 30 Tage abfragen und zeigen, was angelegt würde. Speichert nichts."""
	frappe.only_for(ROLES)
	settings = _settings()
	_check_settings(settings)
	end = _utc_now() - API_DELAY
	result = _sync(settings, end - CHUNK, end, dry_run=True)

	lines = [
		f"<p>{len(result['preview'])} neue Buchungen, {result['existing']} schon vorhanden, "
		f"{len(result['skipped'])} übersprungen.</p>",
		"<table class='table table-bordered table-sm'><tr><th>Datum</th><th>Betrag</th><th>Text</th></tr>",
	]
	for row in result["preview"][:50]:
		lines.append(
			f"<tr><td>{row['date']}</td><td style='text-align:right'>{row['amount']:.2f}</td>"
			f"<td>{escape_html(row['description'])}</td></tr>"
		)
	lines.append("</table>")
	if result["skipped"]:
		lines.append("<p>Übersprungen:<br>" + "<br>".join(escape_html(s) for s in result["skipped"][:20]) + "</p>")
	return "".join(lines)


@frappe.whitelist()
def sync_now():
	frappe.only_for(ROLES)
	_check_settings(_settings())
	frappe.enqueue(
		"paypal_sync.sync.run_job", queue="long", timeout=1800, job_id="paypal_sync", deduplicate=True
	)
	return _("Abruf gestartet. Das Ergebnis steht gleich unter „Letztes Ergebnis“.")
