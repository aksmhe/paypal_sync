# PayPal Sync für ERPNext

Holt die Umsätze eines **PayPal-Geschäftskontos** automatisch über die offizielle PayPal-Schnittstelle (*Transaction Search API*) und legt sie in ERPNext als **Bank Transactions** an.
Danach werden sie wie Bankumsätze im **Bank Reconciliation Tool** abgeglichen. Den CSV-Export aus PayPal braucht man dafür nicht mehr.

- Läuft mit **ERPNext / Frappe 15 und 16**
- Kostenlos, keine Fremddienste: ERPNext spricht direkt mit PayPal
- Nur **lesender** Zugriff auf PayPal: Die App kann kein Geld bewegen

---

## Inhalt

1. [Was die App macht](#1-was-die-app-macht)
2. [Installation](#2-installation)
3. [PayPal-App anlegen](#3-paypal-app-anlegen)
4. [Einrichtung in ERPNext](#4-einrichtung-in-erpnext)
5. [Erster Abruf](#5-erster-abruf)
6. [Buchen und Abgleichen](#6-buchen-und-abgleichen)
7. [Banking-Regeln (Vorschlag)](#7-banking-regeln-vorschlag)
8. [Grenzen der PayPal-Schnittstelle](#8-grenzen-der-paypal-schnittstelle)
9. [Fehlerbehebung](#9-fehlerbehebung)
10. [Sicherheit](#10-sicherheit)

---

## 1. Was die App macht

- **Automatischer Abruf:** Alle **6 Stunden** fragt ERPNext bei PayPal nach neuen Umsätzen, wenn der Abruf in den Einstellungen eingeschaltet ist.
- **Ein Umsatz = eine Bank Transaction:** Jeder PayPal-Umsatz wird eine Bank Transaction mit dem **Bruttobetrag** auf dem PayPal-Bankkonto in ERPNext.
- **Gebühren getrennt:** Jede PayPal-Gebühr wird eine **eigene** Bank Transaction. Eine Banking-Regel kann sie so automatisch auf das Gebührenkonto buchen.
- **Keine Doppelten:** Jeder Umsatz wird über die PayPal-Transaktions-ID erkannt. Ein zweiter Abruf legt nichts doppelt an.
- **Lesbare Texte:** Die Beschreibung enthält den PayPal-Ereigniscode, Betreff, Name, E-Mail und Rechnungsnummer des Partners.

So sehen die Texte aus:

| Vorgang bei PayPal | Betrag | Text in ERPNext |
|---|---:|---|
| Kunde zahlt Rechnung | +100,00 | `PayPal [T0006] Zahlung \| Kunde GmbH \| kunde@example.com \| Rechnung ACC-SINV-2026-00001` |
| Gebühr dazu | −2,84 | `PayPal-Gebühr [T0006] zu 1AB23456CD789012E \| Kunde GmbH` |
| Einkauf mit PayPal | −50,00 | `PayPal [T0006] Zahlung \| Software-Abo \| Shop XY` |
| PayPal holt Geld vom Bankkonto | +50,00 | `PayPal [T0300] Einzahlung vom Bankkonto` |
| Auszahlung auf das Bankkonto | −200,00 | `PayPal [T0400] Auszahlung auf Bankkonto` |
| Rückzahlung | −20,00 | `PayPal [T1107] Rückzahlung/Storno \| …` |

---

## 2. Installation

### Mit frappe_docker (eigenes Image)

1. **Sicherung** erstellen:
   ```bash
   docker exec <backend-container> bench --site <site> backup --with-files
   ```
2. In der `apps.json` diese Zeile **ergänzen**. Die vorhandenen Einträge bleiben stehen:
   ```json
   {"url": "https://github.com/aksmhe/paypal_sync", "branch": "main"}
   ```
3. Image **neu bauen**, z. B.:
   ```bash
   docker build \
     --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
     --build-arg=FRAPPE_BRANCH=version-16 \
     --secret=id=apps_json,src=apps.json \
     --tag=<image>:<neuer-tag> \
     --file=images/layered/Containerfile .
   ```
4. Neues Image **prüfen**. `paypal_sync` muss in der Liste stehen:
   ```bash
   docker run --rm <image>:<neuer-tag> ls apps
   ```
5. In der Compose-Datei auf den neuen Tag umstellen und neu starten:
   ```bash
   docker compose -p <projekt> -f <compose-datei> up -d
   ```
6. App in die Site **installieren**:
   ```bash
   docker exec <backend-container> bench --site <site> install-app paypal_sync
   docker exec <backend-container> bench --site <site> migrate
   ```

### Mit bench (klassische Installation)

```bash
bench get-app https://github.com/aksmhe/paypal_sync --branch main
bench --site <site> install-app paypal_sync
bench --site <site> migrate
```

---

## 3. PayPal-App anlegen

Das muss jemand mit Zugang zum **PayPal-Geschäftskonto** machen.

1. Auf **[developer.paypal.com](https://developer.paypal.com)** mit dem PayPal-Geschäftskonto anmelden.
2. Oben den Schalter von **Sandbox** auf **Live** stellen. Das ist wichtig: Sandbox-Daten funktionieren nicht mit echten Umsätzen.
3. **Apps & Credentials** → **Create App**, Name z. B. „ERPNext“.
4. In der App unter **Features**:
   - ✅ **Transaction Search** einschalten
   - ❌ alle anderen Haken herausnehmen. Die App braucht nur Lesezugriff.
   - **Save Changes**
5. **Client-ID** und **Secret** notieren. Das Secret mit dem Kopier-Symbol kopieren, nicht durch Markieren mit der Maus.

> ⏳ **Wartezeit:** Bis PayPal die Freigabe für *Transaction Search* aktiviert, können **einige Stunden bis zu einem Tag** vergehen. Bis dahin meldet der Verbindungstest `NOT_AUTHORIZED`.

---

## 4. Einrichtung in ERPNext

### 4.1 Konten (Beispiel SKR03)

| Konto | Zweck | Kontoart | Ablage im Kontenplan |
|---|---|---|---|
| **1210 PayPal** | das PayPal-Guthaben | Bank | unter „Bank“ |
| **1360 Geldtransit** | Umbuchungen zwischen Bank und PayPal | – | unter „Sonstige Vermögensgegenstände“ |
| **4970 Nebenkosten des Geldverkehrs** | PayPal-Gebühren | – | meist schon vorhanden |

> Die Kontonummern sind ein Vorschlag. **Die steuerliche Einordnung bitte mit dem Steuerberater abstimmen.**

### 4.2 Bank und Bankkonto

1. **Bank** anlegen: Name `PayPal`.
2. **Bank Account** anlegen:
   - Kontoname: z. B. `Geschäftskonto`
   - Bank: `PayPal`
   - **Firmenkonto** (*Is Company Account*): ✅
   - Firma: eure Firma
   - Konto: `1210 PayPal`

### 4.3 PayPal Sync Settings

Suchleiste → **PayPal Sync Settings** öffnen:

| Feld | Eintrag |
|---|---|
| Automatischer Abruf aktiv | erst einmal **aus** lassen |
| Sandbox (Testumgebung) | **aus** |
| Client-ID | aus der PayPal-App (Live) |
| Secret | aus der PayPal-App (Live) |
| Bankkonto PayPal | das Bankkonto aus 4.2 |
| Umsätze ab | erster Tag, ab dem Umsätze übernommen werden sollen |

**Speichern.**

---

## 5. Erster Abruf

Auf der Seite **PayPal Sync Settings** gibt es drei Knöpfe:

1. **Verbindung testen.** Klappt es, steht dort: *„Verbindung zu PayPal klappt, die Umsatzsuche ist freigeschaltet.“*
2. **Probelauf (letzte 30 Tage).** Zeigt eine Tabelle mit den Umsätzen, die angelegt **würden**. Dabei wird **nichts gespeichert.**
3. **Jetzt abrufen.** Holt alle Umsätze ab „Umsätze ab“ und legt sie als Bank Transactions an. Das läuft im Hintergrund, das Ergebnis steht danach unter **„Letztes Ergebnis“**.

Passt alles, den Haken **„Automatischer Abruf aktiv“** setzen und speichern. Ab dann holt ERPNext alle 6 Stunden neue Umsätze.

---

## 6. Buchen und Abgleichen

Die abgerufenen Umsätze erscheinen im **Bank Reconciliation Tool**. Dort das Bankkonto `PayPal` wählen. Dann gilt:

| Umsatz | Buchen auf / Abgleichen mit |
|---|---|
| Kunde zahlt Rechnung | mit der **Ausgangsrechnung** bzw. Zahlung abgleichen |
| Einkauf über PayPal | mit der **Eingangsrechnung** bzw. Zahlung abgleichen |
| `PayPal-Gebühr …` | **4970** Nebenkosten des Geldverkehrs |
| `T03..` Einzahlung vom Bankkonto | **1360** Geldtransit |
| `T04..` Auszahlung auf Bankkonto | **1360** Geldtransit |
| Gegenstück auf dem **Hausbank-Konto** (Lastschrift/Gutschrift „PayPal“) | **1360** Geldtransit |

**Warum Geldtransit?** Wenn Geld von der Bank zu PayPal fließt, sieht man das auf **beiden** Konten. Beide Seiten werden gegen 1360 gebucht. Das Konto 1360 geht danach wieder auf 0, und nichts wird doppelt gezählt.

---

## 7. Banking-Regeln (Vorschlag)

Unter **Bank Transaction Rule** kann man die wiederkehrenden Fälle automatisieren:

| Regelname | Art | Bedingung (Beschreibung) | Aktion |
|---|---|---|---|
| PayPal-Gebühren | Withdrawal | *Starts With* `PayPal-Gebühr` | Bank Entry → 4970 |
| PayPal Umbuchung Bank | Any | *Regex* `^PayPal \[T0[34]` | Bank Entry → 1360 |
| Hausbank an/von PayPal | Any | *Regex* `(?i)paypal` (nur passend zum Text eurer Bank) | Bank Entry → 1360 |

> Die letzte Regel vorher an echten Kontoauszügen prüfen. Bucht PayPal Einkäufe direkt per Lastschrift von der Bank ab, steht dort ebenfalls „PayPal“.

---

## 8. Grenzen der PayPal-Schnittstelle

- **Verzug:** Neue Umsätze erscheinen bei PayPal erst nach **bis zu 3 Stunden**.
- **Zeitraum pro Abfrage:** höchstens **31 Tage**. Die App teilt längere Zeiträume selbst auf.
- **Wie weit zurück:** höchstens **3 Jahre**.
- **Fremdwährungen** (z. B. USD) werden übersprungen. PayPal bucht die Umrechnung in EUR als eigenen EUR-Umsatz (`T0200`), und den übernimmt die App.
- **Offene Zahlungen** (Status *Pending*) werden erst übernommen, wenn sie abgeschlossen sind.

---

## 9. Fehlerbehebung

| Meldung | Ursache | Lösung |
|---|---|---|
| `401 invalid_client` / *Client Authentication failed* | Client-ID oder Secret falsch, oder es sind Sandbox-Daten | Bei PayPal auf **Live** stellen, beide Werte neu kopieren und einfügen |
| `403 NOT_AUTHORIZED` | *Transaction Search* ist in der PayPal-App nicht aktiv oder noch nicht freigeschaltet | Haken prüfen, dann einige Stunden warten |
| `400 INVALID_REQUEST` | „Umsätze ab“ liegt mehr als 3 Jahre zurück | Datum anpassen |
| *Fehler beim Abruf, siehe Error Log* | anderer Fehler | **Error Log** öffnen, Eintrag „PayPal Sync fehlgeschlagen“ ansehen |
| Umsätze fehlen | Verzug bei PayPal oder offene Zahlung | Ein paar Stunden später erneut abrufen |

---

## 10. Sicherheit

- Das **Secret** wird in ERPNext **verschlüsselt** gespeichert (Feldtyp *Password*).
- Die PayPal-App sollte **nur** *Transaction Search* haben. Damit kann niemand über diesen Zugang Geld bewegen.
- Zugriff auf die Einstellungen haben nur die Rollen **System Manager** und **Accounts Manager**.
- Im Code stehen **keine** Zugangsdaten.

---

## Lizenz

MIT, siehe [license.txt](license.txt) (englisches Original, rechtlich verbindlich).
Deutsche Übersetzung zum besseren Verständnis: [license_de.txt](license_de.txt)
