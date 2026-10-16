# Roadmap de Pendientes y Próximos Pasos
## Plataforma SaaS de Trading Cuantitativo y Risk Guardian
**Fecha:** Octubre 2026 | **Priorización de Tareas según SRS / SDD**

---

## Matriz de Estado General

| Módulo / Componente | Estado Actual | Prioridad |
|---|---|---|
| **Core Backend & Base de Datos** | ✅ Completado (33/33 tests) | Baja (Mantenimiento) |
| **Risk Guardian & Position Sizing** | ✅ Completado | Media (Ajustes finos) |
| **Estrategias Cuantitativas Base** | ✅ Completado | Media (Backtesting) |
| **Conector MQL5 (Polling WebRequest)** | ✅ Completado | Media (Validación en MT5) |
| **Frontend Web Dashboard (React)** | ✅ Portal local en `/frontend` | Baja |
| **Canal WebSocket de Ultra Baja Latencia**| ✅ Canal y puente listos | 🟡 Media (prueba en terminal) |
| **Copiadora (Trade Copier)** | ✅ Copia directa entre cuentas propias | Baja |
| **Bot de Notificaciones (Telegram)**| ✅ Avisos y resumen diario | 🟢 Baja (falta el token) |
| **Automatización del Calendario Económico**| ✅ Feed de alto impacto | Baja |
| **Integración Real Stripe / LemonSqueezy** | ⏳ **Pendiente** | 🟡 **Media** |
| **Migraciones Formales con Alembic** | ✅ Revisión inicial | Baja |

---

## 1. Tareas Inmediatas de Alta Prioridad

### 1.1. Frontend Web Dashboard (React + TypeScript + Tailwind)
> **Objetivo:** Portal web interactivo y responsive para que los traders gestionen sus cuentas, supervisen el riesgo en vivo y ajusten sus estrategias algorítmicas.
- [x] **Inicialización del Proyecto:** Configuración con Vite + React 19 + TypeScript + Tailwind CSS en la carpeta `/frontend`.
- [x] **Módulo de Autenticación:** Formularios de Registro, Inicio de Sesión y recuperación de contraseña conectados a `/api/v1/auth/*`.
  - [x] **Correo del enlace de reset.** Sale por SMTP si `SMTP_HOST` está definido. Sin servidor, y con `EXPOSE_RESET_TOKENS=true`, el portal sigue mostrando el enlace.
- [x] **Panel de Control Principal (Overview):**
  - [x] Tarjetas KPI: Balance, Equidad en tiempo real, PnL flotante, Drawdown diario actual vs límite, Drawdown total vs límite.
  - [x] Semáforo visual del estado del Risk Guardian (`NORMAL`, `ALERTA`, `KILL-SWITCH`).
  - [x] Gráfico de Curva de Equidad (Equity vs Balance) con Recharts.
- [x] **Gestión de Cuentas y Licencias:**
  - [x] Visualización de la licencia activa, plan contratado y estado de la suscripción.
  - [x] Alta y vinculación de terminales MT5 por número de cuenta y servidor.
- [x] **Editor de Parámetros de Riesgo:**
  - [x] Sliders para Max Daily Drawdown %, Max Total Drawdown %, Límite de Operaciones Simultáneas y Riesgo por Trade %.
  - [x] Toggle para activar/desactivar el filtro de noticias macroeconómicas.
- [x] **Gestión de Estrategias Cuantitativas:**
  - [x] Selector por cuenta y par de divisas (EURUSD, GBPUSD, XAUUSD, etc.).
  - [x] Formulario dinámico para ajustar parámetros de Session Breakout y Z-Score.
  - [x] Interruptor instantáneo para pausar o reactivar estrategias individualmente.
- [x] **Historial y Auditoría de Operaciones:**
  - [x] Tabla paginada de trades cerrados reportados por el EA.
  - [x] Resumen de métricas: Win Rate %, Profit Factor, Expectancy, Ganancia/Pérdida media.

---

