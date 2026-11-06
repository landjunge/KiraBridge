# CI-Auswahl und offene Plattformprüfungen

06.11.2026 · Quellenauftrag `BP-CI-COST-GATES-FIX-20261106`,
ThreadDesk `188ce4729a62/8c6479474c2e`, Audit `188ce4729a62/1c96d22bdb05`.
Basis ist `6067fb0907bcdeaf91ef3ea6608b1468190a2536`.
Die Scope-Semantik ist gemäß Präzisierung `188ce4729a62/855841f2821b`
und unabhängigem Review `188ce4729a62/707741aacd48` korrigiert.

Die drei Workflows begrenzen bereits die Laufzeit ihrer einzelnen Jobs auf
10, 20 beziehungsweise 15 Minuten. Die Änderung begrenzt den automatischen
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

Der Remote-CI-Kontext ist getrennt: Verify setzt weiterhin keinen
`KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE`. Ohne expliziten M4-Snapshot wird
`tests/test_remote_relay.py` übersprungen. Die separat mit explizitem M4-Pin
durchgeführten lokalen No-Skip-Integrationsprüfungen sind eigene Belege;
diese Workflowänderung ersetzt weder deren Quellenbindung noch fehlende CI-
oder produktive Remote-Abnahme.

Die Regeln gelten für Ereignisse, die diese Workflowrevision auswählen.
Alte Referenzen, vorhandene PRs und bereits laufende Jobs können weiterhin
andere Definitionen verwenden. Dieser Quellenauftrag startet keine Actions,
keinen Push, Build, Release oder Installation und ändert keine Konto-,
Billing-, Server-, Runner- oder Schutzregeln.

Die ursprüngliche statische 28-Fall-Tabelle zum Commit `7adb9d2` ordnete
`workflow_dispatch`/`ALL` fälschlich Linux zu. Sie bleibt als fehlerhafter
historischer Beleg erhalten. Die getrennte Folgeauswertung verwendet die
dokumentierte GitHub-Semantik; die drei Workflowdateien bleiben bytegleich.

Referenzen: [Workflowsyntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[Stringvergleiche](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#operators),
[Runner und Architekturen](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job),
[übersprungene Pflichtchecks](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
