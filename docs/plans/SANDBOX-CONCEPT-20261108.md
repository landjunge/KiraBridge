# BP-SANDBOX-01 · Konzept Agenten-Sandbox auf dem VServer

Stand: 08.11.2026. Lane L1. **Nur Konzept.** Auf dem Server wurde nur gelesen.
Nichts installiert, nichts gestartet, nichts geschrieben. Keine Secrets erfasst.
Bezug: Gesamtplan 9.3 G5, 9.4 Nr. 3, 9.5 BP-SANDBOX-01; Bauplan Nachtrag N2.

## 1. Gemessene Hostressourcen (`netcup`, nur lesend)

| Größe | Messwert | Bewertung |
|---|---|---|
| CPU | 8 vCPU (`nproc` 8), "QEMU Virtual CPU 2.5+", Hypervisor KVM | Passt zur Angabe "etwa 8 Kerne". Geteilte vCPUs. |
| RAM | 15 GiB gesamt, 3,5 GiB belegt, 12 GiB verfügbar; Swap 4 GiB | Passt zu "16 GB". |
| Platte | `/dev/vda4` 314 GB, 18 GB belegt, 284 GB frei, ein einziges Dateisystem | Genug Platz. Kein Quota-Schutz: ein voller Sandbox-Bereich träfe auch Postgres. |
| Last | CPU-Pressure avg60 etwa 1,6 % | Host ist weitgehend leer. |
| Kernel | 6.12.101 (Debian 13), cgroup v2, Controller cpu/memory/io/pids aktiv | Gut für Limits. |
| User-Namespaces | an (`max_user_namespaces` 63768), `/dev/net/tun` vorhanden | Rootless-Container möglich. |
| AppArmor | geladen, 103 Profile | Zusatzschutz verfügbar. |
| **KVM** | **Nein.** Kein `/dev/kvm`, Flags `vmx`/`svm` fehlen (Gast ohne verschachtelte Virtualisierung) | Keine Windows-VM, keine Kata-/Firecracker-VM auf diesem Host. |
| Runtimes | Nur Docker 29.7.2 mit runc. Podman, gVisor (`runsc`), Sysbox fehlen. | Alles Weitere müsste installiert werden (Schritt 2). |

Ergebnis: Die Nutzerangabe 8 Kerne / 16 GB stimmt. Die Annahme "KVM nur
optional" wird zu **"KVM nicht vorhanden"**. Die Windows-VM entfällt auf
diesem Host, bis Netcup verschachtelte Virtualisierung freischaltet oder ein
zweiter Host kommt.

## 2. Heutige Lage, die die Wahl bestimmt

- Produktiv auf dem Host: 4AllPass-Compose (Caddy auf 80/443/8443, backend,
  postgres, redis, web), `threaddesk-server`, KiraBridge-Userdienst (Nutzer
  `daniel`), zwei GitHub-Runner (`actions.runner.landjunge-KiraBridge.*`,
  Nutzer `github-runner`, uid 1001).
- Das Dockernetz `4allpass_internal` (172.18.0.0/16) ist **nicht** `internal`,
  und Host-Dienste lauschen auf der Bridge-Adresse 172.18.0.1 (Ports 8766,
  8787) sowie auf 127.0.0.1 (8765, 8796, 41675). UFW lässt 8766/8787 nur von
  Caddy (172.18.0.5) zu. Das ist der Zugriffspfad, den eine Sandbox nie
  erreichen darf.
- `DOCKER-USER` ist leer. `FORWARD` steht auf DROP, ausgehend wird per
  MASQUERADE genattet.
- `daniel` ist in den Gruppen `docker` und `sudo`. **Docker-Gruppe heißt
  Root-Äquivalent.** Eine Sandbox darf deshalb weder unter `daniel` noch über
  den bestehenden Docker-Daemon laufen.
- Subuid-Bereiche vergeben: `daniel` 100000-165535, `github-runner`
  165536-231071. Für die Sandbox braucht es einen eigenen, dritten Bereich.
- Ausgehend ist der Host offen (GitHub per HTTPS erreichbar, Test lesend).

## 3. Optionen

