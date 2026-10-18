# Baufortschritt · seven-tools-build-20261018-1833

Maßgeblich: status.json; diese Ansicht wird daraus erzeugt. Keine zweite Ausführungswarteschlange.

Koordinator: /root. Originalauftrag und acht Pläne: SOURCE.md, unverändert und per SHA-256 gebunden.

| Paket | Verantwortlich | Status | Abhängigkeiten | Commit / PR / Grenze |
|---|---|---|---|---|
| TD-C01 | /root/threaddesk_m1 | main_and_bridge_operator_profile_integrated | G-01 | a99afa8b4ddfdc4396521bad11d6868b2069d9b0 |
| TD-C02 | /root/threaddesk_m1 | integrated_runtime_and_actual_chatgpt_checked | G-01 | 583c000a8f226d5d9e71c51310fb0a81a3bafb49 |
| TD-C03 | /root/threaddesk_m1 | source_and_local_checks_complete_ci_pending | TD-C01 | 502f0db8a65d9701a44f956d5c56b3efbd748cf6 |
| TD-C04 | /root/threaddesk_m1 | open | operator_server_scope |  |
| TD-D01 | /root/threaddesk_m1 | source_and_local_checks_complete_ci_pending |  | 502f0db8a65d9701a44f956d5c56b3efbd748cf6 |
| TD-R01 | /root/threaddesk_m1 | source_and_local_checks_complete_ci_pending |  | 502f0db8a65d9701a44f956d5c56b3efbd748cf6 |
| KB-C01 | /root | integrated_runtime_and_actual_chatgpt_checked | TD-C01, G-01 | 4d59e7081d62c5e4e9924e9e710382d8d8772c43 |
| KB-C02 | /root | integrated_runtime_and_actual_chatgpt_checked | TD-C02, KB-C01 | 583c000a8f226d5d9e71c51310fb0a81a3bafb49 |
| KB-C03 | /root | integrated_runtime_and_actual_chatgpt_checked |  | 8226763 |
| KB-C04 | /root | open | TG-C02 |  |
| KB-C05 | /root | open | KB-C02 |  |
| KB-D01 | /root | integrated_runtime_assets_and_isolated_browser_checked |  | 19660bf98ad1c373e5ba791a57ec1752860ca8e2 |
| KB-R01 | /root | open |  |  |
| FP-C01 | /root/fourallpass_protected | source_and_ci_checked |  | 3fd6ed2 |
| FP-C02 | /root/fourallpass_protected | partial_fail_closed | FP-C01, KB-C02, TG-C01, secret_os_boundary | 014597b1fc85c1b633f911c3d3fdf6ef4bbd9a3a |
| FP-C03 | /root/fourallpass_protected | open | FP-C02, TG-C02, KB-C04 |  |
| FP-D01 | /root/fourallpass_protected | source_browser_and_ci_checked |  | fd5473203abc8fdc3fab4fff2e2331882d5f2dde |
| FP-R01 | /root/fourallpass_protected | source_browser_and_ci_checked |  | fd5473203abc8fdc3fab4fff2e2331882d5f2dde |
| FP-V01 | /root/fourallpass_protected | open | FP-C02, FP-C03 |  |
| TG-C01 | /root/tollgate_control | bounded_source_and_ci_checked | G-01 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-C02 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C01 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-C03 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C01, G-02 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-C04 | /root/tollgate_control | bounded_source_and_ci_checked | TG-C02, TG-C03 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-D01 | /root/tollgate_control | bounded_source_and_ci_checked |  | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-R01 | /root/tollgate_control | bounded_source_and_ci_checked |  | e8e66430fb64def027abdee2063a7a774a763883 |
| GH-C01 | /root | bounded_source_browser_and_ci_checked | TD-C02, KB-C02 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C02 | /root | bounded_source_browser_and_ci_checked | TG-C02, KB-C04 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C03 | /root | bounded_source_browser_and_ci_checked | TG-C03, FP-C02 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C04 | /root | open | GH-C01 |  |
| GH-C05 | /root | open | FP-C03, TG-C01 |  |
| GH-D01 | /root | bounded_source_browser_and_ci_checked |  | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-R01 | /root | bounded_source_browser_and_ci_checked |  | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| AA-C01 | /root | source_native_and_python_checks_complete | G-01, TD-C02, KB-C02 | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| AA-C02 | /root | source_native_and_targeted_checks_complete | AA-C01 | c62149b567ce090df44fa8e942906c3025e879be |
| AA-C03 | /root | open | operator_transport_scope |  |
| AA-D01 | /root | source_native_and_python_checks_complete |  | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| AA-R01 | /root | source_native_and_python_checks_complete |  | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| BD-C01 | /root | source_and_browser_checked |  | b875912e477523059671849f856a4b6dac8270e6 |
| BD-C02 | /root | source_and_isolated_browser_checked | BD-C01 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-C03 | /root | source_and_isolated_browser_checked | BD-C02 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-C04 | /root | open | TD-C02, KB-C02, KB-C05 |  |
| BD-D01 | /root | source_and_isolated_browser_checked | BD-C02, BD-C03, BD-C04 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-R01 | /root | source_and_isolated_browser_checked | BD-C01 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
