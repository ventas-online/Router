"""Catálogo de proveedores y construcción desde variables de entorno."""
from __future__ import annotations
from typing import Dict,List,Optional
from ..core.provider import GeminiProvider,OpenAICompatibleProvider
PROVIDER_CATALOG={
"openrouter":{"base_url":"https://openrouter.ai/api/v1","env_key":"OPENROUTER_API_KEY","kind":"openai","models":["deepseek/deepseek-chat-v3-0324:free","meta-llama/llama-4-maverick:free","deepseek/deepseek-r1:free"]},
"cerebras":{"base_url":"https://api.cerebras.ai/v1","env_key":"CEREBRAS_API_KEY","kind":"openai","models":["llama-4-scout-17b-16e-instruct","qwen3-32b","deepseek-r1-distill-llama-70b"]},
"groq":{"base_url":"https://api.groq.com/openai/v1","env_key":"GROQ_API_KEY","kind":"openai","models":["llama-3.3-70b-versatile","gpt-oss-20b"]},
"gemini":{"base_url":"https://generativelanguage.googleapis.com/v1beta","env_key":"GEMINI_API_KEY","kind":"gemini","models":["gemini-2.5-flash","gemini-2.5-flash-lite"]},
"mistral":{"base_url":"https://api.mistral.ai/v1","env_key":"MISTRAL_API_KEY","kind":"openai","models":["mistral-small-latest"]},
"huggingface":{"base_url":"https://router.huggingface.co/v1","env_key":"HF_API_KEY","kind":"openai","models":["meta-llama/Llama-3.3-70B-Instruct"]}}
def build_providers_from_env(env:Dict[str,str],priority:Optional[List[str]]=None,cooldown_seconds:Optional[float]=None,failure_threshold:Optional[int]=None):
    providers=[]
    for idx,name in enumerate(priority or PROVIDER_CATALOG):
        spec=PROVIDER_CATALOG.get(name)
        if not spec: continue
        key=str(env.get(spec["env_key"],"")).strip()
        if not key: continue
        cls=GeminiProvider if spec["kind"]=="gemini" else OpenAICompatibleProvider
        providers.append(cls(name=name,base_url=spec["base_url"],api_key=key,models=list(spec["models"]),priority=idx+1,cooldown_seconds=cooldown_seconds,failure_threshold=failure_threshold))
    return providers
