# Statisches Modulinventar · 26 October2026

Quelle0866c00: **117 Module, 30623 Quellzeilen**.

Alle getrackten Pythonmodule unter src wurden per AST erfasst. Importreferenzen schließen verzögerte Imports ein; Zyklen sind damit konkrete statische Kopplungen, kein Beleg eines Importfehlers. Das Inventar ersetzt keine vollständige semantische Prüfung.

[Maschinenlesbares Inventar mit Abhängigkeiten, Grenzen und Zyklen](evidence/universal-static-module-inventory-20261026.json).

| Moduldatei | Zeilen | Klassen / Funktionen |
|---|---:|---:|
| [src/kirabridge/__init__.py](../src/kirabridge/__init__.py) | 5 | 0 / 0 |
| [src/kirabridge/admin_manager.py](../src/kirabridge/admin_manager.py) | 65 | 0 / 2 |
| [src/kirabridge/agent_manager/__init__.py](../src/kirabridge/agent_manager/__init__.py) | 665 | 5 / 16 |
| [src/kirabridge/agent_manager/claude.py](../src/kirabridge/agent_manager/claude.py) | 172 | 1 / 5 |
| [src/kirabridge/agent_manager/cli_support.py](../src/kirabridge/agent_manager/cli_support.py) | 82 | 1 / 5 |
| [src/kirabridge/agent_manager/copilot.py](../src/kirabridge/agent_manager/copilot.py) | 192 | 1 / 5 |
| [src/kirabridge/agent_manager/full_access.py](../src/kirabridge/agent_manager/full_access.py) | 227 | 1 / 7 |
| [src/kirabridge/agent_manager/gemini.py](../src/kirabridge/agent_manager/gemini.py) | 339 | 1 / 7 |
| [src/kirabridge/agent_manager/opencode.py](../src/kirabridge/agent_manager/opencode.py) | 274 | 1 / 6 |
| [src/kirabridge/approval_console.py](../src/kirabridge/approval_console.py) | 229 | 1 / 16 |
| [src/kirabridge/audit_manager/__init__.py](../src/kirabridge/audit_manager/__init__.py) | 66 | 2 / 6 |
| [src/kirabridge/automatic_review_demo.py](../src/kirabridge/automatic_review_demo.py) | 456 | 1 / 15 |
| [src/kirabridge/bridge_core/__init__.py](../src/kirabridge/bridge_core/__init__.py) | 1 | 0 / 0 |
| [src/kirabridge/bridge_core/bridge.py](../src/kirabridge/bridge_core/bridge.py) | 682 | 1 / 15 |
| [src/kirabridge/bridge_core/config.py](../src/kirabridge/bridge_core/config.py) | 418 | 19 / 12 |
| [src/kirabridge/bridge_core/models.py](../src/kirabridge/bridge_core/models.py) | 217 | 29 / 3 |
| [src/kirabridge/chatgpt_setup.py](../src/kirabridge/chatgpt_setup.py) | 380 | 0 / 8 |
| [src/kirabridge/cli.py](../src/kirabridge/cli.py) | 744 | 0 / 5 |
| [src/kirabridge/clipboard_manager/__init__.py](../src/kirabridge/clipboard_manager/__init__.py) | 90 | 1 / 5 |
| [src/kirabridge/completion_client.py](../src/kirabridge/completion_client.py) | 73 | 1 / 5 |
| [src/kirabridge/completion_manager.py](../src/kirabridge/completion_manager.py) | 263 | 1 / 10 |
| [src/kirabridge/configured_workflow.py](../src/kirabridge/configured_workflow.py) | 312 | 1 / 10 |
| [src/kirabridge/console_runtime.py](../src/kirabridge/console_runtime.py) | 205 | 0 / 5 |
| [src/kirabridge/control_center.py](../src/kirabridge/control_center.py) | 115 | 1 / 13 |
| [src/kirabridge/development_status.py](../src/kirabridge/development_status.py) | 366 | 0 / 8 |
| [src/kirabridge/diagnostics.py](../src/kirabridge/diagnostics.py) | 302 | 1 / 9 |
| [src/kirabridge/discovery.py](../src/kirabridge/discovery.py) | 160 | 0 / 3 |
| [src/kirabridge/event_push.py](../src/kirabridge/event_push.py) | 624 | 5 / 26 |
| [src/kirabridge/event_queue.py](../src/kirabridge/event_queue.py) | 134 | 0 / 6 |
| [src/kirabridge/file_transfer/__init__.py](../src/kirabridge/file_transfer/__init__.py) | 1 | 0 / 0 |
| [src/kirabridge/file_transfer/authorization.py](../src/kirabridge/file_transfer/authorization.py) | 60 | 1 / 5 |
| [src/kirabridge/file_transfer/diagnostics.py](../src/kirabridge/file_transfer/diagnostics.py) | 12 | 0 / 1 |
| [src/kirabridge/file_transfer/integrity.py](../src/kirabridge/file_transfer/integrity.py) | 182 | 1 / 8 |
| [src/kirabridge/file_transfer/models.py](../src/kirabridge/file_transfer/models.py) | 64 | 7 / 0 |
| [src/kirabridge/file_transfer/ports.py](../src/kirabridge/file_transfer/ports.py) | 29 | 2 / 9 |
| [src/kirabridge/file_transfer/protocol.py](../src/kirabridge/file_transfer/protocol.py) | 118 | 0 / 2 |
| [src/kirabridge/file_transfer/repository.py](../src/kirabridge/file_transfer/repository.py) | 118 | 1 / 8 |
| [src/kirabridge/file_transfer/service.py](../src/kirabridge/file_transfer/service.py) | 376 | 1 / 6 |
| [src/kirabridge/file_transfer/sources.py](../src/kirabridge/file_transfer/sources.py) | 278 | 4 / 13 |
| [src/kirabridge/file_transfer/threaddesk.py](../src/kirabridge/file_transfer/threaddesk.py) | 241 | 1 / 12 |
| [src/kirabridge/filesystem_manager/__init__.py](../src/kirabridge/filesystem_manager/__init__.py) | 172 | 2 / 10 |
| [src/kirabridge/grok_connector/__init__.py](../src/kirabridge/grok_connector/__init__.py) | 28 | 0 / 2 |
| [src/kirabridge/grok_connector/administration.py](../src/kirabridge/grok_connector/administration.py) | 88 | 1 / 6 |
| [src/kirabridge/grok_connector/auth_store.py](../src/kirabridge/grok_connector/auth_store.py) | 791 | 2 / 29 |
| [src/kirabridge/grok_connector/console.py](../src/kirabridge/grok_connector/console.py) | 353 | 1 / 8 |
| [src/kirabridge/grok_connector/conversation.py](../src/kirabridge/grok_connector/conversation.py) | 288 | 0 / 4 |
| [src/kirabridge/grok_connector/gateway.py](../src/kirabridge/grok_connector/gateway.py) | 614 | 5 / 20 |
| [src/kirabridge/grok_connector/provider.py](../src/kirabridge/grok_connector/provider.py) | 55 | 1 / 10 |
| [src/kirabridge/grok_connector/runtime.py](../src/kirabridge/grok_connector/runtime.py) | 602 | 0 / 12 |
| [src/kirabridge/handoff_manager.py](../src/kirabridge/handoff_manager.py) | 715 | 1 / 18 |
| [src/kirabridge/image_manager.py](../src/kirabridge/image_manager.py) | 217 | 1 / 4 |
| [src/kirabridge/install_ui.py](../src/kirabridge/install_ui.py) | 303 | 1 / 23 |
| [src/kirabridge/installation.py](../src/kirabridge/installation.py) | 314 | 0 / 5 |
| [src/kirabridge/local_runtime.py](../src/kirabridge/local_runtime.py) | 208 | 0 / 8 |
| [src/kirabridge/mcp_gateway/__init__.py](../src/kirabridge/mcp_gateway/__init__.py) | 0 | 0 / 0 |
| [src/kirabridge/mcp_gateway/client.py](../src/kirabridge/mcp_gateway/client.py) | 426 | 3 / 17 |
| [src/kirabridge/mcp_gateway/file_tools.py](../src/kirabridge/mcp_gateway/file_tools.py) | 216 | 0 / 12 |
| [src/kirabridge/mcp_gateway/http.py](../src/kirabridge/mcp_gateway/http.py) | 51 | 1 / 4 |
| [src/kirabridge/mcp_gateway/proxy.py](../src/kirabridge/mcp_gateway/proxy.py) | 211 | 1 / 10 |
| [src/kirabridge/mcp_gateway/queue_tools.py](../src/kirabridge/mcp_gateway/queue_tools.py) | 102 | 0 / 6 |
| [src/kirabridge/mcp_gateway/server.py](../src/kirabridge/mcp_gateway/server.py) | 874 | 0 / 59 |
| [src/kirabridge/message_manager/__init__.py](../src/kirabridge/message_manager/__init__.py) | 504 | 2 / 15 |
| [src/kirabridge/message_manager/receiver.py](../src/kirabridge/message_manager/receiver.py) | 672 | 1 / 18 |
| [src/kirabridge/observation_export.py](../src/kirabridge/observation_export.py) | 487 | 0 / 13 |
| [src/kirabridge/operations.py](../src/kirabridge/operations.py) | 123 | 1 / 3 |
| [src/kirabridge/operations_service.py](../src/kirabridge/operations_service.py) | 574 | 1 / 16 |
| [src/kirabridge/operator_actions.py](../src/kirabridge/operator_actions.py) | 153 | 3 / 10 |
| [src/kirabridge/operator_application.py](../src/kirabridge/operator_application.py) | 85 | 3 / 3 |
| [src/kirabridge/operator_control.py](../src/kirabridge/operator_control.py) | 580 | 1 / 17 |
| [src/kirabridge/operator_platform.py](../src/kirabridge/operator_platform.py) | 72 | 2 / 4 |
| [src/kirabridge/operator_queries.py](../src/kirabridge/operator_queries.py) | 83 | 1 / 6 |
| [src/kirabridge/output_history.py](../src/kirabridge/output_history.py) | 269 | 1 / 11 |
| [src/kirabridge/permissions.py](../src/kirabridge/permissions.py) | 146 | 0 / 7 |
| [src/kirabridge/platform_adapters/__init__.py](../src/kirabridge/platform_adapters/__init__.py) | 226 | 5 / 14 |
| [src/kirabridge/platform_adapters/_exec.py](../src/kirabridge/platform_adapters/_exec.py) | 20 | 0 / 1 |
| [src/kirabridge/platform_adapters/clipboard_lease.py](../src/kirabridge/platform_adapters/clipboard_lease.py) | 250 | 1 / 5 |
| [src/kirabridge/platform_adapters/codex_state.py](../src/kirabridge/platform_adapters/codex_state.py) | 232 | 2 / 7 |
| [src/kirabridge/platform_adapters/desktop.py](../src/kirabridge/platform_adapters/desktop.py) | 80 | 1 / 4 |
| [src/kirabridge/platform_adapters/shell_prompt.py](../src/kirabridge/platform_adapters/shell_prompt.py) | 14 | 0 / 1 |
| [src/kirabridge/platform_adapters/terminal_app.py](../src/kirabridge/platform_adapters/terminal_app.py) | 452 | 1 / 18 |
| [src/kirabridge/platform_adapters/tmux.py](../src/kirabridge/platform_adapters/tmux.py) | 95 | 1 / 7 |
| [src/kirabridge/private_files.py](../src/kirabridge/private_files.py) | 27 | 0 / 2 |
| [src/kirabridge/process_manager/__init__.py](../src/kirabridge/process_manager/__init__.py) | 17 | 1 / 2 |
| [src/kirabridge/queue_management/__init__.py](../src/kirabridge/queue_management/__init__.py) | 4 | 0 / 0 |
| [src/kirabridge/queue_management/control.py](../src/kirabridge/queue_management/control.py) | 280 | 1 / 5 |
| [src/kirabridge/queue_management/models.py](../src/kirabridge/queue_management/models.py) | 29 | 2 / 0 |
| [src/kirabridge/queue_management/schema.py](../src/kirabridge/queue_management/schema.py) | 28 | 0 / 1 |
| [src/kirabridge/queue_management/views.py](../src/kirabridge/queue_management/views.py) | 277 | 1 / 14 |
| [src/kirabridge/read_query.py](../src/kirabridge/read_query.py) | 158 | 1 / 3 |
| [src/kirabridge/readiness.py](../src/kirabridge/readiness.py) | 334 | 1 / 18 |
| [src/kirabridge/review_demo.py](../src/kirabridge/review_demo.py) | 205 | 1 / 8 |
| [src/kirabridge/security_manager/__init__.py](../src/kirabridge/security_manager/__init__.py) | 239 | 1 / 14 |
| [src/kirabridge/session_input_policy.py](../src/kirabridge/session_input_policy.py) | 166 | 1 / 9 |
| [src/kirabridge/session_manager.py](../src/kirabridge/session_manager.py) | 573 | 5 / 22 |
| [src/kirabridge/session_ports.py](../src/kirabridge/session_ports.py) | 50 | 6 / 15 |
| [src/kirabridge/setup_dependencies.py](../src/kirabridge/setup_dependencies.py) | 93 | 0 / 2 |
| [src/kirabridge/task_manager/__init__.py](../src/kirabridge/task_manager/__init__.py) | 1 | 0 / 0 |
| [src/kirabridge/task_manager/manager.py](../src/kirabridge/task_manager/manager.py) | 476 | 1 / 15 |
| [src/kirabridge/task_manager/store.py](../src/kirabridge/task_manager/store.py) | 503 | 1 / 20 |
| [src/kirabridge/team_console.py](../src/kirabridge/team_console.py) | 861 | 1 / 22 |
| [src/kirabridge/team_manager/__init__.py](../src/kirabridge/team_manager/__init__.py) | 1182 | 1 / 47 |
| [src/kirabridge/team_manager/dispatcher.py](../src/kirabridge/team_manager/dispatcher.py) | 482 | 4 / 13 |
| [src/kirabridge/team_manager/models.py](../src/kirabridge/team_manager/models.py) | 68 | 7 / 0 |
| [src/kirabridge/terminal_access.py](../src/kirabridge/terminal_access.py) | 57 | 0 / 1 |
| [src/kirabridge/terminal_design.py](../src/kirabridge/terminal_design.py) | 369 | 2 / 17 |
| [src/kirabridge/terminal_manager/__init__.py](../src/kirabridge/terminal_manager/__init__.py) | 201 | 2 / 8 |
| [src/kirabridge/terminal_queries.py](../src/kirabridge/terminal_queries.py) | 67 | 1 / 2 |
| [src/kirabridge/threaddesk_contract.py](../src/kirabridge/threaddesk_contract.py) | 294 | 1 / 9 |
| [src/kirabridge/threaddesk_dynamic.py](../src/kirabridge/threaddesk_dynamic.py) | 119 | 0 / 5 |
| [src/kirabridge/threaddesk_manager.py](../src/kirabridge/threaddesk_manager.py) | 291 | 1 / 10 |
| [src/kirabridge/visible_handoff.py](../src/kirabridge/visible_handoff.py) | 809 | 2 / 20 |
| [src/kirabridge/visible_message_evidence.py](../src/kirabridge/visible_message_evidence.py) | 170 | 0 / 4 |
| [src/kirabridge/visible_readiness.py](../src/kirabridge/visible_readiness.py) | 113 | 0 / 4 |
| [src/kirabridge/visible_terminal.py](../src/kirabridge/visible_terminal.py) | 225 | 2 / 4 |
| [src/kirabridge/voice_channel.py](../src/kirabridge/voice_channel.py) | 114 | 1 / 6 |
| [src/kirabridge/voice_message_policy.py](../src/kirabridge/voice_message_policy.py) | 141 | 1 / 7 |
| [src/kirabridge/workflow_control_adapter.py](../src/kirabridge/workflow_control_adapter.py) | 518 | 2 / 10 |

## Statische Zyklen

- `kirabridge.permissions`, `kirabridge.session_input_policy`
- `kirabridge.message_manager`, `kirabridge.voice_message_policy`
- `kirabridge.bridge_core.bridge`, `kirabridge.diagnostics`, `kirabridge.grok_connector`, `kirabridge.grok_connector.gateway`, `kirabridge.grok_connector.runtime`, `kirabridge.local_runtime`, `kirabridge.message_manager.receiver`, `kirabridge.operations_service`, `kirabridge.readiness`, `kirabridge.team_manager.dispatcher`
- `kirabridge.approval_console`, `kirabridge.control_center`