Bewertung 1 (schlecht) bis 5 (gut), auf diesem Host (kein KVM, 8 vCPU).

| Option | Isolation | Aufwand | Berührt Produktiv-Docker | Passt zu G5 | Bemerkung |
|---|---|---|---|---|---|
| Rootless Podman, eigener Nutzer | 3 | 4 | nein | ja | Kein Root-Daemon, kein Socket, eigener subuid-Bereich, eigenes Netz. Schwäche: gemeinsamer Kernel. |
| Docker mit `userns-remap` | 3 | 2 | **ja** (selber Daemon) | bedingt | Root-Daemon und Socket bleiben. Eine Daemon-Änderung betrifft 4AllPass. Abgelehnt. |
| gVisor (`runsc`) | 4 | 3 | nein, wenn mit Podman | ja | Eigener User-Space-Kernel, stärkere Isolation. Kosten: Leistung, manche Syscalls fehlen (Build-Werkzeuge). Ohne KVM im Modus `systrap` nutzbar. Gute zweite Stufe. |
| Sysbox | 3 | 2 | ja (Daemon-Runtime) | bedingt | Gedacht für Docker-in-Docker. Braucht Root-Dienst, passt schlecht zu "kein Docker-Socket". Nicht nötig. |
| Separate VM (KVM/QEMU) | 5 | 1 | nein | ja | Beste Trennung, aber **ohne KVM unmöglich** (TCG-Emulation viel zu langsam). Erst mit zweitem Host. |

### Empfehlung

**Stufe 1: rootless Podman unter einem neuen Systemnutzer `sbx`**, ein
Container je Agentenlauf, mit systemd-Slice (cgroup v2), eigenem
Netzwerk-Namespace und AppArmor/seccomp-Standardprofil. Docker bleibt
unangetastet und für die Sandbox tabu.

**Stufe 2 (optional, nach Abnahme): gVisor als OCI-Runtime** in Podman für
Läufe mit nicht vertrauenswürdigem Code.

**Stufe 3 (nur bei Bedarf): eigene VM auf zweitem Host** oder Netcup-Wechsel
auf KVM-fähiges Produkt. Dort auch die optionale Windows-VM.

Begründung: kleinster Eingriff, kein zusätzlicher Root-Daemon, keine
Berührung der Produktiv-Container, rückbaubar durch Löschen eines Nutzers.
Ehrliche Grenze: Alle Container teilen den Host-Kernel. Ein Kernel-Exploit
wäre ein Ausbruch. Deshalb Stufe 2 und die Netz-/Secret-Regeln unten.

## 4. Netzwerkmodell

Ziel: Sandbox spricht **nur ausgehend** mit GitHub und Paketquellen. Keine
Verbindung zu Host, Docker-Netzen, Datenbank, Caddy oder Nachbar-Sandboxes.

1. Eigenes Netz für `sbx` (Podman-Netz `sbxnet`, z. B. 10.89.0.0/24), nie
   `4allpass_internal`, nie `--network host`.
2. Sandbox hat **keine** Direktroute ins Internet. Einziger Ausgang ist ein
   Allowlist-Proxy (Forward-Proxy auf der `sbxnet`-Gateway-Adresse, Nutzer
   `sbx-proxy`, ohne weitere Rechte). Erlaubte Ziele (HTTPS, nach
   Hostnamen): `github.com`, `api.github.com`, `codeload.github.com`,
   `objects.githubusercontent.com`, `registry.npmjs.org`, `pypi.org`,
   `files.pythonhosted.org`, `deb.debian.org`, `crates.io`/`static.crates.io`,
   `proxy.golang.org`. Alles andere: Ablehnung und Log.
3. nftables-Regeln (neue eigene Tabelle `inet sbx`, bestehende UFW/Docker-
   Regeln unberührt):
   - Von `sbxnet`: erlaubt nur TCP 3128 zum Proxy und DNS zum Proxy-Resolver.
   - Von `sbxnet` verboten: 172.16.0.0/12 (Docker), 127.0.0.0/8,
     eigene öffentliche Hostadresse, Metadaten-/Linklokal 169.254.0.0/16,
     alle Hostports, IPv6 komplett.
   - Eingehend zur Sandbox: nichts. Kein veröffentlichter Port.
