"""Dependency-free web/API server for the Router AI workspace."""
from __future__ import annotations
import json, mimetypes, os, time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from llmrouter import Router, build_providers_from_env, load_env
from llmrouter.api_keys import ApiKeyStore, QuotaExceeded
from llmrouter.web_store import WebStore
ROOT=Path(__file__).resolve().parent
WEB=ROOT/"web"
MAX_BODY=int(os.getenv("ROUTER_MAX_BODY_BYTES","1048576"))
DB_PATH=os.getenv("ROUTER_WEB_DB",str(ROOT/"router_web.sqlite3"))
STORE=WebStore(DB_PATH)
API_KEYS=ApiKeyStore(DB_PATH)
RATE_WINDOW=int(os.getenv("ROUTER_RATE_WINDOW_SECONDS","60"))
RATE_LIMIT=int(os.getenv("ROUTER_RATE_LIMIT","30"))
AUTH_REQUIRED=os.getenv("ROUTER_AUTH_REQUIRED","1").lower() not in ("0","false","no")
SESSION_TTL=int(os.getenv("ROUTER_SESSION_TTL_SECONDS","604800"))
COOKIE_SECURE=os.getenv("ROUTER_COOKIE_SECURE","0").lower() in ("1","true","yes")
_RATE_BUCKETS=defaultdict(deque)
def build_router():
    env=load_env(); priority=[x.strip() for x in env.get("PROVIDER_PRIORITY","").split(",") if x.strip()]
    return Router(providers=build_providers_from_env(env,priority or None),max_retries=int(env.get("ROUTER_MAX_RETRIES","1")))
