# CI-Auswahl und offene Plattformprüfungen

06.11.2026 · Quellenauftrag `BP-CI-COST-GATES-FIX-20261106`,
ThreadDesk `188ce4729a62/8c6479474c2e`, Audit `188ce4729a62/1c96d22bdb05`.
Basis ist `6067fb0907bcdeaf91ef3ea6608b1468190a2536`.
Die Scope-Semantik ist gemäß Präzisierung `188ce4729a62/855841f2821b`
und unabhängigem Review `188ce4729a62/707741aacd48` korrigiert.

Verify begrenzt bestehende selbstgehostete Jobs mit `matrix.runner=kirabridge`
auf 20 Minuten; die Hosted-Mac-Jobs bleiben bei 10 Minuten. Die beiden
Paketworkflows behalten ihre Grenzen von 20 beziehungsweise 15 Minuten.
Die ursprüngliche Auswahländerung begrenzt den automatischen
Hosted-Mac-Fanout: Ein normaler Push startete bisher Intel- und ARM-Verify,
ein PR zusätzlich beide Mac-Paketprüfungen und ein `release/**`-Push zusätzlich
ARM-Paketsmoke. Wiederholte Ereignisse können weitere Läufe auslösen.
Zeitgrenzen und Concurrency sind kein Kontobudget oder harter Geldbetrag.

## Auswahl der Jobs

| Workflow und Ereignis | Ausgewählte bestehende Jobs |
| --- | --- |
| Verify: Push oder PR, unabhängig von einem Scope | Linux, Python 3.11 und 3.13 |
| Verify: manuell, Scope `linux`, fehlend oder unbekannt | Linux, Python 3.11 und 3.13 |
| Verify: manuell, Scope `all` einschließlich `All`/`ALL` nach Ausdrucksvergleich | Linux 3.11/3.13, Intel-Mac 3.11 und ARM-Mac 3.11 |
| macOS package acceptance: manuell | Intel- und ARM-Paketprüfung |
| Private release candidate: manuell | ARM-Macsmoke und bestehender Linux-Paketsmoke |
| Beide Paketworkflows: Push oder PR | Kein automatischer Lauf |

GitHub vergleicht Strings mit `==` ohne Beachtung der Großschreibung.
Der Ausdruck `inputs.scope == 'all'` wählt deshalb für ausgewertete Werte
`all`, `All` und `ALL` dieselbe volle Matrix, ausschließlich mit dem
`workflow_dispatch`-Eventguard. `unknown`, leerer oder fehlender Scope wählen
Linux. Das Choice-Menü bietet `linux` und `all` an. Ob die API abweichende
Choicewerte tatsächlich annimmt, bleibt unbekannt; die Fallauswertung weist
deren Ausdruckssemantik nach und behauptet keine API-Erreichbarkeit.

Die Paketworkflows behalten alle Jobs, Prüfschritte, Artefakte und Zeitgrenzen.
Ihre Concurrency ist pro Workflow und vollständigem Ref gebunden;
`cancel-in-progress: false` schützt laufende Lifecycle-/Rollbackprüfungen vor
einem späteren manuellen Start. Daraus folgt keine Zusage, dass jeder wartende
Start ausgeführt wird. Verify behält seine vorhandene Concurrency und Namen.

Ein manueller Start und Scope sind technische Auswahl. Sie ersetzen keine
tatsächliche Freigabe möglicher Kosten. Das private Repository und seine
eigenen Linux-Runner begründen keine Nullkostenzusage für Rechenzeit,
Speicher, Netzwerk oder Artefakte. Im Audit waren zwei registrierte Debian-X64-
Runner mit Label `kirabridge` online. Der Anzeigename `ubuntu-24.04` in der
Verify-Matrix ist kein Nachweis eines nativen Ubuntu-Kernels. Für das separate
Label `kirabridge-linux-smoke` war kein Runner registriert; der dokumentierte
ephemere Einzeljob-Runner bleibt eine Voraussetzung des Paketsmokes.

## Unveränderte Abnahmegrenzen

Die Auswahländerung besteht keine Plattformprüfung. Erforderlich bleiben
tatsächliche, an den jeweiligen integrierten Quellstand gebundene Ergebnisse:

- Verify mit gesperrten Abhängigkeiten, Ruff-/Formatprüfung, Tests und Build;
  Intel- und native ARM-Ergebnisse werden getrennt von Linux geführt.
- Doppelbuild und übereinstimmende Artefakthashes, der hashgebundene RC14-
  Upgradebeleg sowie isolierte launchd-Installation, Neustart, Rollback und
  bestätigte Bereinigung auf den jeweils beanspruchten Mac-Architekturen.
