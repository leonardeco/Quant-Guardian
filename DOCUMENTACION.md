# Documentación Técnica del Sistema
## Plataforma SaaS de Trading Cuantitativo, Risk Guardian y Ejecución Automatizada
**Versión:** 0.2.0 | **Fecha:** Octubre 2026  
**Estado:** Core Backend, Motor Cuantitativo, Conector MQL5, Portal Web y Tests Automatizados Operativos.

---

## 1. Arquitectura General del Sistema

El sistema implementa una arquitectura híbrida **Thin-Client (Cliente Ligero) + Servidor Centralizado (FastAPI + Redis + PostgreSQL)**:

```
┌────────────────────────────────────────────────────────┐
│             TradingView / Webhooks / API               │
└───────────────────────────┬────────────────────────────┘
                            │ (HMAC-SHA256)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   FastAPI Backend Core                 │
│  - Control de Licencias y Suscripciones (Triple Check) │
│  - Risk Guardian Centralizado (Kill-Switch)            │
│  - Motor Cuantitativo (Session Breakout, Z-Score)      │
│  - Conversión Dinámica de Lote (Piso estricto por paso)│
│  - Analytics & Dashboard API (JWT)                     │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               ▼                          ▼
     ┌──────────────────┐       ┌──────────────────┐
     │   PostgreSQL 15  │       │     Redis 7      │
     │  (Persistencia   │       │  (Velas, Colas   │
     │   ACID & Datos)  │       │  e Idempotencia) │
     └──────────────────┘       └──────────────────┘
               ▲
               │ Telemetría / Velas / Órdenes / Trades
               ▼
┌────────────────────────────────────────────────────────┐
│            Terminal MetaTrader 5 (MQL5 EA)             │
│  - QuantGuardian.mq5 (Thin Client)                     │
│  - Heartbeat de Equity & Monitoreo de Drawdown         │
│  - Ejecución de Kill-Switch Local (FORCE_FLAT)         │
│  - Envío de Velas Cerradas + Normalización UTC         │
│  - Auditoría de Deals cerrados (OnTradeTransaction)    │
└────────────────────────────────────────────────────────┘
```

---

## 2. Componentes Implementados

### 2.1. Backend Core (`backend/app/`)

* **`config.py`**: Configuración centralizada vía Pydantic Settings (`BaseSettings`), variables de entorno para PostgreSQL, Redis, secretos de JWT, webhook secrets y orígenes CORS.
* **`db.py`**: Conexión asíncrona a base de datos con SQLAlchemy 2.0 (`create_async_engine`, `async_sessionmaker`).
* **`models.py`**: Modelo relacional completo con 8 tablas principales:
  1. `users`: Credenciales, email y fechas de creación.
  2. `subscriptions`: Relación con el usuario, plan (`starter`, `quant_pro`, `institutional`) y estado de cobro (`active`, `trialing`, `past_due`, `canceled`).
  3. `licenses`: Llaves criptográficas únicas (`license_key`), vinculadas a la suscripción, con estado y marca de último heartbeat.
  4. `trading_accounts`: Cuentas MT5 asociadas a una licencia (`account_number`, `broker_server`, `initial_balance`).
  5. `risk_profiles`: Umbrales de protección financiera (Drawdown diario máximo %, Drawdown total máximo %, límite de operaciones abiertas, riesgo por trade %, filtro de noticias).
  6. `strategy_configs`: Configuración algorítmica por cuenta y símbolo, parámetros dinámicos en formato JSON y flag de activación.
  7. `trade_executions`: Registro histórico de órdenes con restricción de unicidad `(trading_account_id, ticket)` para garantizar idempotencia en reintentos.
  8. `equity_snapshots`: Serie temporal de balance, equidad, PnL flotante, High Water Mark (HWM), equidad de inicio del día y operaciones abiertas.
  9. `copy_links`: Vínculo de una cuenta maestra con una seguidora. La seguidora solo puede tener una maestra.
* **`security.py`**:
  * Autenticación con contraseñas seguras usando derivación criptográfica nativa `hashlib.scrypt` (resistente a ataques de GPU, sin problemas de compatibilidad con librerías externas).
  * Generación y validación de tokens JWT (`HS256`) con expiración configurable.
  * Protección de endpoints de usuario con `HTTPBearer` (`get_current_user`).
* **`risk.py`**:
  * **Risk Guardian**: Motor de evaluación matemático puro (sin dependencias I/O):
    * `FORCE_FLAT`: Activación del Kill-Switch si el Drawdown Diario o Total supera el umbral configurado.
    * `BLOCK_NEW`: Bloqueo de aperturas adicionales si se alcanza el número máximo de operaciones abiertas.
    * `ALLOW`: Operación permitida dentro de los parámetros de riesgo.
  * **Position Sizing**: Cálculo de lotaje dinámico basado en % de riesgo sobre el capital y distancia del Stop Loss, aplicando función piso (`floor`) al tamaño de paso (`volume_step`) del broker para asegurar que el riesgo real nunca exceda el porcentaje configurado.
