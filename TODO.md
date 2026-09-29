# TODO — Restagrup en producción

Estado real a 2026-09-29: los 5 módulos están **instalados y corriendo** en
`restagrup.cositt.net` (`db-restagrup`), con la Google Places API Key cargada. Nada más
está configurado todavía — lo de abajo es lo que falta para que el flujo funcione de
punta a punta con datos reales.

## Bloqueante — sin esto "Pedir presupuesto" no manda nada real

- [ ] **Servidor SMTP saliente** (Ajustes → Técnico → Correo saliente). Verificado
  2026-09-29: `ir.mail_server` tiene 0 servidores configurados en prod. Sin esto, el
  email de petición de presupuesto se crea pero nunca sale.
- [ ] **Dominio catchall** (`mail.catchall.domain`, Ajustes → Técnico → Parámetros).
  Vacío hoy. Afecta el Reply-To real de los emails salientes.

## Configuración pendiente (diferida a propósito el 2026-09-29)

- [ ] **Claves Groq/Gemini** en Ajustes → Restagrup. Sin esto: no hay extracción IA de
  leads, ni clasificación de respuestas, ni propuesta de importe/notas de presupuesto.
  El resto del flujo sigue funcionando a mano.
- [ ] **Margen de venta por defecto (%)** en Ajustes → Restagrup. Hoy en 0 — los
  presupuestos de venta salen a coste hasta que se configure.
- [ ] **Correo entrante para captura automática** (Nivel 2 — ver guía de uso, Parte 0
  Paso 2). Bloqueado por falta de una cuenta IMAP real de la agencia/restaurantes —
  mismo bloqueante sin resolver que tiene el proyecto hermano `motor-restaurantes`
  (esperando la cuenta de Manolo). Mientras tanto, el Nivel 1 (pegar texto + Extraer
  con IA) funciona igual.

## Nunca probado en producción (solo se instaló + configuró, no se usó)

- [ ] **Smoke test real de punta a punta**: crear un lead → buscar restaurantes →
  pedir presupuesto → confirmar. No se ejecutó ni un solo flujo real en `db-restagrup`
  todavía, solo la instalación de los módulos y la carga de la clave.
- [ ] **Confirmar que Google Places devuelve resultados reales** con la key cargada —
  la key se guardó y se verificó que está en la BD, pero nunca se disparó una llamada
  real a la API desde producción.

## Infraestructura / riesgo

- [ ] **Enterprise en modo trial**, sin código real todavía (creado ~2026-09-21, ~15
  días de trial según `produccion-restagrup/access.md` — fecha exacta de vencimiento
  sin confirmar, revisar antes de que expire). Los módulos Restagrup no dependen de
  nada exclusivo de Enterprise, pero el resto de la BD sí podría verse afectado.
- [ ] **Backup de producción cubre solo la base de datos** (diario, rotación 7 días) —
  **sin backup del filestore** (adjuntos, incluidos los `.eml` que guarda la captura
  automática de respuestas cuando esté activa).
- [ ] **`odoo-dev-restagrup/` (entorno de desarrollo local) sigue sin git** — ni
  siquiera `git init` local. Solo este repo (`custom-addons/`, ahora
  `cs_restaurant_motor_searcher` en GitHub) está versionado.
- [ ] **Deploy a producción es manual por SSH** (`git clone`/`git pull` +
  `docker compose restart` + `odoo -u`) — sin pipeline, sin rollback automatizado más
  allá del backup diario de BD.

## Decisión de negocio pendiente (no técnica)

- [ ] ¿Este módulo reemplaza RestaGest+RestaFact ya en producción, o conviven un
  tiempo? No hay decisión explícita todavía — mientras el SMTP no esté configurado,
  la pregunta es moot (no puede reemplazar nada sin poder mandar emails).
