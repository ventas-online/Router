# LLM Router — Enrutador de modelos IA gratuitos con failover automático

Herramienta en Python que **une todos tus modelos gratuitos de IA en una sola API** y, cuando uno se queda sin tokens (cuota agotada, rate limit o caída), **activa automáticamente el siguiente proveedor**.

**¿Sin tokens en OpenRouter? → salta a Cerebras → salta a Groq → salta a Gemini...** siempre hay un modelo respondiendo.

## Características

- 🔀 **Enrutador inteligente**: agrupa OpenRouter, Groq, Google Gemini, Cerebras, Mistral y Hugging Face en una sola interfaz.
- ⚡ **Failover automático**: detecta `429`, `402`, `insufficient_quota`, `rate limit` y rota al siguiente proveedor con *cooldown*.
- 🛡️ **Circuit breaker**: si un proveedor falla N veces seguidas, se abre el circuito y no se vuelve a intentar durante un periodo.
- 📊 **Seguimiento de tokens**: contabiliza uso por proveedor y lo persiste en `usage.json`; puedes fijar límites diarios por proveedor.
- 🔌 **Sistema de Skills**: añade capacidades como plugins sin tocar el núcleo.
- ⏱️ **Backoff exponencial** entre reintentos.
- 🧪 **100 % testado** con `unittest`, sin dependencias externas.
- 🐍 Sin frameworks: Python 3.9+.

## Instalación

```bash
unzip llm-router.zip && cd llm-router
python3 --version
```

## Configuración

Copia `.env.example` a `.env` y añade las API keys disponibles. Puedes configurar prioridades con `ROUTER_PRIORITY` y límites diarios con `DAILY_LIMIT_<PROVIDER>`.

## Uso rápido

```bash
python -m llmrouter.cli "Explícame qué es una red neuronal en 2 frases"
python -m llmrouter.cli "Este texto es muy largo..." --skill summarize
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Licencia

MIT