* **`strategies.py`**:
  * **Session Breakout & Sweep**: Identifica rango asiático (00:00 - 07:00 UTC) y opera rupturas o barridos de liquidez en la apertura de Londres (07:00 - 12:00 UTC) con SL dinámico basado en ATR y multiplicador R:R.
  * **Z-Score Reversion**: Detección de sobre-extensión estadística sobre la media móvil de precios de cierre; entrada en contratendencia cuando $|Z| \ge \text{umbral}$, con toma de beneficios en la media.
  * **News Blackout**: Filtro de exclusión operativa en una ventana temporal previa y posterior a eventos macroeconómicos de alto impacto.
* **`engine.py`**:
  * Normalización horaria: conversión del tiempo de servidor del broker a UTC mediante `utc_offset`.
  * Búfer de velas en Redis con retención de hasta 500 barras por cuenta y símbolo.
  * Cola de órdenes atómica en Redis con expiración automática de 1 hora (evita ejecuciones tardías de órdenes viejas) e idempotencia por `signal_uid` con retención de 7 días.
  * Conversión de señales a especificaciones del broker (`point`, `tick_size`, `tick_value`, `vol_min`, `vol_step`, `vol_max`).
* **`analytics.py`**:
  * Métricas cuantitativas: Win Rate, Factor de Beneficio (Profit Factor), Esperanza Matemática (Expectancy), Ganancia/Pérdida promedio y Drawdown Máximo Porcentual histórico.
* **`dashboard.py`**: Router modular protegido por JWT para el portal de clientes (gestión de cuentas, perfiles de riesgo, estrategias y reporte de analítica).
* **`main.py`**: Orquestador principal de FastAPI con endpoints para pasarela de pagos, activación de licencias, heartbeat, reporte de trades, ingesta de señales y entrega de órdenes pendientes.

---

### 2.2. Conector MT5 (`mql5/QuantGuardian.mq5`)

* **Activación de Licencia**: Comunicación inicial en `OnInit` para registrar y validar la cuenta contra el backend.
* **Heartbeat & Kill-Switch**: Envío periódico (cada 5 segundos) del balance, equidad, equidad inicial del día y posiciones abiertas. Si el servidor responde `FORCE_FLAT`, el EA ejecuta el cierre inmediato de todas las posiciones con su Magic Number y borra órdenes pendientes.
* **Gestión de Suscripciones**: Detección de códigos HTTP `402 Payment Required` (suscripción impagada) o `403 Forbidden` (licencia cancelada/revocada), pausando la operativa y emitiendo alertas sonoras/visuales en el terminal.
* **Ingesta Automática de Velas**: Envío de velas cerradas en cada apertura de barra hacia el backend con sus especificaciones de trading completas.
* **Auditoría de Trades Cerrados**: Monitoreo de eventos en `OnTradeTransaction`, recopilando precio ponderado (VWAP), comisiones, swap y PnL neto, enviándolos al endpoint `/terminal/trades` con reintentos automáticos en caso de pérdida de conexión.
* **Puente alternativo** (`mql5/mt5_bridge.py`): socket persistente en la misma máquina que la terminal. Ejecuta órdenes y el `FORCE_FLAT` sin el poll de 500 ms. No debe correr junto con el EA sobre la misma cuenta.

---

## 3. Catálogo de Endpoints API

### Pasarela y Facturación
* `POST /api/v1/webhooks/billing`  
  * **Auth:** Cabecera `X-Signature` (HMAC-SHA256).
  * **Función:** Procesa eventos de cobro (`subscription.created`, `subscription.updated`). Genera y revoca licencias automáticamente.

### Terminal MetaTrader 5
* `POST /api/v1/license/activate`  
  * **Payload:** `{ license_key, account_number, broker_server, initial_balance }`
  * **Función:** Vincula la terminal con la licencia del usuario.
* `POST /api/v1/telemetry/heartbeat`  
  * **Auth:** Cabecera `X-License-Key`.
  * **Función:** Registra snapshot de equidad y devuelve la acción de riesgo (`ALLOW`, `BLOCK_NEW`, `FORCE_FLAT`).
* `POST /api/v1/terminal/trades`  
  * **Auth:** Cabecera `X-License-Key`.
  * **Función:** Registra operaciones cerradas para analítica. Idempotente por `(account, ticket)`.
* `GET /api/v1/terminal/pending?account_number={acc}`  
  * **Auth:** Cabecera `X-License-Key`.
  * **Función:** Extrae y vacía atómicamente la cola de órdenes pendientes para la cuenta. Si hay un socket vivo para esa cuenta, responde vacío: el socket es el único consumidor.
