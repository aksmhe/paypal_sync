app_name = "paypal_sync"
app_title = "PayPal Sync"
app_publisher = "AffiKSys"
app_description = "PayPal-Umsätze per API als Bank Transactions"
app_email = "m.heide@affiksys.com"
app_license = "mit"
required_apps = ["erpnext"]

# Alle 6 Stunden neue PayPal-Umsätze holen (nur wenn in den Einstellungen aktiv)
scheduler_events = {
    "cron": {
        "15 */6 * * *": ["paypal_sync.sync.scheduled_sync"],
    },
}