4. Wegen `INPUT DROP` und UFW wird für `sbxnet` bewusst nichts am Host
   geöffnet. Die Host-Dienste auf 172.18.0.1 und 127.0.0.1 sind aus `sbxnet`
   nicht erreichbar (Abnahmetest unten).
5. Ausgehende Mengen begrenzen (Rate und Tagesvolumen am Proxy), gegen
   Datenabfluss und Miner.

## 5. Ressourcenbudget je Sandbox

Host 8 vCPU / 15 GiB, produktiv belegt etwa 3,5 GiB. Reserve für Produktion:
**2 vCPU, 6 GiB RAM, 60 GB Platte bleiben unangetastet.**

| Ressource | je Sandbox | Gesamtdeckel `sbx.slice` |
|---|---|---|
| CPU | 2 vCPU (`CPUQuota=200%`), `CPUWeight=50` (niedriger als Produktion) | 4 vCPU |
| RAM | 3 GiB hart (`MemoryMax`), `MemorySwapMax=0` | 8 GiB |
| Prozesse | `TasksMax=512` | 1024 |
| Platte | 30 GB, eigenes Verzeichnis unter `/srv/sbx` mit XFS/ext4-Project-Quota oder eigenem Loop-Image | 90 GB |
| I/O | `IOWeight=20`, Lese-/Schreibbandbreite je 50 MB/s | – |
| Laufzeit | 4 h je Lauf, danach hartes Ende | – |
| Parallel | höchstens 2 Sandboxes | – |
| Dateien | `LimitNOFILE=4096`, keine Core-Dumps | – |

Container: nicht privilegiert, `--cap-drop=ALL`, `no-new-privileges`,
Root-Dateisystem schreibgeschützt plus `tmpfs`, keine `--device`, kein
`/dev/kvm`, keine Host-Mounts außer dem eigenen Arbeitsverzeichnis des
Laufs. Postgres hat keinen veröffentlichten Hostport; das bleibt so.

## 6. Fluss von Branches und Artefakten

```
Agent (Sandbox) --git push--> GitHub  agent/<lauf-id>/<thema>   (nur diese Namensräume)
GitHub --Pull Request--> Mensch prüft --> Merge
iMac: git fetch, Abgleich, macOS-Build und Test
Sandbox <-- git pull (nur lesen, nach Merge oder Branch-Freigabe)
```

- Sandbox klont per HTTPS/SSH nur das eigene Repo und arbeitet im Container.
  **Keine zweite Codebasis**, kein dauerhaftes Server-Repo außerhalb der
  Sandbox.
- Pushes nur auf `agent/*`. Branch-Schutz auf `main`: kein Push, kein
  Force-Push. Merge nur durch den Menschen (G5, menschliche Freigabe).
- Artefakte (Logs, Testberichte, Pakete) kommen als Dateien in ein
  Ausgabeverzeichnis `/srv/sbx/<lauf-id>/out`, werden mit SHA256 aufgelistet
  und vom iMac per `scp`/`rsync` gezogen oder als PR-Anhang übergeben.
  Umgekehrt nie Dateien vom Server in Produktion kopieren.
- Der iMac baut die macOS-Version aus dem Branch-Stand, nicht aus
  Sandbox-Binärdateien.
- Windows-Build: weiter über die vorhandenen Windows-Wege, nicht über die
  Sandbox (kein KVM).

## 7. Umgang mit Secrets

- **Keine Produktiv-Secrets in der Sandbox.** Weder 4AllPass-`.env`, noch
  Datenbank-Zugang, noch Runner-Token, noch Schlüssel von `daniel` oder
  `root`. `sbx` hat kein Lesen auf deren Pfade (eigener Nutzer, Modus 0700
  prüfen, Abnahme).
- GitHub-Zugang je Sandbox/Lauf:
  - bevorzugt ein **Fine-grained Token** auf genau ein Repo, Rechte nur
    `Contents: read/write` und `Pull requests: write`, **Ablauf höchstens 7
    Tage**, kein Zugriff auf Actions, Secrets, Administration, Workflows;
  - oder ein **Deploy-Key** je Repo, nur Schreibrecht, wenn Push nötig ist;
    sonst nur lesend.
  - Ein Token gilt für eine Sandbox. Nie wiederverwendet, nie im Image.
