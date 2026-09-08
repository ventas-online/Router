"""Skill de ejemplo: traducción con el modelo enrutado."""
from .base import SkillBase
class TranslateSkill(SkillBase):
    name="translate"; description="Traduce un texto a otro idioma usando el modelo enrutado."
    parameters=[{"name":"text","type":"string","required":True,"description":"Texto a traducir"},{"name":"to","type":"string","required":True,"description":"Idioma destino"}]
    def run(self,ctx):
        router=ctx["router"]
        if router is None: raise RuntimeError("La skill 'translate' necesita un router.")
        text=ctx["inputs"].get("text",""); target=ctx["inputs"].get("to","inglés")
        resp=router.complete([{"role":"user","content":f"Traduce el siguiente texto a {target}. Devuelve SOLO la traducción, sin comentarios:\n\n{text}"}])
        return resp["content"]
