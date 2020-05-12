import pytio
import http3
import gzip
import io

tio = pytio.Tio()

def languages():
    return tio.query_languages()

aliases = {
    "python": "python3",
    "javascript": "javascript-node"
}

client = http3.AsyncClient()

async def run(lang, code):
    real_lang = aliases.get(lang, lang)
    req = pytio.TioRequest(real_lang, code)
    res = await client.post("https://tio.run/cgi-bin/run/api/", data=req.as_deflated_bytes(), timeout=65)
    content = res.content.decode("UTF-8")
    split = list(filter(lambda x: x != "\n" and x != "", content.split(content[:16])))
    if len(split) == 1:
        return False, real_lang, split[0], None
    else:
        return True, real_lang, split[0], split[1]