- Nativer Macsmoke und Linux-Paketsmoke. Ubuntu-Userspace im Container auf
  Debian weist keinen nativen Ubuntu-Kernel, Windows oder macOS nach.
- Bestehende unabhängige Reviews und tatsächlich geltende serverseitige
  Pflichtchecks. Das Lesen von Branchschutz, Rulesets und wirksamen
  `main`-Regeln ergab im Audit jeweils HTTP 403 mit dem Hinweis
  `Upgrade to GitHub Pro or make this repository public to enable this feature.`
  Die Regeln sind damit unbestätigt, nicht nachweislich abwesend.

Manuelle Verify-Jobnamen enthalten weiterhin den übergebenen Scope,
beispielsweise `[manual all]` oder `[manual linux]`. Sie dürfen nicht ungeprüft
als Ersatz automatischer
Required-Check-Kontexte gewertet werden. Es werden keine Anforderungen entfernt,
keine erfolgreichen Ersatzstatus erzeugt und keine fehlenden, abgebrochenen
oder übersprungenen Prüfungen als bestanden gemeldet.

Am historischen Ausgangspin `6067fb0` fehlte der explizite M4-Kontext noch;
Remote-Tests konnten dadurch übersprungen werden. Seit dem integrierten Stand
`0da9abbcc3fd60f7e0d1f7a89724d6c07bb83892` verwendet Verify getrennte frische
Prozesse für Legacy mit TD770 und Remote R2/R3 mit festem M4-Pin. Die
Remote-Lane verlangt vollständige, fehlerfreie Ergebnisse ohne Skips.
Lokale No-Skip-Belege bleiben getrennt von tatsächlich ausgeführten CI-
oder produktiven Remote-Abnahmen.

## Begrenzte Zeit- und Provenienzkorrektur

Folgeauftrag `188ce4729a62/5c22b7db3b49` betrifft nur die Verify-Zeitgrenze
und die frühe Logprovenienz. Run `42210252095`, Versuch 1 auf `0da9abb`,
wurde an der bisherigen 10-Minuten-Grenze abgebrochen. Beide Legacy-Lanes
zeigten zuletzt 82 Prozent; weitere Fortschrittszeilen erschienen ungefähr
2 beziehungsweise 7 Sekunden vor der Zeitgrenze. Es fehlen abschließende
Testzahlen und Exitstatus; Remote und Build wurden nicht ausgeführt.
Das belegt weder einen vollständigen PASS noch den Ausschluss eines Hängers.
Die unabhängige Verlaufsauswertung bleibt ein eigener Beleg.

Der Helper gibt nach tatsächlicher Quellen-, Import-, Abhängigkeits- und
Temp-Bindung unmittelbar vor pytest einen einzelnen kompakten JSON-Satz mit
`phase=PREFLIGHT` aus und leert stdout sofort. Er enthält Quellenpins und
Manifestdigests, Importpfade sowie die beobachteten Temp-/Device-/Freiplatz-
und Inodewerte. Die Ausgabe ist einschließlich Zeilenende auf 16 KiB UTF-8
begrenzt; ein zu großer Satz wird vor pytest abgelehnt, nicht abgeschnitten.
`acceptance=not_evaluated` und `pytest_started=false` vergeben keinen
Teststatus und keine zusätzliche Berechtigung. Vollständige Dateiinventare
und Abhängigkeitslisten bleiben im bestehenden Provenienzbericht.
Die abschließenden Quellen-, Import-, Exit-, JUnit- und No-Skip-Gates bleiben
erhalten. Auch bei frühem Logbeleg bleibt ein harter Abbruch unvollständig.

Die Regeln gelten für Ereignisse, die diese Workflowrevision auswählen.
Alte Referenzen, vorhandene PRs und bereits laufende Jobs können weiterhin
andere Definitionen verwenden. Dieser Quellenauftrag startet keine Actions,
keinen Push, Build, Release oder Installation und ändert keine Konto-,
Billing-, Server-, Runner- oder Schutzregeln.

Die ursprüngliche statische 28-Fall-Tabelle zum Commit `7adb9d2` ordnete
`workflow_dispatch`/`ALL` fälschlich Linux zu. Sie bleibt als fehlerhafter
historischer Beleg erhalten. Die getrennte Folgeauswertung verwendet die
dokumentierte GitHub-Semantik; bei dieser historischen Folgeauswertung
blieben die drei Workflowdateien bytegleich. Der jetzige Folgeauftrag
ändert ausschließlich die genannte Verify-Zeitgrenze.

Referenzen: [Workflowsyntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[Stringvergleiche](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#operators),
[Runner und Architekturen](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job),
[übersprungene Pflichtchecks](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
