frappe.ui.form.on("PayPal Sync Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Verbindung testen"), () => {
			frappe.call({
				method: "paypal_sync.sync.test_connection",
				freeze: true,
				callback: (r) => frappe.msgprint(r.message),
			});
		});
		frm.add_custom_button(__("Probelauf (letzte 30 Tage)"), () => {
			frappe.call({
				method: "paypal_sync.sync.dry_run",
				freeze: true,
				freeze_message: __("Frage PayPal ab ..."),
				callback: (r) => frappe.msgprint({ title: __("Probelauf – nichts gespeichert"), message: r.message, wide: true }),
			});
		});
		frm.add_custom_button(__("Jetzt abrufen"), () => {
			frappe.confirm(__("PayPal-Umsätze jetzt abrufen und als Bank Transactions anlegen?"), () => {
				frappe.call({
					method: "paypal_sync.sync.sync_now",
					callback: (r) => frappe.show_alert({ message: r.message, indicator: "green" }),
				});
			});
		});
	},
});
