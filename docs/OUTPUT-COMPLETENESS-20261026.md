# Output completeness / Vollständigkeit der Ausgabe

Base / Basis: merged `0866c00364994577581e56f5eee18538941a9315`.

## Deutsch

`read_query(terminal.output)` erhält eine bereits im Prozess-Capture bekannte Kürzung.
Das additive `output_completeness` trennt `capture` (`complete`, `truncated`, `unknown`)
von `response_truncated`, also einer weiteren Kürzung für die aktuelle Antwort.
`retained_text_bytes` und `returned_text_bytes` zählen die UTF-8-Textbytes des vorhandenen
Captures bzw. der Antwort, nicht wiederhergestellte Originalbytes. Ein vorhandener
Prozesszähler bleibt separat als `output_bytes_observed` sichtbar (sonst `null`).
Ein größerer Prozesszähler belegt eine unvollständige zurückbehaltene Ausgabe.

`scope: visible_terminal_view` und `protocol_history: visible_view_only` kennzeichnen
sichtbare Ausschnitte. Auch ein vollständig gelieferter Capture beweist keine vollständige
Agenten- oder Projekthistorie (`protocol_history: not_established`). Bereits verworfene
Bytes werden nicht wiederhergestellt. Bestehende Grenzen, Eigentümer- und Rechteprüfungen
bleiben erhalten. Pagination und ein dauerhafter vollständiger Protokoll-Export sind
hier nicht implementiert. Der native Terminal-Suffix wird nach Unicode-Codepoints
statt UTF-16-Einheiten geschnitten; die nachgelagerte UTF-8-Bytegrenze bleibt bestehen.

## English

`read_query(terminal.output)` preserves truncation already known by the process capture.
The additive `output_completeness` separates capture completeness (`complete`, `truncated`,
`unknown`) from further truncation of the current response (`response_truncated`).
`retained_text_bytes` and `returned_text_bytes` count available UTF-8 text, not reconstructed
original bytes. `output_bytes_observed` carries an available process byte counter, otherwise
`null`. A larger observed counter proves that the retained output is incomplete.

Visible captures explicitly describe a terminal view, not a complete protocol history.
Even a complete capture does not certify complete agent/project history. Discarded bytes
are not recovered. Limits, ownership and authorization checks remain unchanged. Pagination
and durable full-protocol export are not implemented here. The native Terminal suffix now
uses Unicode codepoints rather than UTF-16 units; downstream UTF-8 byte limits still apply.

## Targeted evidence

Two pre-fix reproductions failed as expected: inherited truncation and the emoji suffix
boundary. After the fix, **11 tests passed**: five new completeness cases, three new JXA
read-expression cases and three existing owner/byte-budget cases. JXA ran on Intel macOS
with a fake tab object; it did not open or inspect any Terminal window, use clipboard or
call `Application`. This is interpreter-level coverage, not actual ChatGPT-host acceptance
or a native production-window test. No complete suite or productive install was run.

Command (use this worktree's source and an existing Python environment with project dev
requirements):

```sh
PYTHONPATH=src python -m pytest -q tests/test_output_completeness.py tests/test_terminal_unicode.py tests/test_read_query.py::test_terminal_output_is_real_bounded_and_owner_checked tests/test_read_query.py::test_terminal_output_utf8_boundary_does_not_expand_byte_budget
```
