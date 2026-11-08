# PayPal Sync für ERPNext

Holt PayPal-Umsätze über die PayPal **Transaction Search API** und legt sie in ERPNext als **Bank Transactions** an.
Danach werden sie wie Bankumsätze im Bank Reconciliation Tool abgeglichen.

- Jeder Umsatz wird eine Bank Transaction mit dem Bruttobetrag. Der Text beginnt mit `PayPal [Ereigniscode]`.
- Jede PayPal-Gebühr wird eine eigene Bank Transaction. Der Text beginnt mit `PayPal-Gebühr`.
- Einzahlungen vom Bankkonto (`T03..`) und Auszahlungen aufs Bankkonto (`T04..`) sind am Code erkennbar.
- Doppelte Umsätze werden über die PayPal-Transaktions-ID erkannt und übersprungen.
- Fremdwährungsumsätze werden übersprungen. Die Umrechnung in EUR kommt von PayPal als eigener EUR-Umsatz (`T0200`).
- Offene Zahlungen (Status P) werden erst übernommen, wenn sie abgeschlossen sind.

## Einrichtung

1. PayPal-Entwicklerbereich (developer.paypal.com) → Apps & Credentials → **Live** → App anlegen.
   In der App unter Features **Transaction Search** einschalten. Bis die Freigabe wirkt, kann es einige Stunden dauern.
2. App installieren: Eintrag in `apps.json`, Image neu bauen, `bench --site <site> install-app paypal_sync`.
3. In ERPNext **PayPal Sync Settings** öffnen: Client-ID, Secret, Bankkonto und „Umsätze ab“ eintragen, speichern.
4. „Verbindung testen“ → „Probelauf (letzte 30 Tage)“ → „Jetzt abrufen“.
5. „Automatischer Abruf aktiv“ setzen: Danach wird alle 6 Stunden abgerufen.

## Grenzen der PayPal-API

- Höchstens 31 Tage pro Abfrage (die App teilt längere Zeiträume selbst auf).
- Neue Umsätze erscheinen mit bis zu 3 Stunden Verzug.
- Höchstens 3 Jahre zurück.
