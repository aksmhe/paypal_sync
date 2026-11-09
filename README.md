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
11. [Versionen](#versionen)

Die Installation umfasst auch das [Update auf eine neue Version](#update-auf-eine-neue-version).

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

#### Vorher: Platzhalter ermitteln

In den Befehlen unten stehen Platzhalter in spitzen Klammern, z. B. `<site>`. Diese werden durch **eure** Werte ersetzt, **ohne** die spitzen Klammern.
Alle Befehle in dieser Tabelle **zeigen nur etwas an und ändern nichts**. Man führt sie auf dem Server als der Benutzer aus, der Docker bedienen darf.

| Platzhalter | Bedeutung | So findet man ihn heraus | Beispiel |
|---|---|---|---|
| `<backend-container>` | Name des Containers, in dem ERPNext läuft | `docker ps --format '{{.Names}}' \| grep backend` | `erpnext-backend-1` |
| `<site>` | Name der ERPNext-Site, meist die Internetadresse ohne `https://` | `docker exec <backend-container> ls sites`: Der Ordnername, der wie eine Adresse aussieht. `apps.json`, `apps.txt`, `assets` und `common_site_config.json` gehören **nicht** dazu. | `erp.example.com` |
| `<image>` und alter Tag | Image, mit dem ERPNext gerade läuft | `docker ps --format '{{.Names}}  {{.Image}}' \| grep backend`: Was **vor** dem Doppelpunkt steht, ist `<image>`, dahinter der **alte Tag**. | `erpnext-custom:16-banking` → `<image>` = `erpnext-custom`, alter Tag = `16-banking` |
| `<neuer-tag>` | frei wählbarer Name für das neue Image. Er sollte sich vom alten unterscheiden, damit der Rückweg offen bleibt. | selbst festlegen | `16-paypal` |
| `<projekt>` | Name des Docker-Compose-Projekts | `docker inspect <backend-container> --format '{{ index .Config.Labels "com.docker.compose.project" }}'` | `erpnext` |
| `<compose-datei>` | Datei, in der steht, welches Image die Container nutzen | `docker inspect <backend-container> --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'` | `/home/benutzer/erpnext.yaml` |
| `<frappe_docker-ordner>` | Ordner mit `apps.json` und dem Unterordner `images` | `find ~ -maxdepth 3 -name apps.json -path '*frappe_docker*'`: Der Ordner, in dem die gefundene Datei liegt. | `/home/benutzer/frappe_docker` |

> 💡 **Tipp:** Am besten alle Werte einmal ermitteln und in eine Notiz schreiben. Danach kann man die Befehle unten fertig zusammensetzen und Schritt für Schritt einfügen.

#### Installation Schritt für Schritt

1. **Sicherung** erstellen. Am Ende erscheint eine „Backup Summary“:
   ```bash
   docker exec <backend-container> bench --site <site> backup --with-files
   ```
2. Eine **Kopie der `apps.json`** anlegen und sie danach ansehen:
   ```bash
   cd <frappe_docker-ordner>
   cp apps.json apps.json.vor-paypal
   cat apps.json
   ```
   Dann diese Zeile als **letzten Eintrag** ergänzen, z. B. mit `nano apps.json`. Die vorhandenen Einträge bleiben stehen. Achtung: Zwischen den Einträgen steht ein Komma, nach dem letzten keins.
   ```json
   {"url": "https://github.com/aksmhe/paypal_sync", "branch": "main"}
   ```
3. Image **neu bauen**, im `<frappe_docker-ordner>`. Das dauert etwa 15–30 Minuten. Steht `FRAPPE_BRANCH` auf `version-16`, ist das für ERPNext 16 richtig. Für ERPNext 15 nimmt man `version-15`.
   ```bash
   docker build \
     --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
     --build-arg=FRAPPE_BRANCH=version-16 \
     --secret=id=apps_json,src=apps.json \
     --tag=<image>:<neuer-tag> \
     --file=images/layered/Containerfile .
   ```
4. Neues Image **prüfen**. Alle bisherigen Apps **und** `paypal_sync` müssen in der Liste stehen:
   ```bash
   docker run --rm <image>:<neuer-tag> ls apps
   ```
5. Eine **Kopie der Compose-Datei** anlegen und nachsehen, ob der alte Tag darin steht:
   ```bash
   cp <compose-datei> <compose-datei>.vor-paypal
   grep -n "<image>:<alter-tag>" <compose-datei>
   ```
   Dann auf den neuen Tag umstellen und neu starten. ERPNext ist dabei 1–2 Minuten nicht erreichbar:
   ```bash
   sed -i 's/<image>:<alter-tag>/<image>:<neuer-tag>/g' <compose-datei>
   docker compose -p <projekt> -f <compose-datei> up -d
   ```
6. App in die Site **installieren** und prüfen:
   ```bash
   docker exec <backend-container> bench --site <site> install-app paypal_sync
   docker exec <backend-container> bench --site <site> migrate
   docker exec <backend-container> bench --site <site> list-apps
   ```
   In der Liste muss jetzt `paypal_sync` stehen. Nach dem Neustart muss man sich im Browser neu bei ERPNext anmelden.

#### Rückweg, falls etwas nicht klappt

- **Vor Schritt 6:** einfach wieder auf das alte Image umstellen:
  ```bash
  sed -i 's/<image>:<neuer-tag>/<image>:<alter-tag>/g' <compose-datei>
  docker compose -p <projekt> -f <compose-datei> up -d
  ```
- **Nach Schritt 6:** die App zuerst wieder entfernen, dann wie oben zurückstellen:
  ```bash
  docker exec <backend-container> bench --site <site> uninstall-app paypal_sync --yes
  ```

#### Update auf eine neue Version

Wenn auf GitHub eine neue Version liegt (siehe [Versionen](#versionen)), wird das Image neu gebaut. `install-app` braucht man dabei **nicht** noch einmal, `migrate` genügt.

1. **Prüfen, ob GitHub die neue Version hat.** Es muss die erwartete Versionsnummer erscheinen:
   ```bash
   curl -s https://raw.githubusercontent.com/aksmhe/paypal_sync/main/paypal_sync/__init__.py
   ```
2. **Prüfen, welches Image gerade läuft.** Das ist ab jetzt der **alte Tag** und euer Rückweg:
   ```bash
   docker inspect <backend-container> --format '{{.Config.Image}}'
   ```
3. **Sicherung** erstellen:
   ```bash
   docker exec <backend-container> bench --site <site> backup --with-files
   ```
4. **Neu bauen, mit `--no-cache`** und einem **neuen Tag**, z. B. `16-paypal-011` für Version 0.1.1.
   Ohne `--no-cache` nimmt Docker die alte App aus dem Zwischenspeicher, weil sich die `apps.json` nicht geändert hat.
   ```bash
   cd <frappe_docker-ordner>
   docker build --no-cache \
     --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
     --build-arg=FRAPPE_BRANCH=version-16 \
     --secret=id=apps_json,src=apps.json \
     --tag=<image>:<neuer-tag> \
     --file=images/layered/Containerfile .
   ```
5. **Neues Image prüfen.** Erwartet werden drei Dinge: die neue Versionsnummer, im mittleren Teil `__init__.py` **und** `doctype`, und alle Apps.
   ```bash
   docker run --rm --entrypoint sh <image>:<neuer-tag> -c "cat apps/paypal_sync/paypal_sync/__init__.py; ls apps/paypal_sync/paypal_sync/paypal_sync/; ls apps"
   ```
6. **Umstellen und neu starten.** Nach dem `grep` muss überall der neue Tag stehen:
   ```bash
   sed -i 's/<image>:<alter-tag>$/<image>:<neuer-tag>/' <compose-datei>
   grep -n "image:" <compose-datei>
   docker compose -p <projekt> -f <compose-datei> up -d
   ```
7. **Datenbank anpassen und prüfen.** In der Liste muss `paypal_sync` mit der neuen Versionsnummer stehen:
   ```bash
   docker exec <backend-container> bench --site <site> migrate
   docker exec <backend-container> bench --site <site> list-apps
   ```

**Rückweg:** Bricht `migrate` mit einem Fehler ab, sofort auf das alte Image zurückstellen und `migrate` dort noch einmal laufen lassen. ERPNext ist dann wieder auf dem vorherigen Stand:
```bash
sed -i 's/<image>:<neuer-tag>/<image>:<alter-tag>/' <compose-datei>
docker compose -p <projekt> -f <compose-datei> up -d
docker exec <backend-container> bench --site <site> migrate
```

Das alte Image erst löschen, wenn die neue Version ein paar Tage sauber läuft: `docker image rm <image>:<alter-tag>`.

### Mit bench (klassische Installation)

```bash
bench get-app https://github.com/aksmhe/paypal_sync --branch main
bench --site <site> install-app paypal_sync
bench --site <site> migrate
```

Update: `bench update --apps paypal_sync` bzw. `cd apps/paypal_sync && git pull`, danach `bench --site <site> migrate`.

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

**Gut zu wissen:**

- **Ganz frische Zahlungen fehlen noch.** Die App fragt bewusst nur Umsätze ab, die **mindestens 3 Stunden** alt sind, weil PayPal sie erst dann sicher bereitstellt. Eine Testzahlung von vor 5 Minuten zeigt der Probelauf also noch nicht. Beim allerersten Mal kann es auch bis zum nächsten Tag dauern.
- **„Letztes Ergebnis“ ist anfangs unsichtbar.** ERPNext blendet leere, schreibgeschützte Felder aus. Der Abschnitt **Status** erscheint erst nach dem ersten echten Abruf, und die Seite muss man dafür **neu laden**.
- **„0 neu angelegt, 2 schon vorhanden“** ist in Ordnung: Die Umsätze hat ein früherer Lauf schon angelegt. Doppelt wird nichts angelegt.
- **„Abgerufen bis (UTC)“** zeigt die Zeit in UTC, also im Winter 1 Stunde und im Sommer 2 Stunden vor der deutschen Zeit, und dazu den Verzug von 3 Stunden.

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

| Einzahlung **privat** von einem Gesellschafter oder Inhaber (z. B. Testzahlung vom privaten PayPal-Konto) | **Privateinlage**, z. B. SKR03 1890 bzw. ein eigenes Einlagekonto je Gesellschafter |

**Warum Geldtransit?** Wenn Geld von der Bank zu PayPal fließt, sieht man das auf **beiden** Konten. Beide Seiten werden gegen 1360 gebucht. Das Konto 1360 geht danach wieder auf 0, und nichts wird doppelt gezählt.

### Schritt für Schritt: einen Umsatz ohne Rechnung buchen

Das gilt für Gebühren, Einlagen und Geldtransit, also für alles, wozu es keine Rechnung gibt.

1. **Bank Reconciliation Tool** (deutsch: *Bankabgleich-Werkzeug*) öffnen, direkt erreichbar unter `/app/bank-reconciliation-tool`.
2. Diese Felder ausfüllen:
   - **Unternehmen:** eure Firma
   - **Bankkonto:** das PayPal-Bankkonto
   - **Von / Bis:** der gewünschte Zeitraum
   - **Kontostand laut Bank:** das aktuelle PayPal-Guthaben

   Dann **Daten abrufen** klicken.
3. Beim Umsatz auf **Aktionen** klicken. Es öffnet sich das Fenster „Banktransaktion abgleichen“.
4. **Aktion:** *Beleg erstellen*. **Dokumententyp:** von *Zahlung* auf **Buchungssatz** umstellen.
5. **Zweites Konto:** das Gegenkonto, z. B. 4970, 1360 oder das Einlagekonto. **Parteityp** und **Partei** bleiben leer.
6. **Buchen** klicken. „Nicht zugewiesener Betrag“ muss danach **0,00** sein.

> 💡 Bei sehr kleinen Zahlungen, etwa einer Testzahlung von 0,05 €, behält PayPal den ganzen Betrag als Mindestgebühr. Zahlung und Gebühr heben sich dann auf.

---

## 7. Banking-Regeln (Vorschlag)

Unter **Bank Transaction Rule** kann man die wiederkehrenden Fälle automatisieren:

| Regelname | Art | Bedingung (Beschreibung) | Aktion |
|---|---|---|---|
| PayPal-Gebühren | Withdrawal | *Starts With* `PayPal-Gebühr` | Bank Entry → 4970 |
| PayPal Umbuchung Bank | Any | *Regex* `^PayPal \[T0[34]` | Bank Entry → 1360 |
| Hausbank an/von PayPal | Any | *Regex* `(?i)paypal` (nur passend zum Text eurer Bank) | Bank Entry → 1360 |

> Die letzte Regel vorher an echten Kontoauszügen prüfen. Bucht PayPal Einkäufe direkt per Lastschrift von der Bank ab, steht dort ebenfalls „PayPal“.

**So legt man die Gebühren-Regel an:**

| Feld | Eintrag |
|---|---|
| Rule Name | `PayPal-Gebühren` |
| Transaction Type | `Withdrawal` |
| Priority | z. B. `10` |
| Company | eure Firma |
| Description Rules | Check `Starts With`, Value `PayPal-Gebühr` |
| Classify As | `Bank Entry` |
| Bank Entry Type | `Single Account` |
| Account | `4970 - Nebenkosten des Geldverkehrs - …` |

Die Regel gilt für **alle** Bankkonten. Das schadet nicht, weil nur Umsätze aus dieser App mit „PayPal-Gebühr“ beginnen. Sie greift erst bei **neuen**, noch nicht abgeglichenen Umsätzen. Im Bankabgleich steht die Buchung dann schon als Vorschlag.

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
| Probelauf: *0 neue Buchungen, 0 übersprungen*, obwohl eine Zahlung da ist | Die Zahlung ist jünger als 3 Stunden, oder PayPal stellt sie noch nicht bereit | Später erneut versuchen. In PayPal prüfen, ob der Status „Abgeschlossen“ ist und nicht „Ausstehend“. |
| Im Abgleich: *Zahlungsweise: T0000 konnte nicht gefunden werden* | Version **0.1.0** schreibt den PayPal-Code in ein Feld, das ERPNext als Zahlungsweise übernimmt | Auf **0.1.1** aktualisieren. Bis dahin das Feld „Zahlungsweise“ im Abgleichsfenster leeren. |
| `migrate` bricht ab mit *TypeError: expected str, bytes or os.PathLike object, not NoneType* | Die Datei `paypal_sync/paypal_sync/__init__.py` fehlt im Repository | Zurück aufs alte Image (siehe [Update](#update-auf-eine-neue-version)), die Datei wieder anlegen und mit `--no-cache` neu bauen |
| Neues Image enthält noch die alte Version | Docker hat die App aus dem Zwischenspeicher genommen | Mit `--no-cache` neu bauen |

---

## 10. Sicherheit

- Das **Secret** wird in ERPNext **verschlüsselt** gespeichert (Feldtyp *Password*).
- Die PayPal-App sollte **nur** *Transaction Search* haben. Damit kann niemand über diesen Zugang Geld bewegen.
- Zugriff auf die Einstellungen haben nur die Rollen **System Manager** und **Accounts Manager**.
- Im Code stehen **keine** Zugangsdaten.

---

## Versionen

| Version | Datum | Änderung |
|---|---|---|
| 0.1.1 | 09.11.2026 | Der PayPal-Ereigniscode wird nicht mehr als „Art der Transaktion“ gespeichert. Sonst übernahm ERPNext ihn im Abgleich als Zahlungsweise und meldete *„Zahlungsweise: T0000 konnte nicht gefunden werden“*. Der Code steht weiterhin im Buchungstext. |
| 0.1.0 | 08.11.2026 | Erste Version |

---

## Lizenz

MIT, siehe [license.txt](license.txt) (englisches Original, rechtlich verbindlich).
Deutsche Übersetzung zum besseren Verständnis: [license_de.txt](license_de.txt)
