# Quant Guardian

Plataforma para controlar el riesgo de cuentas de MetaTrader 5, ejecutar señales y estrategias, y ver el resultado en un portal.

El asesor en la terminal es un cliente ligero. El riesgo, las licencias, las estrategias y la cola de órdenes viven en el API.

## Qué incluye

- API FastAPI, PostgreSQL y Redis.
- Portal en React: sesión, cuentas, riesgo, estrategias, operaciones, copias y Telegram.
- Asesor `mql5/QuantGuardian.mq5`, que consulta el API por HTTP.
- Puente `mql5/mt5_bridge.py`, que mantiene un socket y ejecuta en la terminal cuando MetaTrader 5 está abierto.
- Copia de órdenes entre cuentas del mismo usuario, con el lote según la equidad.
- Avisos de Telegram y resumen a las 17:00, hora de Nueva York.
- Calendario de alto impacto (NFP, CPI, FOMC y decisiones de tipos) para pausar estrategias.

La referencia de endpoints, modelos y pruebas está en [DOCUMENTACION.md](DOCUMENTACION.md). Lo que sigue abierto está en [PENDIENTES.md](PENDIENTES.md).

## Requisitos

- Docker, para el API con PostgreSQL y Redis.
- Node.js 20 o superior, para el portal.
- Python 3.12, si va a correr el API o las pruebas fuera de Docker.
- MetaTrader 5, solo para operar de verdad.

## Arranque con Docker

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

El API queda en `http://127.0.0.1:8000`.

En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

El portal queda en `http://localhost:5173`.

## Arranque local sin Docker

Desde `backend`, con SQLite y Redis en memoria:

```bash
pip install -r requirements.txt
set DATABASE_URL=sqlite+aiosqlite:///./dev.db
set REDIS_URL=memory://
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En PowerShell las dos variables se asignan con `$env:DATABASE_URL="..."` y `$env:REDIS_URL="memory://"`.

Las pruebas:

```bash
cd backend
python -m pytest tests -q
```

## Variables

Copie `backend/.env.example` a `backend/.env`. No suba el `.env`.

| Variable | Uso |
|---|---|
| `DATABASE_URL` | Postgres en Docker, o SQLite en local |
| `REDIS_URL` | Redis. `memory://` vale para pruebas |
| `JWT_SECRET` | Firma de la sesión del portal |
| `WEBHOOK_SECRET` | Firma HMAC de cobros y del calendario manual |
| `EXPOSE_RESET_TOKENS` | Muestra el enlace de restablecimiento si no hay correo |
| `TELEGRAM_BOT_TOKEN` | Token de BotFather. El chat id se guarda en Cuentas |
| `SMTP_HOST` y el resto de `SMTP_*` | Envío del enlace de restablecimiento |
| `PUBLIC_APP_URL` | Dirección del portal dentro de ese enlace |
| `NEWS_FEED_URL` | Calendario. Vacío apaga la descarga |

## MetaTrader 5

1. Compile `mql5/QuantGuardian.mq5` en MetaEditor.
2. En Herramientas, Opciones, Asesores expertos, permita WebRequest hacia `http://127.0.0.1:8000`.
3. Pegue la licencia en el parámetro del asesor.

No corra el asesor y el puente sobre la misma cuenta. El puente toma la cola por el socket y el asesor deja de recibir esas órdenes.

```bash
pip install MetaTrader5 websockets
python mql5/mt5_bridge.py --api http://127.0.0.1:8000 --license CLAVE --account LOGIN
```

`MetaTrader5` solo se instala en Windows, con la terminal abierta.

## Base de datos

El proceso crea las tablas al arrancar. Para un Postgres nuevo también puede aplicar la revisión de Alembic desde `backend`:

```bash
alembic upgrade head
```

## Licencia de uso

El registro del portal crea el usuario. La licencia de trading sale del webhook de cobro `POST /api/v1/webhooks/billing`, firmado con `WEBHOOK_SECRET`. Stripe todavía no está conectado.
