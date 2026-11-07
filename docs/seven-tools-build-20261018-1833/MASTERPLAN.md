# Baufortschritt · seven-tools-build-20261018-1833

Maßgeblich: status.json; diese Ansicht wird daraus erzeugt. Keine zweite Ausführungswarteschlange.

Koordinator: /root. Originalauftrag und acht Pläne: SOURCE.md, unverändert und per SHA-256 gebunden.

| Paket | Verantwortlich | Status | Abhängigkeiten | Commit / PR / Grenze |
|---|---|---|---|---|
| TD-C01 | /root/threaddesk_m1 | main_and_bridge_operator_profile_integrated | G-01 | a99afa8b4ddfdc4396521bad11d6868b2069d9b0 |
| TD-C02 | /root/threaddesk_m1 | integrated_runtime_and_actual_chatgpt_checked | G-01 | 583c000a8f226d5d9e71c51310fb0a81a3bafb49 |
| TD-C03 | /root/threaddesk_m1 | main_and_operator_runtime_actual_chatgpt_checked | TD-C01 | 6c7d578a1edb612d0e8e6d99faa2953888d69bfb |
| TD-C04 | /root/threaddesk_m1 | requires_separate_server_operating_decision | operator_server_scope | No selected authorized test server, remote identity/role/revocation policy or two distinct test installations. Local room/UI is not an Internet-team service. |
| TD-D01 | /root/threaddesk_m1 | main_integrated_source_browser_and_ci_checked |  | 6c7d578a1edb612d0e8e6d99faa2953888d69bfb |
| TD-R01 | /root/threaddesk_m1 | main_integrated_source_browser_and_ci_checked |  | 6c7d578a1edb612d0e8e6d99faa2953888d69bfb |
| KB-C01 | /root | integrated_runtime_and_actual_chatgpt_checked | TD-C01, G-01 | 4d59e7081d62c5e4e9924e9e710382d8d8772c43 |
| KB-C02 | /root | integrated_runtime_and_actual_chatgpt_checked | TD-C02, KB-C01 | 583c000a8f226d5d9e71c51310fb0a81a3bafb49 |
| KB-C03 | /root | integrated_runtime_and_actual_chatgpt_checked |  | 8226763 |
| KB-C04 | /root | main_runtime_and_actual_chatgpt_stop_checked | TG-C02 | f731f65d6422b08c511220689e42200e28cf39ae |
| KB-C05 | /root | bounded_image_and_selected_observations_actual_chatgpt_checked | KB-C02 | 9d6e1a86c7719d1755508f9d3e51a625d6660c1c |
| KB-D01 | /root | integrated_runtime_assets_and_isolated_browser_checked |  | 19660bf98ad1c373e5ba791a57ec1752860ca8e2 |
| KB-R01 | /root | main_integrated_DE_EN_instructions_checked |  | f19797b2e1b7e34b73de1180734a6b9c93ab07e5 |
| FP-C01 | /root/fourallpass_protected | main_integrated_bounded_source_and_targeted_checks |  | 3fd6ed2 |
| FP-C02 | /root/fourallpass_protected | partial_fail_closed | FP-C01, KB-C02, TG-C01, secret_os_boundary | 014597b1fc85c1b633f911c3d3fdf6ef4bbd9a3a |
| FP-C03 | /root/fourallpass_protected | blocked_production_secret_boundary | FP-C02, TG-C02, KB-C04 | No trusted production ProtectedHost/Vault transfer/consent and revocation source; no independent OS secret/browser-debug boundary or concrete allowed account action. Same-UID unrestricted terminal is not isolation. |
| FP-D01 | /root/fourallpass_protected | main_integrated_bounded_source_and_targeted_checks |  | fd5473203abc8fdc3fab4fff2e2331882d5f2dde |
| FP-R01 | /root/fourallpass_protected | main_integrated_bounded_source_and_targeted_checks |  | fd5473203abc8fdc3fab4fff2e2331882d5f2dde |
| FP-V01 | /root/fourallpass_protected | main_package_guard_source_and_targeted_checks_complete_remaining_platform_acceptance | FP-C02, FP-C03 | 4295599bcc5f60b731f8576da780b2a9c107e9c9 |
| TG-C01 | /root/tollgate_control | main_integrated_bounded_source_and_targeted_checks | G-01 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-C02 | /root/tollgate_control | main_and_registered_bridge_runtime_stop_only_checked | TG-C01 | 53fc57cc2e082d022e65e5929cb2a1e186fba852 |
| TG-C03 | /root/tollgate_control | main_integrated_bounded_source_and_targeted_checks | TG-C01, G-02 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-C04 | /root/tollgate_control | main_integrated_bounded_source_and_targeted_checks | TG-C02, TG-C03 | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-D01 | /root/tollgate_control | main_integrated_bounded_source_and_targeted_checks |  | e8e66430fb64def027abdee2063a7a774a763883 |
| TG-R01 | /root/tollgate_control | main_integrated_bounded_source_and_targeted_checks |  | e8e66430fb64def027abdee2063a7a774a763883 |
| GH-C01 | /root | main_integrated_bounded_source_and_targeted_checks | TD-C02, KB-C02 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C02 | /root | main_integrated_bounded_source_and_targeted_checks | TG-C02, KB-C04 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C03 | /root | main_integrated_bounded_source_and_targeted_checks | TG-C03, FP-C02 | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-C04 | /root | main_integrated_source_and_ci_checked | GH-C01 | 2c86ef004e1491f15393b59fea2cc466de662cca |
| GH-C05 | /root | blocked_protected_account_browser_path | FP-C03, TG-C01 | FP-C03 production secret/debug/session boundary and controlled allowed browser action unavailable; legacy unprotected standalone browsing is not protected account handling. |
| GH-D01 | /root | main_integrated_bounded_source_and_targeted_checks |  | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| GH-R01 | /root | main_integrated_bounded_source_and_targeted_checks |  | 875cabd82d8b74f6de78e9577237291e0d08cb1c |
| AA-C01 | /root | source_native_and_python_checks_complete | G-01, TD-C02, KB-C02 | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| AA-C02 | /root | main_integrated_bounded_source_and_targeted_checks | AA-C01 | c62149b567ce090df44fa8e942906c3025e879be |
| AA-C03 | /root | actual_selected_report_conversation_read_checked_web_scope_pending | operator_transport_scope | No concrete separate web-service transport/operator/authentication/retention scope; local selected snapshot is not live service coverage. |
| AA-D01 | /root | main_integrated_bounded_source_and_targeted_checks |  | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| AA-R01 | /root | main_integrated_bounded_source_and_targeted_checks |  | 9a0bd2acfbef64af0b56d0e566ee07d62adf05de |
| BD-C01 | /root | main_integrated_bounded_source_and_targeted_checks |  | b875912e477523059671849f856a4b6dac8270e6 |
| BD-C02 | /root | main_integrated_bounded_source_and_targeted_checks | BD-C01 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-C03 | /root | main_integrated_bounded_source_and_targeted_checks | BD-C02 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-C04 | /root | main_contract_checked_normal_start_profile_wiring_in_progress | TD-C02, KB-C02, KB-C05 | b0b63aa83b74592150686123275dc63c2260004e |
| BD-D01 | /root | main_integrated_bounded_source_and_targeted_checks | BD-C02, BD-C03, BD-C04 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
| BD-R01 | /root | main_integrated_bounded_source_and_targeted_checks | BD-C01 | 5a9b2925af7f0415185bae2ef807fd65166bbc54 |
