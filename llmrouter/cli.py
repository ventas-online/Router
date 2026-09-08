"""Interfaz de línea de comandos del router."""
from __future__ import annotations
import argparse,sys
from . import __version__
from .core.router import Router
from .env import load_env
from .providers import build_providers_from_env

def main(argv=None):
    parser=argparse.ArgumentParser(prog="llmrouter",description="Enrutador de modelos IA gratuitos con failover automático.")
    parser.add_argument("message",nargs="*"); parser.add_argument("--model"); parser.add_argument("--temperature",type=float); parser.add_argument("--max-tokens",type=int); parser.add_argument("--skill"); parser.add_argument("--input",action="append",default=[]); parser.add_argument("--list-skills",action="store_true"); parser.add_argument("--status",action="store_true"); parser.add_argument("--version",action="store_true"); args=parser.parse_args(argv)
    if args.version: print(f"llmrouter {__version__}"); return 0
    env=load_env(); priority=[x.strip() for x in env.get("ROUTER_PRIORITY","").split(",") if x.strip()] or None
    providers=build_providers_from_env(env,priority=priority,cooldown_seconds=float(env.get("ROUTER_COOLDOWN_SECONDS",300)),failure_threshold=int(env.get("ROUTER_FAILURE_THRESHOLD",3)))
    limits={k:int(v) for k,v in env.items() if k.startswith("DAILY_LIMIT_") and str(v).isdigit() and int(v)>0}; router=Router(providers,limits)
    if args.list_skills:
        for s in router.list_skills(): print(f"- {s['name']}: {s['description']}")
        return 0
    if args.status:
        for s in router.status(): print(s)
        return 0
    if args.skill:
        inputs={};
        for kv in args.input:
            if "=" in kv: k,v=kv.split("=",1); inputs[k.strip()]=v.strip()
        print(router.run_skill(args.skill,**inputs)); return 0
    text=" ".join(args.message).strip()
    if not text: parser.print_help(); return 1
    if not providers: print("No hay proveedores configurados.",file=sys.stderr); return 2
    try: print(router.complete([{"role":"user","content":text}],model=args.model,temperature=args.temperature,max_tokens=args.max_tokens)["content"]); return 0
    except Exception as e: print(f"Error: {e}",file=sys.stderr); return 3
if __name__=="__main__": sys.exit(main())
