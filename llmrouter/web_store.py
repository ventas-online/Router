"""Dependency-free SQLite persistence for the Router web workspace."""
from __future__ import annotations
import hashlib,hmac,json,secrets,sqlite3,threading,time,uuid
from pathlib import Path
class WebStore:
 def __init__(self,path="router_web.sqlite3"):self.path=str(Path(path));self._lock=threading.Lock();self._init()
 def _connect(self):
  c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row;c.execute("PRAGMA foreign_keys=ON");return c
 def _init(self):
  with self._lock,self._connect() as db:
   db.executescript("""CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at REAL NOT NULL);CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,created_at REAL NOT NULL,expires_at REAL NOT NULL);CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,user_id TEXT,title TEXT NOT NULL,messages TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,conversation_id TEXT,model TEXT,provider TEXT,latency_ms INTEGER,prompt_tokens INTEGER DEFAULT 0,completion_tokens INTEGER DEFAULT 0,ok INTEGER NOT NULL,error_type TEXT,created_at REAL NOT NULL);CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id,updated_at);CREATE INDEX IF NOT EXISTS idx_requests_user_created ON requests(user_id,created_at);""");self._ensure_column(db,"conversations","user_id","TEXT");self._ensure_column(db,"requests","user_id","TEXT")
 @staticmethod
 def _ensure_column(db,t,c,d):
  if c not in {r[1] for r in db.execute(f"PRAGMA table_info({t})")}:db.execute(f"ALTER TABLE {t} ADD COLUMN {c} {d}")
 @staticmethod
 def _hash_password(password,salt=None):
  salt=salt or secrets.token_bytes(16);digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210_000);return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"
 @staticmethod
 def _verify_password(password,encoded):
  try:
   scheme,rounds,salt,digest=encoded.split("$",3)
   return scheme=="pbkdf2_sha256" and hmac.compare_digest(hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),int(rounds)).hex(),digest)
  except (ValueError,TypeError):return False
 @staticmethod
 def _token_hash(token):return hashlib.sha256(token.encode("ascii")).hexdigest()
 @staticmethod
 def _normalize_email(email):return email.strip().lower()
 def create_user(self,email,password):
  email=self._normalize_email(email);now=time.time();uid=uuid.uuid4().hex
  with self._lock,self._connect() as db:
   try:db.execute("INSERT INTO users VALUES(?,?,?,?)",(uid,email,self._hash_password(password),now))
   except sqlite3.IntegrityError:return None
  return {"id":uid,"email":email,"created_at":now}
 def authenticate_user(self,email,password):
  with self._lock,self._connect() as db:r=db.execute("SELECT * FROM users WHERE email=?",(self._normalize_email(email),)).fetchone()
  if not r or not self._verify_password(password,r["password_hash"]):return None
  return {"id":r["id"],"email":r["email"],"created_at":r["created_at"]}
 def create_session(self,user_id,ttl_seconds=604800):
  token=secrets.token_urlsafe(32);now=time.time()
  with self._lock,self._connect() as db:db.execute("INSERT INTO sessions VALUES(?,?,?,?)",(self._token_hash(token),user_id,now,now+int(ttl_seconds)))
  return token
 def get_user_by_session(self,token):
  if not token:return None
  with self._lock,self._connect() as db:r=db.execute("SELECT u.id,u.email,u.created_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",(self._token_hash(token),time.time())).fetchone()
  return dict(r) if r else None
 def delete_session(self,token):
  if token:
   with self._lock,self._connect() as db:db.execute("DELETE FROM sessions WHERE token_hash=?",(self._token_hash(token),))
 def save_conversation(self,user_id=None,conversation_id=None,title=None,messages=None):
  if messages is None:messages=title;title=conversation_id;conversation_id=None;user_id=None
  now=time.time();conversation_id=conversation_id or uuid.uuid4().hex
  with self._lock,self._connect() as db:db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,messages=excluded.messages,updated_at=excluded.updated_at",(conversation_id,user_id,title[:120] or "New chat",json.dumps(messages,ensure_ascii=False),now,now))
  return conversation_id
 def get_conversation(self,user_id=None,conversation_id=None):
  if conversation_id is None:conversation_id=user_id;user_id=None
  with self._lock,self._connect() as db:
   r=db.execute("SELECT * FROM conversations WHERE id=? AND (user_id=? OR ? IS NULL)",(conversation_id,user_id,user_id)).fetchone()
  if not r:return None
  x=dict(r);x["messages"]=json.loads(x["messages"]);return x
 def list_conversations(self,user_id=None,limit=30):
  with self._lock,self._connect() as db:
   if user_id is None:r=db.execute("SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",(int(limit),)).fetchall()
   else:r=db.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",(user_id,int(limit))).fetchall()
  return [dict(x) for x in r]
 def delete_conversation(self,user_id=None,conversation_id=None):
  if conversation_id is None:conversation_id=user_id;user_id=None
  with self._lock,self._connect() as db:
   if user_id is None:db.execute("DELETE FROM conversations WHERE id=?",(conversation_id,))
   else:db.execute("DELETE FROM conversations WHERE id=? AND user_id=?",(conversation_id,user_id))
 def record_request(self,**d):
  with self._lock,self._connect() as db:db.execute("INSERT INTO requests(user_id,conversation_id,model,provider,latency_ms,prompt_tokens,completion_tokens,ok,error_type,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(d.get("user_id"),d.get("conversation_id"),d.get("model"),d.get("provider"),int(d.get("latency_ms") or 0),int(d.get("prompt_tokens") or 0),int(d.get("completion_tokens") or 0),1 if d.get("ok") else 0,d.get("error_type"),time.time()))
 def analytics(self,user_id=None,hours=24):
  since=time.time()-int(hours)*3600
  with self._lock,self._connect() as db:
   where="user_id=? AND created_at>=?" if user_id is not None else "created_at>=?";args=(user_id,since) if user_id is not None else (since,)
   total=db.execute(f"SELECT COUNT(*) n FROM requests WHERE {where}",args).fetchone()["n"];ok=db.execute(f"SELECT COUNT(*) n FROM requests WHERE {where} AND ok=1",args).fetchone()["n"];avg=db.execute(f"SELECT AVG(latency_ms) n FROM requests WHERE {where} AND ok=1",args).fetchone()["n"]
   rows=db.execute(f"SELECT COALESCE(provider,'unknown') provider,COUNT(*) requests,SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) successes,SUM(prompt_tokens+completion_tokens) tokens FROM requests WHERE {where} GROUP BY provider ORDER BY requests DESC",args).fetchall()
  return {"hours":int(hours),"requests":total,"successes":ok,"success_rate":round(ok/total*100,2) if total else 0,"avg_latency_ms":round(avg,1) if avg is not None else 0,"providers":[dict(r) for r in rows]}
