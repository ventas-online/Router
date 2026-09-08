"""Descubrimiento y registro de skills (plugins en una carpeta)."""
from __future__ import annotations
import importlib.util, inspect
from pathlib import Path
from typing import Any, Dict, List, Optional
from .base import SkillBase
DEFAULT_SKILLS_DIR=Path(__file__).resolve().parent

def discover_skills(skills_dir: Optional[str|Path]=None)->Dict[str,SkillBase]:
    skills_dir=Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR; found={}
    if not skills_dir.is_dir(): return found
    for py in sorted(skills_dir.glob("*.py")):
        if py.name.startswith("_") or py.name=="base.py": continue
        mod_name=f"llmrouter.skills.{py.stem}" if skills_dir.resolve()==DEFAULT_SKILLS_DIR.resolve() else f"llmrouter_ext_skill_{py.stem}"
        spec=importlib.util.spec_from_file_location(mod_name,py)
        if spec is None or spec.loader is None: continue
        module=importlib.util.module_from_spec(spec)
        try: spec.loader.exec_module(module)
        except Exception: continue
        for _,obj in inspect.getmembers(module,inspect.isclass):
            if obj is SkillBase or not issubclass(obj,SkillBase) or not obj.name: continue
            found[obj.name]=obj()
    return found

class SkillRegistry:
    def __init__(self,router:Any=None,skills_dir:Optional[str|Path]=None): self.router=router; self.skills=discover_skills(skills_dir)
    def list(self)->List[Dict[str,Any]]: return [s.help() for s in self.skills.values()]
    def names(self): return list(self.skills.keys())
    def get(self,name): return self.skills.get(name)
    def add(self,skill): self.skills[skill.name]=skill
    def run(self,name,**inputs):
        skill=self.get(name)
        if skill is None: raise KeyError(f"Skill no encontrada: {name}. Disponibles: {', '.join(self.names())}")
        return skill.run({"router":self.router,"registry":self,"inputs":inputs})
