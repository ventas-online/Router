"""Skill de ejemplo: resumen de textos largos con el modelo enrutado."""
from .base import SkillBase
class SummarizeSkill(SkillBase):
    name="summarize"; description="Resume un texto largo en un número máximo de palabras."
    parameters=[{"name":"text","type":"string","required":True,"description":"Texto a resumir"},{"name":"max_words","type":"integer","required":False,"description":"Máximo de palabras (por defecto 150)"},{"name":"language","type":"string","required":False,"description":"Idioma del resumen"}]
    def run(self,ctx):
        router=ctx["router"]
        if router is None: raise RuntimeError("La skill 'summarize' necesita un router.")
        text=ctx["inputs"].get("text",""); max_words=ctx["inputs"].get("max_words",150); language=ctx["inputs"].get("language","el mismo idioma del texto")
        resp=router.complete([{"role":"user","content":f"Resume el siguiente texto en un máximo de {max_words} palabras, en {language}. Sé conciso y conserva las ideas clave:\n\n{text}"}])
        return resp["content"]
