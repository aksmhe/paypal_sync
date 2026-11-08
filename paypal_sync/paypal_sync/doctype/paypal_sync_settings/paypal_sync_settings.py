import frappe
from frappe import _
from frappe.model.document import Document


class PayPalSyncSettings(Document):
	def validate(self):
		if not self.enabled:
			return
		for field in ("client_id", "client_secret", "bank_account", "start_date"):
			if not self.get(field):
				frappe.throw(_("Bitte {0} ausfüllen.").format(_(self.meta.get_label(field))))

		account = frappe.db.get_value("Bank Account", self.bank_account, ["account", "is_company_account"], as_dict=True)
		if not account or not account.is_company_account or not account.account:
			frappe.throw(_("Das Bankkonto muss ein Firmenkonto mit Buchungskonto sein."))
