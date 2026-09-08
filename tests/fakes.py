"""Proveedor simulado para tests: sin red, resultados deterministas."""
from llmrouter.core.errors import ProviderError,QuotaExceededError,RateLimitError
from llmrouter.core.provider import Provider
class FakeProvider(Provider):
    def __init__(self,name,priority,outcome,model="fake-model",**kwargs): super().__init__(name=name,priority=priority,models=[model],**kwargs); self.outcome=outcome
    def complete(self,messages,model=None,temperature=None,max_tokens=None,timeout=60):
        if self.outcome=="quota": raise QuotaExceededError(self.name,"cuota agotada (insufficient_quota)",429)
        if self.outcome=="rate": raise RateLimitError(self.name,"too many requests",429)
        if self.outcome=="error": raise ProviderError(self.name,"internal server error",500)
        return {"content":f"hola desde {self.name}","model":model or self.models[0],"provider":self.name,"usage":{"prompt_tokens":9,"completion_tokens":4}}
