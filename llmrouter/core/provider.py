"""Adaptadores de proveedores LLM."""
from __future__ import annotations
import time
from .errors import ProviderError,QuotaExceededError,RateLimitError,CircuitOpenError
from .transport import http_post_json
QUOTA_MARKERS=("insufficient_quota","quota exceeded","quota_exceeded","out of quota","exceeded your current quota","resource_exhausted")
RATE_MARKERS=("rate limit","rate_limit","too many requests","exceeded rate")

def _markers_in(text,markers): return any(m in text.lower() for m in markers)

class Provider:
    def __init__(self,name,priority=1,models=None,cooldown_seconds=300,failure_threshold=3):
        self.name=name; self.priority=priority; self.models=models or []; self.cooldown_seconds=cooldown_seconds or 300; self.failure_threshold=failure_threshold or 3; self.consecutive_failures=0; self._cooldown_until=0.0; self._circuit=False
    def in_cooldown(self): return time.time()<self._cooldown_until
    def circuit_open(self): return self._circuit
    def available(self): return not self.in_cooldown() and not self._circuit
    def record_failure(self):
        self.consecutive_failures+=1; self._cooldown_until=time.time()+self.cooldown_seconds
        if self.consecutive_failures>=self.failure_threshold: self._circuit=True
    def record_success(self): self.consecutive_failures=0; self._cooldown_until=0; self._circuit=False
    def complete(self,*args,**kwargs): raise NotImplementedError

class OpenAICompatibleProvider(Provider):
    def __init__(self,name,base_url,api_key,models,**kwargs): super().__init__(name,models=models,**kwargs); self.base_url=base_url.rstrip('/'); self.api_key=api_key
    def complete(self,messages,model=None,temperature=None,max_tokens=None,timeout=60):
        model=model or self.models[0]; payload={"model":model,"messages":messages}
        if temperature is not None: payload["temperature"]=temperature
        if max_tokens is not None: payload["max_tokens"]=max_tokens
        status,body=http_post_json(self.base_url+"/chat/completions",{"Authorization":f"Bearer {self.api_key}"},payload,timeout)
        if status>=400 or status==0:
            msg=str(body.get("error",{}).get("message",body))
            if status in (402,429) and _markers_in(msg,QUOTA_MARKERS): raise QuotaExceededError(self.name,msg,status)
            if status in (429,503) or _markers_in(msg,RATE_MARKERS): raise RateLimitError(self.name,msg,status)
            raise ProviderError(self.name,msg,status)
        choice=(body.get("choices") or [{}])[0]; usage=body.get("usage") or {}
        return {"content":choice.get("message",{}).get("content","") or choice.get("text","") ,"model":body.get("model",model),"provider":self.name,"usage":usage}

class GeminiProvider(Provider):
    def __init__(self,name,base_url,api_key,models,**kwargs): super().__init__(name,models=models,**kwargs); self.base_url=base_url.rstrip('/'); self.api_key=api_key
    def complete(self,messages,model=None,temperature=None,max_tokens=None,timeout=60):
        model=model or self.models[0]; contents=[{"role":"user","parts":[{"text":m.get("content","")}]} for m in messages]
        payload={"contents":contents}; gen={}
        if temperature is not None: gen["temperature"]=temperature
        if max_tokens is not None: gen["maxOutputTokens"]=max_tokens
        if gen: payload["generationConfig"]=gen
        status,body=http_post_json(f"{self.base_url}/models/{model}:generateContent?key={self.api_key}",{},payload,timeout)
        msg=str(body.get("error",{}).get("message",body))
        if status>=400 or status==0:
            if status in (429,503): raise RateLimitError(self.name,msg,status)
            raise ProviderError(self.name,msg,status)
        parts=((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return {"content":"".join(p.get("text","") for p in parts),"model":model,"provider":self.name,"usage":body.get("usageMetadata",{})}
