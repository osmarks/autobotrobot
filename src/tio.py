import pytio
import gzip
import io

tio = pytio.Tio()

async def languages(http_session):
    return await (await http_session.get("https://tio.run/languages.json")).json()

aliases = {
    "python": "python3",
    "javascript": "javascript-node"
}

async def run(http_session, lang, code):
    real_lang = aliases.get(lang, lang)
    req = pytio.TioRequest(real_lang, code)
    res = await (await http_session.post("https://tio.run/cgi-bin/run/api/", data=req.as_deflated_bytes(), timeout=65)).text()
    split = list(filter(lambda x: x != "\n" and x != "", res.split(res[:16])))
    if len(split) == 1:
        return False, real_lang, split[0], None
    else:
        return True, real_lang, split[0], split[1]