* `WS /ws/v1/terminal/stream?license_key={key}&account_number={acc}`  
  * **Auth:** Query string (el puente no puede firmar cabeceras en el upgrade).
  * **Función:** Empuja órdenes en cuanto se encolan y el resultado de riesgo (`ALLOW`, `BLOCK_NEW`, `FORCE_FLAT`) en cuanto llega un heartbeat. El cliente envía `{"type":"heartbeat",...}`.

### Ingesta de Señales y Datos de Mercado
* `POST /api/v1/signals/ingest`  
  * **Auth:** Validación de `license_key` en el payload JSON (compatible con Webhooks de TradingView).
  * **Función:** Encola señales externas con deduplicación por `signal_uid`.
* `POST /api/v1/market/candles`  
  * **Auth:** Cabecera `X-License-Key`.
  * **Función:** Recibe velas cerradas del EA, ejecuta las estrategias configuradas y encola órdenes automáticas.
* `POST /api/v1/market/news`  
  * **Auth:** Cabecera `X-Signature` (HMAC-SHA256).
  * **Función:** Actualiza las fechas y horas de eventos económicos de alto impacto.
  * El proceso también consulta `NEWS_FEED_URL` (por defecto el calendario semanal público) cada `NEWS_REFRESH_HOURS` y se queda solo con NFP, CPI, FOMC y decisiones de tipos de impacto alto.

### Dashboard de Usuario (JWT)
* `POST /api/v1/auth/register`: Registro de usuario y retorno de Bearer Token.
* `POST /api/v1/auth/login`: Autenticación con email y contraseña.
* `GET /api/v1/me`: Consulta de licencias, planes y `telegram_chat_id` del usuario autenticado.
* `PUT /api/v1/me/telegram`: Guarda el chat de Telegram. Sin `TELEGRAM_BOT_TOKEN` no se envía nada.
* `GET /api/v1/me/accounts`: Lista de cuentas vinculadas con balance, equidad, drawdown diario/total, acción y nivel (`NORMAL`, `ALERT`, `KILL`).
* `GET / PUT /api/v1/me/accounts/{account_id}/risk`: Consulta y modificación del perfil de riesgo (drawdowns, lotes, filtros).
* `GET / POST / PATCH /api/v1/me/accounts/{account_id}/strategies`: Gestión de estrategias algorítmicas por par.
* `GET / POST / DELETE /api/v1/me/copies`: Vínculos de copia entre cuentas del mismo usuario. La orden de la maestra se encola en la seguidora con el lote proporcional a la equidad. El stop y el take profit se copian igual. Un solo salto: la seguidora no vuelve a copiar.
* `GET /api/v1/analytics/performance?account_id={id}&limit=50&offset=0`: Reporte de métricas sobre todo el historial filtrado, curva de equidad y página de operaciones (`trades_total`). `date_from` y `date_to` son opcionales.
* `POST /api/v1/auth/forgot-password`: Solicitud de restablecimiento. Responde siempre 200. Si `SMTP_HOST` está configurado, envía el enlace a `/restablecer`. El token en claro solo vuelve cuando el correo no se pudo enviar y `EXPOSE_RESET_TOKENS` está activo.
* `POST /api/v1/auth/reset-password`: Cambia la contraseña con un token de un solo uso, vigente 30 minutos.
* `GET /health`: Comprobación de vida del proceso.

El heartbeat responde `action` (`ALLOW`, `BLOCK_NEW`, `FORCE_FLAT`) y `level` (`NORMAL`, `ALERT` al 80% de un límite de drawdown, `KILL`). El EA solo actúa sobre `action`.

---

## 4. Estado de Pruebas Automatizadas

El proyecto cuenta con **33 pruebas automatizadas** del backend (SQLite y Redis en memoria):
* `test_core.py`: Evaluación matemática de riesgo, dimensionamiento de lote, activación de licencias, suspensión por impago, revocación y aislamiento de colas entre licencias.
* `test_strategies.py`: Lógica de Session Breakout (ruptura y barrido), Z-Score Reversion y filtro de noticias macroeconómicas.
* `test_engine.py`: Normalización de desfase UTC, conversión de precio a puntos del broker, ingesta de velas a señales de trading y desactivación selectiva de estrategias.
* `test_dashboard.py`: Registro, login y restablecimiento de contraseña, edición multi-tenant de perfiles de riesgo, reporte de transacciones, paginación y nivel de alerta.
* `test_live.py`: Entrega de órdenes por WebSocket, bloqueo del polling mientras el socket está conectado y push inmediato de `FORCE_FLAT`.
* `test_copier.py`: Vínculo maestra–seguidora, escalado de lote por equidad y copia de un cierre.
* `test_telegram.py`: Aviso al pasar a alerta o kill-switch, cierre notificado una sola vez y resumen de las 17:00 hora de Nueva York.
* `test_news_mail.py`: Filtro del calendario y envío del enlace de restablecimiento sin devolver el token.

**Resultado de ejecución:**
```
33 passed
```
