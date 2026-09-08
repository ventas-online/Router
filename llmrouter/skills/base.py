"""Clase base de las skills (plugins con descubrimiento automático)."""
from __future__ import annotations
from typing import Any, Dict, List
class SkillBase:
    name: str = ""; description: str = ""; parameters: List[Dict[str, Any]] = []; version: str = "1.0"
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name: cls.name = cls.__name__.lower()
    def run(self, ctx: Dict[str, Any]) -> Any: raise NotImplementedError
    def help(self): return {"name":self.name,"description":self.description,"parameters":self.parameters,"version":self.version}
