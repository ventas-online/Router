"""Ejemplo básico de uso del router en Python."""
from llmrouter import Router, build_providers_from_env, load_env

env = load_env()
router = Router(
    providers=build_providers_from_env(env),
    daily_limits={k: int(v) for k, v in env.items() if k.startswith("DAILY_LIMIT_") and v},
)

if not router.providers():
    print("Sin API keys todavía: copia .env.example a .env y pega al menos una clave.")
else:
    resp = router.complete([{"role": "user", "content": "Dime quién eres en una frase."}])
    print(resp["content"])
    print("→ respondió:", resp["provider"], "| modelo:", resp["model"], "| uso:", resp.get("usage"))

print("\nSkills disponibles:", [s["name"] for s in router.list_skills()])
if router.providers():
    print("Traducción:", router.run_skill("translate", text="¿Cómo estás?", to="inglés"))