### 1.2. Canal WebSocket Full-Duplex (< 25ms de Latencia) - ADR-01
> **Objetivo:** Sustituir la latencia de ~500ms del polling HTTP de MQL5 por comunicación bidireccional instantánea.
- [x] **Endpoint WebSocket en Backend:** `/ws/v1/terminal/stream` en FastAPI con autenticación por query param.
- [x] **Puente Local Python:** `mql5/mt5_bridge.py` mantiene el socket y ejecuta con la librería `MetaTrader5` cuando la terminal está abierta. Sin terminal, imprime la orden.
  - *Opción B (no usada):* WebSocket directo desde el EA. El asesor sigue en polling y cede la cola si el puente está conectado.
- [x] **Despacho Inmediato de Emergencia:** Al evaluar el heartbeat, el servidor empuja `FORCE_FLAT` por el socket sin esperar el siguiente poll.

---

### 1.3. Copiadora entre cuentas propias
> **Objetivo:** Replicar la orden de una cuenta maestra en las cuentas seguidoras del mismo usuario.
- [x] **Modelo de Relación Master-Follower:** Tabla `copy_links` y pantalla Copias en el portal. Una seguidora tiene una sola maestra.
- [x] **Redimensionamiento de Volumen:** El lote de la seguidora es el de la maestra por el ratio de equidades, con piso al paso de 0.01.
- El retraso aleatorio y la variación de stop/take profit no se implementan. Servían para ocultar la copia.

---

## 2. Tareas de Media Prioridad

### 2.1. Sistema de Alertas y Notificaciones (Telegram)
- [x] **Integración de Bot de Telegram:**
  - [x] Registro del `chat_id` del usuario en el dashboard (pantalla Cuentas).
  - [x] Alerta al pasar a alerta (80% del drawdown) o al kill-switch. No se repite mientras el nivel no cambie.
  - [x] Notificación de apertura y cierre de operaciones. El reintento del mismo ticket no vuelve a avisar.
- [x] **Reporte Ejecutivo Diario Automatizado:**
  - [x] Tarea en el proceso del API a las 17:00 hora de Nueva York.
  - [x] Resumen de balance, PnL neto, cantidad de operaciones y eventos ya cargados para el día siguiente.
- Hace falta `TELEGRAM_BOT_TOKEN` en el entorno. Sin ese token el envío no sale. WhatsApp no está incluido.

---

### 2.2. Automatización del Calendario Económico (News Feed)
- [x] **Worker de calendario:**
  - [x] Cada seis horas lee `NEWS_FEED_URL` (por defecto el JSON semanal público del calendario).
  - [x] Se queda con impacto alto de NFP, CPI, FOMC y decisiones de tipos.
  - [x] Escribe las horas en Redis para el filtro de `strategies.py`. El `POST /api/v1/market/news` sigue disponible.

---

### 2.3. Integración Comercial y Pasarelas de Pago Reales
- [ ] **Stripe / LemonSqueezy:**
  - [ ] Validación de firmas de Stripe (`stripe.Webhook.construct_event`).
  - [ ] Manejo de eventos del ciclo de vida del cliente: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`.
  - [ ] Redirección al Stripe Customer Portal para cancelación o actualización de métodos de pago.
- [ ] **Pagos Cripto:**
  - [ ] Soporte para cobro de suscripciones anuales o licencias vitalicias mediante USDT (TRC20 / BEP20) vía Binance Pay o Cryptomus.

---

## 3. Tareas Técnicas de Baja Prioridad / Despliegue

### 3.1. Migraciones de Base de Datos con Alembic
- [x] Entorno async en `backend/migrations`, configurado con la `DATABASE_URL` del proyecto.
- [x] Revisión inicial `20261016_initial` con las tablas de `models.py`.
- El arranque local sigue usando `create_all` para no romper la base SQLite que ya existe. En Postgres nuevo: `alembic upgrade head` desde `backend`.

### 3.2. Backtesting y Optimización Cuantitativa
- [ ] Script de simulación y backtest vectorizado contra datos históricos de tick y minuto (EURUSD, US30, XAUUSD) para calcular Ratio de Sharpe, Sortino y Maximum Drawdown antes de producción.

### 3.3. Compilación y Validación en Entorno Real MetaTrader 5
- [ ] Compilar `QuantGuardian.mq5` en MetaEditor 5 (Windows).
- [ ] Habilitar `http://127.0.0.1:8000` en *Herramientas > Opciones > Asesores Expertos > Permitir WebRequest*.
- [ ] Probar la ejecución de órdenes y el kill-switch en cuenta Demo de MetaTrader 5.