- Übergabe: Token liegt als `podman secret` bzw. als `tmpfs`-Datei, nur im
  Speicher, wird nach dem Lauf vernichtet und bei GitHub widerrufen.
- Modell-API-Schlüssel: eigene Schlüssel mit Ausgabenlimit, getrennt von
  allen Produktivschlüsseln. Budget wird über TollGate gedeckelt (Gesamtplan).
- Branch-Schutz verhindert, dass ein gestohlenes Token Produktion verändert.
  Workflow-Dateien (`.github/workflows/**`) sind per Codeowner/Regel für
  Agenten gesperrt, sonst wäre ein Push ein Weg auf die Runner (Abschnitt 8).
- Logs durchlaufen vor der Ablage einen Secret-Scan.

## 8. Risiken für CI-Runner und 4AllPass-Datenbank

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| Zwei GitHub-Runner laufen auf demselben Host (`github-runner`) und führen PR-Code aus | Ein Agent, der Workflows ändert oder Code in einem Runner-Lauf unterbringt, hätte Hostzugriff | Workflow-Dateien für Agenten sperren; Agenten-PRs laufen nicht auf diesen Runnern (kein `pull_request` aus Agenten-Branches ohne menschliche Freigabe); Runner-Labels trennen |
| Runner und Sandbox teilen CPU/RAM | CI wird langsam oder bricht ab | `sbx.slice` mit niedrigem Gewicht und hartem Deckel; Runner-Last vorher messen |
| Platte ist ein einziges Dateisystem | Voller Sandbox-Bereich stoppt Postgres und Runner | Quota je Lauf, Gesamtdeckel 90 GB, Alarm bei 70 % Belegung |
| Docker-Gruppe = Root | Wer `daniel` hat, hat alles | Sandbox nie unter `daniel`; `sbx` nicht in `docker`/`sudo` |
| Netz zum Host (172.18.0.1, 127.0.0.1) | Zugriff auf interne API-Ports (8766, 8787, 8765, 8796) | Abschnitt 4: eigenes Netz, Sperre, Abnahmetest |
| 4AllPass-Postgres | Datenabfluss/-zerstörung, falls Sandbox das Dockernetz erreicht | Postgres ohne Hostport (so heute); `sbxnet` kann `4allpass_internal` nicht erreichen; Sandbox hat keine DB-Zugangsdaten; vor Start frische Sicherung prüfen |
| Kernel-Ausbruch (gemeinsamer Kernel) | Voller Hostzugriff | Rootless, Capabilities weg, seccomp/AppArmor; Stufe 2 gVisor; Kernel-Updates zeitnah |
| Fork-Bombe, Speicher-Fresser | Host-OOM trifft Produktion | `MemoryMax`, `TasksMax`, `MemorySwapMax=0`; OOM-Reihenfolge so, dass Sandbox zuerst stirbt (`OOMScoreAdjust`) |
| Miner/Datenabfluss über erlaubte Hosts | Missbrauch von Rechenzeit und Bandbreite | Proxy-Allowlist, Rate-Limit, Laufzeitlimit |

## 9. Einrichtungsplan (nach Beauftragung; jetzt nichts davon ausführen)

Nur die Ownerin (Claude-Organisator, N2) schreibt auf den Server. Vor jedem
Schritt Sicherung des Zustands (UFW-/nft-Export, `dpkg -l`, Liste der
Dienste). Jeder Schritt einzeln, mit Rückweg.