ROUTER=build_router()
class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def _origin(self): return os.getenv("ROUTER_CORS_ORIGIN","*")
    def _send(self,status,payload,content_type="application/json; charset=utf-8",extra_headers=None):
        body=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status)
        self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store")
        self.send_header("Access-Control-Allow-Origin",self._origin()); self.send_header("Access-Control-Allow-Credentials","true")
        if extra_headers:
            for k,v in extra_headers.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def _rate_limited(self):
        if RATE_LIMIT<=0:return False
        now=time.time(); bucket=_RATE_BUCKETS[self.client_address[0]]
        while bucket and bucket[0]<=now-RATE_WINDOW: bucket.popleft()
        if len(bucket)>=RATE_LIMIT:return True
        bucket.append(now); return False
    def _json_body(self):
        try:length=int(self.headers.get("Content-Length","0"))
        except ValueError:raise ValueError("invalid Content-Length")
        if length<0 or length>MAX_BODY:raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")
    @staticmethod
    def _valid_messages(messages,allow_empty=False):
        if not isinstance(messages,list) or (not allow_empty and not messages) or len(messages)>100:return False
        return all(isinstance(m,dict) and m.get("role") in ("user","assistant","system","model") and isinstance(m.get("content",""),str) and len(m.get("content",""))<=100000 for m in messages)
    def _session_token(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get("Cookie","")); return cookie.get("router_session").value if cookie.get("router_session") else None
        except Exception:return None
    def _current_user(self):return STORE.get_user_by_session(self._session_token())
    def _bearer_key(self):
        value=self.headers.get("Authorization",""); prefix="Bearer "; return value[len(prefix):].strip() if value.startswith(prefix) else None
    def _auth_context(self,requested_project_id=None):
        raw=self._bearer_key()
        if raw:
            auth=API_KEYS.authenticate_key(raw)
            if not auth:return self._send(401,{"error":"Invalid or revoked API key","code":"INVALID_API_KEY"}) or None
            if requested_project_id and requested_project_id!=auth["project_id"]:return self._send(403,{"error":"API key is scoped to another project","code":"PROJECT_MISMATCH"}) or None
            return {"user":{"id":auth["user_id"],"email":auth["project_name"]},"project_id":auth["project_id"],"api_key_id":auth["api_key_id"]}
        if not AUTH_REQUIRED:return {"user":{"id":"anonymous","email":"anonymous"},"project_id":requested_project_id,"api_key_id":None}
        user=self._current_user()
        if not user:self._send(401,{"error":"Authentication required","code":"AUTH_REQUIRED"}); return None
        if requested_project_id:
            if not API_KEYS.get_project(user["id"],requested_project_id):return self._send(404,{"error":"Project not found"}) or None
        return {"user":user,"project_id":requested_project_id,"api_key_id":None}
    def _require_session_user(self):
        if not AUTH_REQUIRED:return {"id":"anonymous","email":"anonymous"}
        user=self._current_user()
        if not user:self._send(401,{"error":"Authentication required","code":"AUTH_REQUIRED"}); return None
        return user
    def _set_session_cookie(self,token):
        parts=["router_session="+token,"Path=/","HttpOnly","SameSite=Lax","Max-Age="+str(SESSION_TTL)]
        if COOKIE_SECURE:parts.append("Secure")
        return {"Set-Cookie":"; ".join(parts)}
    @staticmethod
    def _clear_session_cookie():return {"Set-Cookie":"router_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"}
    @staticmethod
    def _valid_credentials(data):
        email=data.get("email") if isinstance(data,dict) else None; password=data.get("password") if isinstance(data,dict) else None
        return isinstance(email,str) and 3<=len(email.strip())<=254 and "@" in email and isinstance(password,str) and 10<=len(password)<=256
    def _quota_preflight(self,context):
        if not context.get("project_id"):return True
        try:API_KEYS.check_quota(context["project_id"]); return True
        except QuotaExceeded as exc:
            self._send(429,{"error":"Project quota exceeded","code":"QUOTA_EXCEEDED","kind":exc.kind,"limit":exc.limit,"used":exc.used}); return False
    def _record_usage(self,context,result,started,ok=True,error_type=None):
        if not context.get("project_id"):return
        usage=(result or {}).get("usage") or {}
        API_KEYS.record_usage(user_id=context["user"]["id"],project_id=context["project_id"],api_key_id=context.get("api_key_id"),model=(result or {}).get("model"),provider=(result or {}).get("provider"),prompt_tokens=usage.get("prompt_tokens"),completion_tokens=usage.get("completion_tokens"),latency_ms=(time.perf_counter()-started)*1000,ok=ok,error_type=error_type)
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin",self._origin()); self.send_header("Access-Control-Allow-Credentials","true"); self.send_header("Access-Control-Allow-Headers","Content-Type, Authorization"); self.send_header("Access-Control-Allow-Methods","GET,POST,DELETE,OPTIONS"); self.send_header("Content-Length","0"); self.end_headers()
    def do_GET(self):
        path=urlparse(self.path).path
        if path.startswith("/api/") and self._rate_limited():return self._send(429,{"error":"Too many requests"})
        if path=="/api/health":return self._send(200,{"ok":True,"providers":len(ROUTER.providers()),"version":"web-v7-projects"})
        if path=="/api/auth/me":
            user=self._current_user(); return self._send(200,{"authenticated":bool(user),"user":user})
        user=self._require_session_user() if (path=="/api/projects" or path=="/api/keys" or path.startswith("/api/projects/")) else None
        if path=="/api/projects":return self._send(200,{"projects":API_KEYS.list_projects(user["id"])}) if user else None
        if path.startswith("/api/projects/"):
            parts=path.strip("/").split("/")
            if not user:return None
            if len(parts)==3:return self._send(200,API_KEYS.get_project(user["id"],parts[2])) if API_KEYS.get_project(user["id"],parts[2]) else self._send(404,{"error":"Project not found"})
            if len(parts)==4 and parts[3]=="keys":return self._send(200,{"keys":API_KEYS.list_keys(user["id"],parts[2])})
        context=self._auth_context()
        if not context:return
        user=context["user"]
        if path=="/api/status":return self._send(200,{"providers":ROUTER.status(),"skills":ROUTER.list_skills()})
        if path=="/api/skills":return self._send(200,{"skills":ROUTER.list_skills()})
        if path=="/api/conversations":return self._send(200,{"conversations":STORE.list_conversations(user["id"])})
        if path.startswith("/api/conversations/"):
            item=STORE.get_conversation(user["id"],path.rsplit("/",1)[-1]); return self._send(200,item) if item else self._send(404,{"error":"Conversation not found"})
        if path=="/api/analytics":return self._send(200,STORE.analytics(user["id"]))
        if path.startswith("/api/usage/"):
            project_id=path.rsplit("/",1)[-1]
            if not API_KEYS.get_project(user["id"],project_id):return self._send(404,{"error":"Project not found"})
            if context.get("project_id") and project_id!=context["project_id"]:return self._send(403,{"error":"Forbidden"})
            return self._send(200,API_KEYS.usage_report(user["id"],project_id))
        return self._static(path)
    def do_DELETE(self):
        path=urlparse(self.path).path
        if self._rate_limited():return self._send(429,{"error":"Too many requests"})
        user=self._require_session_user()
        if not user:return
        if path.startswith("/api/projects/"):
            parts=path.strip("/").split("/")
            if len(parts)==3:
                ok=API_KEYS.delete_project(user["id"],parts[2]); return self._send(200,{"ok":ok}) if ok else self._send(404,{"error":"Project not found"})
            if len(parts)==5 and parts[3]=="keys":
                ok=API_KEYS.revoke_key(user["id"],parts[2],parts[4]); return self._send(200,{"ok":ok}) if ok else self._send(404,{"error":"API key not found"})
        if path.startswith("/api/conversations/"):
            STORE.delete_conversation(user["id"],path.rsplit("/",1)[-1]); return self._send(200,{"ok":True})
        return self._send(404,{"error":"Not found"})
    def _stream_chat(self,data,messages,conversation_id,started,context):
        self.send_response(200); self.send_header("Content-Type","text/event-stream; charset=utf-8"); self.send_header("Cache-Control","no-cache, no-transform"); self.send_header("Connection","keep-alive"); self.send_header("Access-Control-Allow-Origin",self._origin()); self.send_header("Access-Control-Allow-Credentials","true"); self.end_headers()
        answer=[]; usage={}; meta={}
        try:
            for event in ROUTER.stream(messages,model=data.get("model") or None,temperature=data.get("temperature"),max_tokens=data.get("max_tokens")):
                if event.get("type")=="delta":answer.append(event.get("content",""))
                if event.get("type")=="usage":usage=event.get("usage") or usage
                meta.update({k:event[k] for k in ("model","provider") if k in event}); self.wfile.write(("data: "+json.dumps(event,ensure_ascii=False)+"\n\n").encode()); self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush(); result={"content":"".join(answer),"model":meta.get("model"),"provider":meta.get("provider"),"usage":usage}
            STORE.record_request(user_id=context["user"]["id"],conversation_id=conversation_id,model=result.get("model"),provider=result.get("provider"),latency_ms=(time.perf_counter()-started)*1000,prompt_tokens=usage.get("prompt_tokens"),completion_tokens=usage.get("completion_tokens"),ok=True); self._record_usage(context,result,started,True)
            if conversation_id:STORE.save_conversation(context["user"]["id"],conversation_id,next((m.get("content","New chat") for m in messages if m.get("role")=="user"),"New chat"),messages+[{"role":"assistant","content":result["content"]}])
        except Exception as exc:
            STORE.record_request(user_id=context["user"]["id"],conversation_id=conversation_id,model=data.get("model"),latency_ms=(time.perf_counter()-started)*1000,ok=False,error_type=type(exc).__name__); self._record_usage(context,{"model":data.get("model")},started,False,type(exc).__name__)
            try:self.wfile.write(("data: "+json.dumps({"type":"error","error":"Router could not complete the request","code":type(exc).__name__})+"\n\n").encode()); self.wfile.flush()
            except OSError:pass
    def do_POST(self):
        path=urlparse(self.path).path
        if self._rate_limited():return self._send(429,{"error":"Too many requests"})
        try:data=self._json_body()
        except (ValueError,json.JSONDecodeError) as exc:return self._send(400 if isinstance(exc,json.JSONDecodeError) else 413,{"error":str(exc)})
        if path=="/api/auth/register":
            if not self._valid_credentials(data):return self._send(400,{"error":"Use a valid email and a password of at least 10 characters"})
            user=STORE.create_user(data["email"],data["password"])
            if not user:return self._send(409,{"error":"An account with that email already exists"})
            token=STORE.create_session(user["id"],SESSION_TTL); return self._send(201,{"user":user},extra_headers=self._set_session_cookie(token))
        if path=="/api/auth/login":
            if not self._valid_credentials(data):return self._send(400,{"error":"Invalid credentials"})
            user=STORE.authenticate_user(data["email"],data["password"])
            if not user:return self._send(401,{"error":"Invalid email or password"})
            token=STORE.create_session(user["id"],SESSION_TTL); return self._send(200,{"user":user},extra_headers=self._set_session_cookie(token))
        if path=="/api/auth/logout":STORE.delete_session(self._session_token()); return self._send(200,{"ok":True},extra_headers=self._clear_session_cookie())
        user=self._require_session_user()
        if not user:return
        if path=="/api/projects":
            try:rq=int(data.get("requests_per_day",1000)); tk=int(data.get("tokens_per_day",1000000))
            except (TypeError,ValueError):return self._send(400,{"error":"Quota limits must be integers"})
            if rq<0 or tk<0:return self._send(400,{"error":"Quota limits cannot be negative"})
            return self._send(201,{"project":API_KEYS.create_project(user["id"],data.get("name","Default project"),rq,tk)})
        if path.startswith("/api/projects/") and path.endswith("/keys"):
            parts=path.strip("/").split("/")
            if len(parts)!=4:return self._send(404,{"error":"Not found"})
            created=API_KEYS.create_key(user["id"],parts[2],data.get("name","API key")); return self._send(201,created) if created else self._send(404,{"error":"Project not found"})
        if path=="/api/conversations":
            messages=data.get("messages",[])
            if not self._valid_messages(messages,allow_empty=True):return self._send(400,{"error":"invalid messages: expected up to 100 valid messages"})
            title=data.get("title","New chat")
            if not isinstance(title,str):return self._send(400,{"error":"title must be a string"})
            return self._send(201,{"id":STORE.save_conversation(user["id"],data.get("id"),title,messages)})
        if path!="/api/chat":return self._send(404,{"error":"Not found"})
        requested_project=data.get("project_id")
        if requested_project is not None and not isinstance(requested_project,str):return self._send(400,{"error":"project_id must be a string"})
        context=self._auth_context(requested_project)
        if not context:return
        if not self._quota_preflight(context):return
        started=time.perf_counter(); conversation_id=None
        try:
            messages=data.get("messages")
            if not self._valid_messages(messages):return self._send(400,{"error":"invalid messages: expected 1-100 valid messages"})
            conversation_id=data.get("conversation_id")
            if conversation_id is not None and not isinstance(conversation_id,str):return self._send(400,{"error":"conversation_id must be a string"})
            if conversation_id and not STORE.get_conversation(context["user"]["id"],conversation_id):return self._send(404,{"error":"Conversation not found"})
            if data.get("stream") is True:return self._stream_chat(data,messages,conversation_id,started,context)
            result=ROUTER.complete(messages,model=data.get("model") or None,temperature=data.get("temperature"),max_tokens=data.get("max_tokens")); usage=result.get("usage") or {}
            STORE.record_request(user_id=context["user"]["id"],conversation_id=conversation_id,model=result.get("model",data.get("model")),provider=result.get("provider"),latency_ms=(time.perf_counter()-started)*1000,prompt_tokens=usage.get("prompt_tokens"),completion_tokens=usage.get("completion_tokens"),ok=True); self._record_usage(context,result,started,True)
            if conversation_id:STORE.save_conversation(context["user"]["id"],conversation_id,next((m.get("content","New chat") for m in messages if m.get("role")=="user"),"New chat"),messages+[{"role":"assistant","content":result.get("content","")}])
            return self._send(200,result)
        except Exception as exc:
            STORE.record_request(user_id=context["user"]["id"],conversation_id=conversation_id,model=data.get("model"),latency_ms=(time.perf_counter()-started)*1000,ok=False,error_type=type(exc).__name__); self._record_usage(context,{"model":data.get("model")},started,False,type(exc).__name__); return self._send(502,{"error":"Router could not complete the request","type":type(exc).__name__})
    def _static(self,path):
        target=(WEB/(path.lstrip("/") or "index.html")).resolve()
        if WEB not in target.parents and target!=WEB:return self._send(403,{"error":"Forbidden"})
        if not target.is_file():target=WEB/"index.html"
        try:return self._send(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        except OSError:return self._send(404,{"error":"Not found"})
if __name__=="__main__":
    host=os.getenv("HOST","127.0.0.1"); port=int(os.getenv("PORT","8080")); print(f"Router Web UI: http://{host}:{port}"); ThreadingHTTPServer((host,port),Handler).serve_forever()
