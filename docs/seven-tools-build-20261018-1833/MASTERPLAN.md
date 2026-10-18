# Baufortschritt · seven-tools-build-20261018-1833

Maßgeblich: status.json; diese Ansicht wird daraus erzeugt. Keine zweite Ausführungswarteschlange.

Koordinator: /root. Originalauftrag und acht Pläne: SOURCE.md, unverändert und per SHA-256 gebunden.

| Paket | Verantwortlich | Status | Abhängigkeiten | Commit / PR / Grenze |
|---|---|---|---|---|
| TD-C01 | /root/threaddesk_m1 | main_and_bridge_operator_profile_integrated | G-01 | a99afa8b4ddfdc4396521bad11d6868b2069d9b0 |
| TD-C02 | /root/threaddesk_m1 | source_and_ci_checked | G-01 | 05403916e549e1060f839ccbaf36a5cb90413776 |
| TD-C03 | /root/threaddesk_m1 | open | TD-C01 |  |
| TD-C04 | /root/threaddesk_m1 | open | operator_server_scope |  |
| TD-D01 | /root/threaddesk_m1 | open |  |  |
| TD-R01 | /root/threaddesk_m1 | open |  |  |
| KB-C01 | /root | integrated_runtime_and_actual_chatgpt_checked | TD-C01, G-01 | 4d59e7081d62c5e4e9924e9e710382d8d8772c43 |
| KB-C02 | /root | open | TD-C02, KB-C01 |  |
| KB-C03 | /root | implemented_prior_current_runtime_to_verify |  |  |
| KB-C04 | /root | open | TG-C02 |  |
| KB-C05 | /root | open | KB-C02 |  |
| KB-D01 | /root | open |  |  |
| KB-R01 | /root | open |  |  |
| FP-C01 | /root/fourallpass_protected | source_and_ci_checked |  | 3fd6ed2 |
| FP-C02 | /root/fourallpass_protected | partial_fail_closed | FP-C01, KB-C02, TG-C01, secret_os_boundary | 3fd6ed2 |
| FP-C03 | /root/fourallpass_protected | open | FP-C02, TG-C02, KB-C04 |  |
| FP-D01 | /root/fourallpass_protected | source_and_browser_checked |  | fd5473203abc8fdc3fab4fff2e2331882d5f2dde |
| FP-R01 | /root/fourallpass_protected | in_progress |  |  |
| FP-V01 | /root/fourallpass_protected | open | FP-C02, FP-C03 |  |
| TG-C01 | /root/tollgate_control | bounded_source_and_ci_checked | G-01 | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| TG-C02 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C01 | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| TG-C03 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C01, G-02 | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| TG-C04 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C02, TG-C03 | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| TG-D01 | /root/tollgate_control | bounded_source_and_ci_checked |  | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| TG-R01 | /root/tollgate_control | bounded_source_and_ci_checked |  | c3a062d89cd3be449cb61976149ee5d455d67b8a |
| GH-C01 | /root | open | TD-C02, KB-C02 |  |
| GH-C02 | /root | open | TG-C02, KB-C04 |  |
| GH-C03 | /root | open | TG-C03, FP-C02 |  |
| GH-C04 | /root | open | GH-C01 |  |
| GH-C05 | /root | open | FP-C03, TG-C01 |  |
| GH-D01 | /root | open |  |  |
| GH-R01 | /root | open |  |  |
| AA-C01 | /root | implementation_in_progress | G-01, TD-C02, KB-C02 | 7e2758b |
| AA-C02 | /root | open | AA-C01 |  |
| AA-C03 | /root | open | operator_transport_scope |  |
| AA-D01 | /root | open |  |  |
| AA-R01 | /root | open |  |  |
| BD-C01 | /root | source_and_browser_checked |  | b875912e477523059671849f856a4b6dac8270e6 |
| BD-C02 | /root | open | BD-C01 |  |
| BD-C03 | /root | open | BD-C02 |  |
| BD-C04 | /root | open | TD-C02, KB-C02, KB-C05 |  |
| BD-D01 | /root | open | BD-C02, BD-C03, BD-C04 |  |
| BD-R01 | /root | open | BD-C01 |  |
