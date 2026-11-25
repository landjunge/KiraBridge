"""Codex paste echo specification; no native execution."""

import json

from .rendering import MAX_FULL, codex_payload_forms, codex_wrap_words


def paste_source(text):
    return (
        "\nfunction observedPaste(before, after, columns) {"
        "if(before===after) return false;"
        r"const prompts=Array.from(after.matchAll(/^[ \t]*[›»][^\n]*/gm));"
        "if(!prompts.length) return false;"
        "const current=after.slice(prompts[prompts.length-1].index)"
        r".replace(/^[ \t]*[›»] ?/,'');"
        "const forms="
        + json.dumps(codex_payload_forms(text))
        + "; const lines="
        + json.dumps(codex_wrap_words(text))
        + ";"
        "if(lines && Number.isInteger(columns) && columns>=20 && columns<=4096) {"
        "for(const width of [columns-3,columns-4]) {"
        "if(lines.some(words=>words.some(word=>word.length>=width))) continue;"
        "let parts=[], wrapped=false;"
        "for(const words of lines) { let logical=words.length?[words[0]]:[''];"
        "for(const word of words.slice(1)) {"
        "if(logical[logical.length-1].length+1+word.length<=width)"
        "logical[logical.length-1]+=' '+word;"
        "else {logical.push(word); wrapped=true;} } parts.push(logical); }"
        # A full logical-line end shows an extra blank row or one extra ASCII space:
        # accept every combination (same enumeration as codex_wrapped_renderings).
        "const full=[]; parts.forEach((l,i)=>{if(l[l.length-1].length===width) full.push(i);});"
        "const few=full.length<=" + str(MAX_FULL) + ";"
        "const combos=few?Math.pow(3,full.length):1;"
        "for(let n=0;n<combos;n++) {"
        "const codes=full.map((_,k)=>few?Math.floor(n/Math.pow(3,full.length-1-k))%3:0);"
        "let rows=[];"
        "parts.forEach((l,i)=>{l=l.slice(); const k=full.indexOf(i);"
        "const code=k>=0?codes[k]:0; if(code===2) l[l.length-1]+=' ';"
        "rows=rows.concat(l); if(code===1) rows.push('');});"
        "if(!wrapped && !codes.some(c=>c)) continue;"
        "forms.push(rows.join('\\n  '));"
        "if(rows.slice(1).includes('')) forms.push(rows[0]+rows.slice(1)"
        ".map(row=>row?'\\n  '+row:'\\n ').join('')); } } }"
        "return forms.some(form=>current.startsWith(form) && "
        "(current.length===form.length || current[form.length]==='\\n'));}\n"
    )
