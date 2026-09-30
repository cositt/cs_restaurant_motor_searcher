# TODO — Restagrup en producción

Actualizado el 2026-09-30. Los 5 módulos están **instalados** en `restagrup.cositt.net`
(`db-restagrup`) desde el 2026-09-29, pero **sin configurar ni probar con datos reales**. El
desarrollo posterior (regla del 20 %, chatter de la búsqueda, permisos de comerciales) vive en el
repo y aún hay que desplegarlo. Lo de abajo es lo que falta para que el flujo funcione de punta a
punta con datos reales.

## Antes de desplegar (verificado en dev)

- [x] Tests de los 5 módulos: 102, 0 fallos. Instalación desde cero en una base limpia: 0 fallos.
- [x] Actualización sobre una base con datos anteriores (`-u`): sin errores ni pérdida de datos.
- [x] Flujo completo simulado de punta a punta (correo → ficha → búsqueda → presupuestos →
  respuestas → pedido → firma → hoja de servicio → confirmación). Ver
  `odoo-dev-restagrup/docs/Simulacion-completa-grupo-15-marbella.pdf`.
- [x] Un comercial **sin** permisos de Compras puede usar todo el flujo (las hojas de servicio las
  genera el sistema).

## Bloqueante — sin esto "Pedir presupuesto" no manda nada real

- [ ] **Servidor SMTP saliente** (Ajustes → Técnico → Correo saliente). En prod hay 0 servidores
  configurados: sin esto el correo se crea pero nunca sale.
- [ ] **Dominio catchall** (`mail.catchall.domain`) y **remitente por defecto**
  (`mail.default.from`). Sin ellos Odoo no puede enviar correos sin remitente explícito, y afecta al
  Reply-To de los correos salientes.
- [ ] **Email en cada usuario** que pida presupuestos (el correo sale con el email del usuario).

## Configuración pendiente

- [ ] **Buzón de correo entrante propio** (IMAP) para que las respuestas de los restaurantes y las
  peticiones de los grupos entren solas en Odoo. Se configura en Ajustes → Técnico → Correo entrante:
  uno para las respuestas (modelo "Resultado del buscador de restaurantes") y otro para las
  peticiones (modelo "Lead/Oportunidad"). Probado con un buzón de simulación (greenmail); en
  producción solo cambia el servidor al que apunta.
- [ ] **Claves Groq/Gemini** en Ajustes → Restagrup. Sin esto no hay extracción IA de leads, ni
  clasificación de respuestas, ni propuesta de importes; el resto del flujo funciona a mano.
- [ ] **Margen de Restagrup (%)** en Ajustes → Restagrup: viene en **20** por defecto (el cliente
  paga el precio del restaurante + 20 %). Comprobar que no haya un 0 guardado de antes.
- [ ] **Ajustes → Ventas → Presupuestos y pedidos**: dejar **"Firma en línea" activada** y
  **"Pago en línea" desactivado**, para que la agencia pueda aceptar solo firmando (por defecto Odoo
  trae las dos activadas y le pediría pagar).
- [ ] **Cargar los menús de cada restaurante** (ficha del restaurante → pestaña Menús): el precio que
  se carga es **el del restaurante**; el del cliente sale solo sumando el margen.

## Nunca probado en producción (solo instalado)

- [ ] **Smoke test real de punta a punta** con un grupo de prueba: lead → buscar → pedir presupuesto →
  confirmar → hoja de servicio. Incluye probar la **ventana de firma** del portal con un navegador
  sin sesión de administrador (en dev solo se probó el envío de la aceptación al enlace público).
- [ ] **Confirmar que Google Places devuelve resultados reales** desde producción con la clave
  cargada.

## Infraestructura / riesgo

- [ ] **Enterprise en modo trial** (creado ~2026-09-21, ~15 días de trial; en el entorno de desarrollo
  se ve "Esta base de datos expirará en 29 días"). Revisar la fecha de vencimiento antes de que expire.
- [ ] **Backup de producción cubre solo la base de datos** (diario, rotación 7 días) — **sin backup del
  filestore** (adjuntos, incluidos los `.eml` de la captura automática de respuestas).
- [ ] **`odoo-dev-restagrup/` (entorno de desarrollo local) sigue sin git**; solo este repo
  (`custom-addons/`) está versionado.
- [ ] **Deploy a producción manual por SSH** (`git pull` + `docker compose restart` + `odoo -u`), sin
  pipeline ni rollback automatizado más allá del backup diario de la base de datos. Hacer un backup
  justo antes de actualizar.
- [ ] **VeriFactu** (obligatorio desde 2027-01-01): comprobar en producción que la compañía tiene la
  localización española y VeriFactu configurado. No es código de este repo.

## Decisiones tomadas

- El correo lo gestionan ellos desde Odoo (buzón propio); ya no se depende de ninguna cuenta externa
  ni del prototipo anterior (`motor-restaurantes`).
- Todo el correo saliente va **en español** (a restaurantes y a agencias), aunque la agencia sea
  extranjera.
- El cliente paga **precio del restaurante + 20 %**; ese 20 % es el margen de Restagrup y se puede
  cambiar en Ajustes. La hoja de servicio del restaurante lleva siempre **su** precio.

## Decisión de negocio pendiente

- [ ] ¿Este módulo reemplaza RestaGest+RestaFact ya en producción, o conviven un tiempo?

## Puntos conocidos, no bloqueantes

- La búsqueda no filtra por tipo de cocina: Google devuelve también bares, pizzerías, etc., y hoy se
  descarta a mano.
- El botón "Hojas de servicio" del pedido también lo ve un comercial sin permisos de Compras; es
  probable que Odoo le niegue el acceso al listado al abrirlo (no verificado). El resumen "N/M
  confirmados" y la creación y el envío de las hojas sí funcionan (verificado con tests).