| Nr. | Schritt | Rückweg | Abnahme |
|---|---|---|---|
| 0 | Freigabe des Nutzers einholen; Sicherung Postgres + Konfig prüfen | – | Sicherung lesbar, Zeitstempel heute |
| 1 | Nutzer `sbx` anlegen (ohne Login-Shell-Rechte, ohne `docker`/`sudo`), eigener subuid-Bereich, `loginctl enable-linger` | `userdel -r sbx`, subuid-Zeile entfernen | `id sbx` ohne Zusatzgruppen; `docker ps` als `sbx` verweigert |
| 2 | `podman` aus Debian-Paketquelle installieren (keine Daemon-Änderung an Docker) | `apt remove podman` | `docker info` unverändert; 4AllPass-Container laufen (Uptime unverändert) |
| 3 | `sbx.slice` mit Deckeln aus Abschnitt 5 | Slice-Datei löschen, `daemon-reload` | `systemctl show sbx.slice` zeigt Limits; Produktion unbeeinflusst |
| 4 | Plattenbereich `/srv/sbx` mit Quota | Verzeichnis entfernen | Schreibtest über Quota scheitert |
| 5 | Netz `sbxnet` + eigene nft-Tabelle `inet sbx` + Allowlist-Proxy | `nft delete table inet sbx`, Netz und Proxy entfernen | Testkatalog Netz (unten) komplett bestanden; UFW/Docker-Regeln diff-gleich |
| 6 | Basis-Image bauen (Debian slim, Git, Build-Werkzeuge, ohne Secrets) | Image löschen | Image enthält keine Tokens (Scan) |
| 7 | Probelauf mit Dummy-Repo und Wegwerf-Token (7 Tage, ein Repo) | Token widerrufen, Container löschen | Branch `agent/test/...` erscheint auf GitHub; `main` unberührt |
| 8 | Ausbruchs- und Lasttest (Fork-Bombe, Speicher, Platte, Netzscans) | Lauf abbrechen | Produktion meldet keinen Fehler; Sandbox wird hart beendet |
| 9 | Freigabe für echte Läufe; Betriebsnotiz und Inventar (`ops/netcup.json`, BP-OPS-01) | Läufe sperren (Slice auf 0) | Menschliche Freigabe im Board |
| 10 | Optional gVisor (Stufe 2) | Runtime entfernen | Gleicher Testkatalog besteht mit `runsc` |

**Gesamter Rückweg:** Sandbox-Container stoppen, `nft delete table inet sbx`,
Proxy und Netz entfernen, `userdel -r sbx`, `apt remove podman`, `/srv/sbx`
löschen, GitHub-Tokens widerrufen. Produktion bleibt unberührt, weil keiner
der Schritte Docker, Caddy, Postgres, ThreadDesk, KiraBridge oder die Runner
verändert.

### Testkatalog Netz und Isolation (Abnahmekriterien)

Aus der Sandbox heraus, alle müssen scheitern:
1. Verbindung zu 172.18.0.1:8766/8787, 127.0.0.1:*, Host-IP:*.
2. Verbindung zu 172.18.0.0/16 (Postgres 5432, Redis 6379, Backend 8000).
3. Verbindung zu `4allpass_internal`-Containern per Namen oder IP.
4. Zugriff auf `/var/run/docker.sock`, `/srv`, `/home/daniel`, `/root`, `/opt`.
5. IPv6-Verbindungen. DNS an fremde Resolver. Nicht gelistete Hosts.

Alle müssen gelingen: `git clone/push` auf `agent/*` per Token, `pip`/`npm`
von der Allowlist.

Weitere Kriterien:
- `ps`/`systemctl` zeigen: Caddy, Postgres, ThreadDesk, KiraBridge-Dienst und
  beide Runner sind während und nach den Tests ununterbrochen aktiv.
- CPU-Pressure und RAM der Produktion bleiben unter Last der Sandbox im
  üblichen Bereich (Ausgangswert avg60 etwa 1,6 %).
- Kein Secret im Image, in den Logs, in der Umgebung der Sandbox.
- `main` ist per Branch-Schutz nicht beschreibbar mit dem Sandbox-Token.

## 10. Offene Punkte für Entscheidung

1. Zustimmung zu Stufe 1 (rootless Podman) als Start.
2. Soll Netcup auf ein KVM-fähiges Produkt oder ein zweiter Host kommen
   (Voraussetzung für Windows-VM und Stufe 3)?
3. Welche Repos dürfen Agenten bekommen (Fine-grained Token je Repo)?
4. Agenten-PRs nicht auf den vorhandenen Runnern: eigene Regel in Actions
   festlegen (Owner).
