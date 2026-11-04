"""Codex paste echo specification; no native execution."""

import json

from .rendering import codex_payload_forms, codex_wrap_words


def paste_source(text):
    return (
        "\nfunction observedPaste(before, after, columns) {"
        "if(before===after) return false;"
        "const prompts=Array.from(after.matchAll(/^[ \\t]*›[^\\n]*/gm));"
        "if(!prompts.length) return false;"
        "const current=after.slice(prompts[prompts.length-1].index)"
        ".replace(/^[ \\t]*› ?/,'');"
        "const forms="
        + json.dumps(codex_payload_forms(text))
        + "; const lines="
        + json.dumps(codex_wrap_words(text))
        + ";"
        "if(lines && Number.isInteger(columns) && columns>=20 && columns<=4096) {"
        "for(const width of [columns-3,columns-4]) {"
        "if(lines.some(words=>words.some(word=>word.length>=width))) continue;"
        "let rows=[], wrapped=false;"
        "for(const words of lines) { let logical=words.length?[words[0]]:[''];"
        "for(const word of words.slice(1)) {"
        "if(logical[logical.length-1].length+1+word.length<=width)"
        "logical[logical.length-1]+=' '+word;"
        "else {logical.push(word); wrapped=true;} } rows=rows.concat(logical); }"
        "if(wrapped) { forms.push(rows.join('\\n  '));"
        "if(rows.slice(1).includes('')) forms.push(rows[0]+rows.slice(1)"
        ".map(row=>row?'\\n  '+row:'\\n ').join('')); } } }"
        "return forms.some(form=>current.startsWith(form) && "
        "(current.length===form.length || current[form.length]==='\\n'));}\n"
    )
