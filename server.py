"""Dependency-free web/API server for the Router AI workspace."""
from __future__ import annotations
import json, mimetypes, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from llmrouter import Router, build_providers_from_env, load_env
from llmrouter.web_store import WebStore
ROOT=Path(__file__).resolve().parent; WEB=ROOT/"web"
MAX_BODY=int(os.getenv("ROUTER_MAX_BODY_BYTES","1048576")); STORE=WebStore(os.getenv("ROUTER_WEB_DB",str(ROOT/"router_web.sqlite3")))
def build_router():
    env=load_env(); priority=[x.strip() for x in env.get("PROVIDER_PRIORITY","").split(",") if x.strip()]
    return Router(providers=build_providers_from_env(env,priority or None),max_retries=int(env.get("ROUTER_MAX_RETRIES","1")))
ROUTER=build_router()
class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def _send(self,status,payload,content_type="application/json; charset=utf-8"):
        body=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.send_header("Access-Control-Allow-Origin",os.getenv("ROUTER_CORS_ORIGIN","*")); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin",os.getenv("ROUTER_CORS_ORIGIN","*")); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.send_header("Access-Control-Allow-Methods","GET,POST,DELETE,OPTIONS"); self.end_headers()
    def _json_body(self):
        try: length=int(self.headers.get("Content-Length","0"))
        except ValueError: raise ValueError("invalid Content-Length")
        if length<0 or length>MAX_BODY: raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/api/status": return self._send(200,{"providers":ROUTER.status(),"skills":ROUTER.list_skills()})
        if path=="/api/health": return self._send(200,{"ok":True,"providers":len(ROUTER.providers()),"version":"web-v2"})
        if path=="/api/skills": return self._send(200,{"skills":ROUTER.list_skills()})
        if path=="/api/conversations": return self._send(200,{"conversations":STORE.list_conversations()})
        if path.startswith("/api/conversations/"):
            item=STORE.get_conversation(path.rsplit("/",1)[-1]); return self._send(200,item) if item else self._send(404,{"error":"Conversation not found"})
        if path=="/api/analytics": return self._send(200,STORE.analytics())
        return self._static(path)
    def do_DELETE(self):
        path=urlparse(self.path).path
        if path.startswith("/api/conversations/"): STORE.delete_conversation(path.rsplit("/",1)[-1]); return self._send(200,{"ok":True})
        return self._send(404,{"error":"Not found"})
    def do_POST(self):
        path=urlparse(self.path).path
        if path=="/api/conversations":
            try:
                data=self._json_body(); messages=data.get("messages",[])
                if not isinstance(messages,list) or len(messages)>100: return self._send(400,{"error":"messages must be a list with at most 100 items"})
                return self._send(201,{"id":STORE.save_conversation(data.get("id"),data.get("title","New chat"),messages)})
            except (ValueError,json.JSONDecodeError) as exc: return self._send(400,{"error":str(exc)})
        if path!="/api/chat": return self._send(404,{"error":"Not found"})
        started=time.perf_counter(); conversation_id=None; data={}
        try:
            data=self._json_body(); messages=data.get("messages")
            if not isinstance(messages,list) or not messages or len(messages)>100: return self._send(400,{"error":"messages must be a non-empty list with at most 100 items"})
            for message in messages:
                if not isinstance(message,dict) or message.get("role") not in ("user","assistant","system","model"): return self._send(400,{"error":"invalid message format"})
                if not isinstance(message.get("content",""),str) or len(message.get("content",""))>100000: return self._send(400,{"error":"message content is invalid or too large"})
            conversation_id=data.get("conversation_id"); model=data.get("model") or None
            result=ROUTER.complete(messages,model=model,temperature=data.get("temperature"),max_tokens=data.get("max_tokens")); usage=result.get("usage") or {}
            STORE.record_request(conversation_id=conversation_id,model=result.get("model",model),provider=result.get("provider"),latency_ms=(time.perf_counter()-started)*1000,prompt_tokens=usage.get("prompt_tokens"),completion_tokens=usage.get("completion_tokens"),ok=True)
            if conversation_id: STORE.save_conversation(conversation_id,messages[0].get("content","New chat"),messages+[{"role":"assistant","content":result.get("content","")}])
            return self._send(200,result)
        except json.JSONDecodeError: return self._send(400,{"error":"invalid JSON request"})
        except ValueError as exc: return self._send(413,{"error":str(exc)})
        except Exception as exc:
            STORE.record_request(conversation_id=conversation_id,model=data.get("model"),latency_ms=(time.perf_counter()-started)*1000,ok=False,error_type=type(exc).__name__)
            return self._send(502,{"error":"Router could not complete the request","type":type(exc).__name__})
    def _static(self,path):
        target=(WEB/(path.lstrip("/") or "index.html")).resolve()
        if WEB not in target.parents and target!=WEB: return self._send(403,{"error":"Forbidden"})
        if not target.is_file(): target=WEB/"index.html"
        try: data=target.read_bytes(); return self._send(200,data,mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        except OSError: return self._send(404,{"error":"Not found"})
if __name__=="__main__":
    host=os.getenv("HOST","127.0.0.1"); port=int(os.getenv("PORT","8080")); print(f"Router Web UI: http://{host}:{port}"); ThreadingHTTPServer((host,port),Handler).serve_forever()
