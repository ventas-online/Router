"""Router principal con prioridad, límites, cooldown y failover."""
from __future__ import annotations
import time
from .errors import AllProvidersExhausted,QuotaExceededError,RateLimitError,ProviderError
from .usage_tracker import UsageTracker
from ..skills import SkillRegistry
class Router:
    def __init__(self,providers=None,daily_limits=None,usage_tracker=None,max_retries=1,base_delay=0.5,skills_dir=None):
        self._providers=sorted(providers or [],key=lambda p:p.priority); self.daily_limits=daily_limits or {}; self.usage_tracker=usage_tracker or UsageTracker(); self.max_retries=max_retries; self.base_delay=base_delay; self.skill_registry=SkillRegistry(self,skills_dir)
    def providers(self): return list(self._providers)
    def _over_limit(self,name):
        limit=self.daily_limits.get(name) or self.daily_limits.get("DAILY_LIMIT_"+name.upper(),0)
        return bool(limit and self.usage_tracker.get_day_usage(name)>=int(limit))
    def complete(self,messages,model=None,temperature=None,max_tokens=None):
        failures=[]
        for p in self._providers:
            if not p.available() or self._over_limit(p.name): continue
            attempts=0
            while attempts<=self.max_retries:
                try:
                    resp=p.complete(messages,model,temperature,max_tokens); p.record_success(); self.usage_tracker.record(p.name,resp.get("model",model or ""),resp.get("usage")); return resp
                except (QuotaExceededError,RateLimitError,ProviderError) as e:
                    failures.append(str(e)); p.record_failure(); attempts+=1
                    if attempts<=self.max_retries and not isinstance(e,QuotaExceededError): time.sleep(self.base_delay*(2**(attempts-1)))
                    else: break
        raise AllProvidersExhausted(failures)
    def list_skills(self): return self.skill_registry.list()
    def run_skill(self,name,**inputs): return self.skill_registry.run(name,**inputs)
    def status(self):
        return [{"provider":p.name,"priority":p.priority,"available":p.available(),"day_tokens":self.usage_tracker.get_day_usage(p.name),"models":p.models} for p in self._providers]
