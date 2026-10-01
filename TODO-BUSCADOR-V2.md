# TODO — Buscador v2 (grupos multi-evento, margen, presupuestos, cambios)

Creado el 2026-10-01, actualizado el mismo día con las decisiones de Juan. **Solo en dev**
(`odoo-dev-restagrup/`). Nada de esto se despliega a producción hasta tenerlo probado en dev y con
visto bueno explícito.

Estado: **PLAN CERRADO (2026-10-01). Todas las decisiones tomadas. Desarrollo en curso, punto por punto.**

Reglas de trabajo (de `CLAUDE.md` y de la memoria del proyecto):
- TDD: test primero (RED), luego código (GREEN). Cobertura mínima 80 % del código nuevo.
- Los tests corren como superusuario: cada modelo nuevo/transient lleva test de **permisos** con un
  usuario `group_user` + `sale.group_sale_salesman`, y su línea en `ir.model.access.csv`.
- Tests en dev: `--http-port=8973` (el 8069 del contenedor está ocupado). Hard-refresh tras cambios de vista/JS.
- Rama `feature/…` desde `develop`. Conventional Commits. Sin push ni deploy sin pedirlo.
- Confirmación previa obligatoria: **cambios de schema de BD** (🗄️), nuevas dependencias, refactors de
  más de 5 archivos.

---

## Decisiones tomadas (2026-10-01)

| Tema | Decisión |
|---|---|
| Orden | 1 → 6 tal como está abajo. |
| Margen | Visible en la tabla interna, oculto al cliente, con interruptor por presupuesto para mostrarlo. |
| Petición de la agencia | **El correo trae varios lugares y fechas** (y tipos de evento): la IA debe extraerlos todos. Es un requisito nuevo, ver 4A. |
| Tipos de evento | No solo comida/cena: desayuno, aperitivo, coffee break… y **ampliables** por el usuario. |
| Eventos tras firmar | Si el presupuesto **no está firmado**, se añaden a él. Si **ya está firmado**, se crea un **presupuesto adicional**. |
| Avisos conjuntos | **Solo a restaurantes** (la agencia no interviene). **Texto libre y plantillas**, a elegir siempre. |
| Cancelación | Es un asunto **restaurante ↔ Restagrup**, no de la agencia (no hay que volver a firmar). Motivos: no puede, sustituido por uno más barato, sustituido por uno mejor. |
| Margen al cliente | Con el interruptor activo se muestra como **línea aparte "Gestión Restagrup (X %)"** (decisión delegada a Claude). |
| Tipos de evento iniciales | Desayuno, aperitivo, comida, cena, coffee break y otro; ampliables. |
| Presupuesto adicional | Regla aprobada: no firmado → se añade; firmado → adicional aparte. |
| Sustituir restaurante | Al cambiar de restaurante **se ajustan los precios al nuevo** (lo normal). Restagrup puede decidir mantener el precio al cliente con una casilla. |

---

## Cómo está hoy (lo que condiciona el diseño)

| Pieza | Hoy |
|---|---|
| Grupo/cliente | `crm.lead`. Ya tiene **varias búsquedas** (`restagrup_restaurant_search_ids`, One2many). |
| Extracción IA del correo | `restagrup_email_ai`: devuelve **una** ciudad, **un** nº de pax, **una** fecha y un tipo de grupo. No sabe de varios lugares ni fechas. |
| Búsqueda | `restagrup.restaurant.search`: ciudad, `min_capacity` (pax), tipo de local… **sin fecha ni tipo de evento**. Una búsqueda = un `chosen_line_id` = un `sale_order_id`. |
| Línea de resultado | `restagrup.restaurant.search.line`, con `etiqueta` (visto/interesado/solicitado/presupuesto_recibido/descartado) y `quote_amount`. |
| Presupuesto de venta | `sale.order`. Sus líneas **ya tienen** `restaurant_id`, `service_date`, `service_meal` (solo comida/cena). Se ve en la captura S00002. |
| Margen | `restagrup.pricing.apply_margin()` (20 % por defecto). Se aplica en `price_unit` al crear el pedido; no se guarda el coste ni el margen en la línea. |
| Hoja de servicio | `purchase.order` por (presupuesto, restaurante), generada al confirmar. Tiene `restagrup_response_state` (IA), `restagrup_needs_resend` y reenvío de cambios. |

Idea clave: `sale_order_id` es un Many2one en la búsqueda, así que varias búsquedas del mismo grupo
pueden apuntar al **mismo** pedido sin cambiar el schema.

---

## Orden y dependencias

| # | Tema | Tamaño | Depende de | Schema 🗄️ |
|---|---|---|---|---|
| 1 | Bug: no deja elegir con el presupuesto recibido por email | S | — | no |
| 2 | Pestaña "Presupuestos" (solo restaurantes con presupuesto) | S | 1 | no |
| 3 | Margen interno + opción de mostrarlo al cliente | M | — | sí |
| 4A | La IA extrae **varios eventos** (lugar, fecha, tipo, pax) del correo | M | — | sí |
| 4B | Búsqueda por evento + presupuesto acumulado / adicional | L | 1, 3, 4A | sí |
| 5 | Vista "Clientes/Grupos" + aviso conjunto a restaurantes | L | 4B | sí |
| 6 | Cancelar o cambiar un restaurante | M | 4B, 5 | sí |

Cada punto se hace con sus tests, se prueba en dev en navegador y se cierra antes del siguiente.

---

## 1. Bug: no se puede elegir un restaurante con presupuesto recibido por email

> **✅ HECHO EN DEV (2026-10-01), sin commit.** Rama `fix/elegir-restaurante-presupuesto-ia`. Opción **B + C**:
> campo `quote_pending_confirmation`; la tarjeta muestra "propuesto por IA, sin confirmar" y un botón
> **Confirmar presupuesto**; "Elegir" sobre un importe sin confirmar abre "Registrar presupuesto y elegir".
> 7 tests nuevos (RED→GREEN). Módulo restaurantes 51 tests y los otros 4 módulos 58: **0 fallos**. Verificado en
> navegador en dev. Pendiente: commit/merge y despliegue a prod cuando se pida.

**Causa probable (reproducida en prod el 2026-10-01).** Cuando el presupuesto llega **por email**,
`_restagrup_classify_quote_response` rellena `quote_amount` y deja la etiqueta en **"solicitado"**.
La tarjeta pinta el importe (1.176,00 €) y parece registrado, pero `action_toggle_chosen` exige
`etiqueta == 'presupuesto_recibido'` y lanza "Solo se puede elegir un restaurante con presupuesto
recibido…". Lo mismo en `action_create_sale_order`.

**Confirmado por Juan:** metiendo el importe **a mano** sí funciona. Cuadra con la causa: la diferencia
es solo cómo se rellena el importe.

**Punto no resuelto:** Juan dice que **no le aparecía el botón "Registrar presupuesto"**. En el código el
botón de la tarjeta se muestra siempre que la etiqueta no sea `presupuesto_recibido` (también en
"solicitado"), y en la captura sí sale. Hay que **reproducirlo en dev con un importe extraído por IA**
y ver exactamente qué falla antes de tocar nada. Primer paso del punto: test que lo reproduzca.

**Opciones**
- **A.** Registrar automáticamente al extraer el importe por IA. Rompe la regla "la IA nunca registra sola".
- **B.** La tarjeta muestra "Importe propuesto por IA — sin confirmar" con botón **Confirmar** de un clic.
- **C.** "Elegir" sobre una línea con importe sin registrar abre "Registrar X € y elegir" en vez de dar error.
- **D.** Mensaje de error claro con botón (mínimo viable).

**Recomendación: B + C.** Mantiene la revisión humana y elimina la confusión.
**Tests primero:** línea con importe de IA y etiqueta `solicitado` → no se pinta como registrada; Elegir
ofrece registrar; tras registrar, elegir y crear presupuesto de venta funcionan.
**Archivos:** `restaurant_search.py`, `restaurant_search_views.xml` (+ CSS de tarjeta).

---

## 2. Pestaña "Presupuestos" dentro de Resultados

> **✅ HECHO EN DEV (2026-10-01).** Rama `feature/pestana-presupuestos`. Pestaña **Presupuestos** con solo los
> restaurantes con presupuesto (registrado o propuesto por IA, marcado en naranja), del más barato al más caro,
> con importe del restaurante, precio al cliente (con margen), notas y botones Confirmar / Elegir / Ver conversación.
> Campos calculados (`quoted_line_ids`, `quote_client_price`): **sin cambios de schema**. 7 tests nuevos; 108 en
> total, 0 fallos; verificado en navegador. **Pendiente (decidir):** columna "fecha de respuesta", que necesita un
> campo guardado nuevo (🗄️) y por eso no se hizo.

Tabla limpia con **solo** los restaurantes que han enviado presupuesto: restaurante, importe del restaurante,
precio al cliente (con margen), notas, fecha de respuesta, estado, botones Registrar/Elegir.

**Recomendación:** pestaña en la búsqueda con campo calculado `quoted_line_ids`, incluyendo las líneas
**"con importe propuesto por IA"** marcadas como *por confirmar* (enlaza con el punto 1). Un menú global
"Presupuestos recibidos" (todas las búsquedas) queda para después si se echa en falta.
**Tests:** el calculado incluye `presupuesto_recibido` (+ por confirmar), orden por importe, totales.
**Archivos:** `restaurant_search.py`, `restaurant_search_views.xml`.

---

## 3. Margen en la tabla interna + opción de mostrarlo al cliente

> **✅ HECHO EN DEV (2026-10-01).** Rama `feature/margen-presupuesto`. Opción **B** (campos propios) con la
> variante **S** para el cliente: con el interruptor "Mostrar margen al cliente" encendido, el PDF y el portal
> añaden bajo los totales *"Incluye Gestión Restagrup (X %): Y € (base imponible)"*; el coste del restaurante
> **nunca** se muestra. Los comerciales ven el margen en la tabla interna (decisión de Juan).
> Schema aprobado: `restagrup_unit_cost` y `restagrup_margin_pct` (línea), `restagrup_show_margin` (pedido) y
> `quote_received_date` (resultado de búsqueda, columna "Recibido" de la pestaña Presupuestos).
> El % queda **congelado** en la línea: cambiar el margen en Ajustes no recalcula pedidos ya creados, ni al
> cambiar los comensales. 24 tests nuevos; 132 en total, 0 fallos; verificado en navegador (vista interna y
> portal, con el interruptor apagado y encendido). **Al desplegar a prod:** las líneas existentes se rellenan
> solas (coste del menú o del presupuesto; % = el vigente en ese momento, no el histórico).
> Pendiente: la plantilla del PDF "Imprimir propuesta" (por restaurante) no lleva la nota; no la necesita.

En la tabla de líneas del presupuesto, el equipo ve coste del restaurante, % y € de margen. **El cliente no**,
salvo que se active una opción por presupuesto.

**Opciones de implementación**
- **A.** Módulo nativo `sale_margin`: menos código, pero **dependencia nueva** y no distingue el "% de Restagrup".
- **B.** Campos propios en `sale.order.line`: `restagrup_cost`, `restagrup_margin_pct`, `restagrup_margin_amount`
  🗄️ y totales en el pedido. Columnas solo para el grupo interno, nunca en PDF/portal.

**Recomendación: B**, con interruptor `restagrup_show_margin` 🗄️ en el pedido.
**Cómo lo ve el cliente cuando se activa (decidido):** línea aparte "Gestión Restagrup (X %)" al final del
presupuesto, con el importe del margen. Las líneas de restaurante conservan su precio sin margen incluido.
**Ojo:** si el margen cambia en Ajustes, los pedidos ya creados **no** se recalculan (se guarda el % aplicado).
**Nota de diseño:** con el interruptor encendido, las líneas de restaurante muestran el precio del restaurante y
la línea de gestión suma el margen; apagado, cada línea lleva el precio ya con margen (como hoy).
**Tests:** coste 25 € y 20 % → cliente 30 €, margen 5 €; PDF/portal sin margen con el interruptor apagado y con
margen encendido; usuario sin grupo interno no ve las columnas.
**Archivos:** `restagrup_service_orders/models/sale_order(_line).py`, vistas y report de presupuesto/propuesta.

---

## 4A. La IA extrae varios eventos del correo (requisito nuevo)

> **✅ HECHO EN DEV (2026-10-01).** Rama `feature/eventos-ia`. Schema aprobado y aplicado:
> tablas `restagrup_event_type` (core, 6 tipos iniciales, ampliables desde Restagrup → Tipos de evento) y
> `restagrup_lead_event` (email_ai), columna `event_id` en las búsquedas, y `restagrup_restaurants` pasa a
> depender de `restagrup_email_ai` (ya usaba sus campos sin declararlo). La IA devuelve una lista de eventos
> (ciudad, fecha, tipo, pax, notas) que entran como **borrador** en la pestaña "Eventos" del lead; cada
> evento tiene su botón "Buscar" y hay "Buscar para todos los eventos". La búsqueda se llama p. ej.
> `Sevilla · 40 pax · Cena · 16/11`. Máximo 20 eventos por correo; datos sucios se dejan vacíos, nunca se
> inventan. 52 tests nuevos; 160 en total, 0 fallos; verificado en navegador.
> **Prueba real contra Groq: 61/61 campos acertados** sobre 9 correos de ejemplo (ES/EN, 1 o varios lugares,
> año omitido, sin datos, aviso automático). Es un corpus pequeño y limpio: se repite con correos reales de
> agencias con `restagrup_email_ai/eval/eval_extraction.py` (instrucciones en su cabecera).
> Pendiente para el 4B: tipo de evento en las líneas del presupuesto (hoy solo comida/cena) y presupuesto
> acumulado/adicional. Nota: el estado de un evento no vuelve a "borrador" si se borra su búsqueda.

El correo de la agencia puede pedir, p. ej.: *"15 nov comida en Málaga, 15 nov cena en Málaga, 16 nov cena en
Sevilla, 42 personas"*. Hoy la IA devuelve un único lugar y una única fecha.

**Diseño**
1. **Prompt nuevo** que devuelve una lista `eventos`: `{ciudad, fecha (YYYY-MM-DD o null), tipo, pax, notas}`.
   Se mantienen las claves antiguas (`ciudad`, `num_pax`, `fecha_servicio`, `tipo_grupo`) para no romper
   nada. Reglas: nunca inventar; si falta el año, la próxima ocurrencia; correos en español **y en inglés**
   (agencias británicas).
2. **Modelo nuevo `restagrup.lead.event`** 🗄️ colgado del lead: ciudad, fecha, tipo, pax, notas, estado
   (borrador / con búsqueda), enlace a su búsqueda. La IA los crea como **borrador** y una persona los revisa,
   igual que hoy con los datos del lead ("nunca se crea nada automáticamente").
3. **Tipos de evento ampliables** `restagrup.event.type` 🗄️ (desayuno, aperitivo, comida, cena, coffee break,
   otro…), editable en Restagrup → Configuración. Las líneas del presupuesto hoy solo admiten comida/cena
   (`service_meal`): se añade un tipo de evento a la línea y los datos antiguos se mapean sin perderse.
4. Pestaña **"Eventos"** en el lead: lista editable, y botones "Buscar restaurantes" por evento y
   "Buscar para todos" (crea las búsquedas ya con ciudad, pax, fecha y tipo).

**Alternativa descartada:** guardar el evento solo en la búsqueda. No sirve porque el correo trae varios
eventos *antes* de que exista ninguna búsqueda, y hay que revisarlos primero.
**Compatibilidad:** un correo con un solo lugar crea un solo evento; los leads antiguos sin eventos se
comportan como hoy.
**Tests:** con el LLM simulado: correo de 3 eventos → 3 borradores; correo de 1 evento → 1; sin datos →
ninguno y estado "sin datos". **Además una prueba real contra Groq** con un corpus de correos de ejemplo
(ES, EN, varios lugares, año omitido), porque los tests simulados no miden la calidad de la extracción.
**Archivos:** `restagrup_email_ai/models/crm_lead.py`, modelos nuevos, vistas, datos de tipos de evento, ACL.

---

## 4B. Búsqueda por evento y presupuesto acumulado o adicional

> **✅ HECHO EN DEV (2026-10-01).** Rama `feature/presupuesto-multievento`. "Crear presupuesto de venta" añade la
> línea al presupuesto **sin firmar** (borrador o enviado) del grupo; si no hay, crea el primero; si el último
> ya está **confirmado/firmado**, no lo toca y crea un **presupuesto adicional** (aviso azul "el primero es
> S…" y nota en el chatter). Cada línea lleva el tipo y la fecha del evento y su descripción lo dice
> (*"Cena · 16/11 — Servicio en X (Sevilla, 40 pax)"*). Los presupuestos quedan enlazados al lead
> (`opportunity_id`). Si se añade a uno ya enviado, nota en el chatter para reenviarlo. Cada presupuesto genera
> sus hojas de servicio. Un grupo de un solo evento va exactamente como antes (test de regresión).
> Schema aprobado: columna `service_event_type_id` en la línea; migración (v19.0.1.1.0) copia comida/cena
> antiguos al tipo nuevo (en dev: 8 de 8 líneas); `service_meal` se conserva sin usar. 13 tests nuevos; 173 en
> total, 0 fallos; verificado en navegador (acumulado de 2 eventos, adicional con banner y desayuno).
> **Al desplegar a prod:** reiniciar el servicio web tras actualizar (un campo nuevo sin reinicio da error en
> el formulario). **Pendiente / límites conocidos:** (1) un presupuesto creado por otro comercial puede no ser
> visible por la regla de "solo mis pedidos" y se crearía uno nuevo en lugar de añadir; (2) la regla de
> firmado es "estado confirmado"; (3) el informe "Imprimir propuesta" por restaurante no se ha tocado.

**Búsqueda por evento.** Cada evento genera su búsqueda (`event_id` 🗄️ en la búsqueda). El nombre pasa a
`42 pax · Málaga · Cena · 15/11`. Pestaña **"Eventos del grupo"** en la búsqueda con las hermanas (mismo
lead), su estado y su restaurante elegido, y botón "Añadir evento".

**Presupuesto, en lenguaje llano**
- Un grupo tiene normalmente **un presupuesto abierto**. Cada evento añade ahí la línea de su restaurante
  elegido, con su fecha y tipo. El total se acumula solo.
- Si el grupo **ya firmó** ese presupuesto y aparece un evento nuevo, **no se toca el firmado**: se crea un
  **presupuesto adicional** que la agencia firma aparte. Así lo ya firmado queda intacto.
- Si el presupuesto **todavía no está firmado**, el evento nuevo se añade al mismo.
- Las hojas de servicio se generan por presupuesto y restaurante. Si un restaurante aparece en el original y
  en el adicional, recibirá dos hojas, cada una con su fecha.
- El resumen del grupo suma todos los presupuestos.

**Tests:** 3 eventos → un único presupuesto con 3 líneas y total acumulado; fecha y tipo en cada línea;
presupuesto firmado + evento nuevo → presupuesto adicional y el firmado **no cambia**; regresión: un grupo de
un solo evento va exactamente como hoy.
**Archivos:** `restaurant_search.py` (restaurants y service_orders), `crm_lead.py`, `sale_order.py`, vistas,
informe de propuesta (agrupar por evento además de por restaurante). **Migración:** búsquedas antiguas sin
evento siguen funcionando.

---

## 5. Vista "Clientes/Grupos" + aviso conjunto a restaurantes

> **✅ HECHO EN DEV (2026-10-01).** Rama `feature/clientes-avisos`. Menú **Restagrup → Clientes** (lista de grupos
> con eventos, restaurantes elegidos, presupuestado, confirmados N/M y avisos sin respuesta), pestañas
> **Eventos** (con restaurante, importe, presupuesto y estado de la hoja) y **Avisos** en el lead, botón
> **Avisar a restaurantes** con asistente (restaurantes marcables, plantilla o texto libre, variables
> `{restaurante} {grupo} {evento} {fecha} {comensales}`), y seguimiento por aviso (pendiente / respondido, fecha,
> extracto y resumen IA). Sale por el hilo de la hoja de servicio si existe, o por el de la petición de
> presupuesto si no. **La agencia no recibe nada.** Menús nuevos: Avisos enviados y Plantillas de aviso (3
> iniciales: cambio de comensales, de fecha u hora, general). Schema aprobado: tablas `restagrup_restaurant_notice`,
> `restagrup_notice_template` y el asistente (`..._wizard` + `_line`); ninguna columna en tablas existentes.
> 20 tests nuevos; 193 en total, 0 fallos; verificado en navegador (asistente, plantilla, envío, pestañas
> Eventos/Avisos y menú Clientes). **No verificado en navegador:** el paso a "Respondido" (cubierto por tests
> con la respuesta simulada). **Límites:** (1) una respuesta solo se enlaza si contesta al mismo correo;
> (2) si un restaurante está elegido en dos eventos del mismo presupuesto, recibe un aviso por evento;
> (3) el aviso por el hilo de la petición de presupuesto aparece como un correo más en esa conversación.

Nuevo menú **Restagrup → Clientes** con el resumen de cada grupo: datos del cliente (como el lead), eventos,
restaurantes elegidos con importe, presupuestos y su estado, confirmaciones N/M.

**Vista:** reutilizar `crm.lead` con acción, lista y kanban propios (sin modelo nuevo; un modelo `restagrup.group`
duplicaría datos del lead).

**Aviso conjunto (solo a restaurantes)**
- Asistente **"Avisar a restaurantes"**: eliges los restaurantes del grupo (los elegidos de cada evento), eliges
  una **plantilla** o escribes **texto libre** (o plantilla y luego la editas), con variables: restaurante, grupo,
  fecha, nuevo nº de comensales.
- Se envía por el **hilo de la hoja de servicio** de cada restaurante, así sus respuestas vuelven enlazadas y las
  clasifica la IA que ya existe.
- **Seguimiento** por restaurante: enviado / respondido / resumen IA / pendiente. Campo propio 🗄️ para no
  confundirlo con la aceptación de la hoja original.
- La **agencia no recibe nada** de este aviso. Ojo: el botón actual "Reenviar cambios" sí manda también la proforma
  a la agencia; el asistente nuevo es independiente y no lo hace.
- El cambio de pax se hace en la línea del presupuesto (fuente única de la cantidad) y el asistente notifica.

**Tests:** envía solo a los seleccionados, mensaje enlazado al hilo correcto, respuesta simulada actualiza el
seguimiento, plantilla y texto libre; **permisos** del transient con comercial sin Compras.
**Archivos:** wizard nuevo + vistas/menú + ACL, plantillas de correo, `purchase_order.py`, `crm_lead.py`.

---

## 6. Cancelar o cambiar un restaurante

Asunto interno entre Restagrup y el restaurante: **la agencia no interviene ni vuelve a firmar.**

**Asistente "Cancelar / cambiar restaurante" sobre un evento**
1. **Motivo** (lista ampliable): el restaurante no puede · sustituido por otro más barato · sustituido por otro
   mejor · otro (texto libre). Queda registrado para consultarlo después.
2. Casilla **"avisar al restaurante"** con plantilla o texto libre.
3. Su hoja de servicio pasa a **cancelada** (el contador N/M ya ignora las canceladas) y la línea del resultado
   queda como **cancelado** con su motivo (valor nuevo de `etiqueta`).
4. El evento vuelve a "presupuestos recibidos": se puede **elegir otro** de los que ya tenían presupuesto o
   pedirlo a nuevos. Si ya hay uno sustituto elegido, se hace el cambio en el mismo asistente.
5. La línea del presupuesto pasa al nuevo restaurante y se genera su hoja de servicio.

**Precio al sustituir (decidido):** por defecto el presupuesto **se ajusta al nuevo restaurante** (coste, margen y
precio al cliente recalculados). Una casilla "mantener el precio al cliente" deja la decisión en manos de
Restagrup: entonces cambia solo el coste y el margen absorbe la diferencia.
**Tests:** cancelar con hoja enviada la cancela, avisa y reabre el evento; sustituir recalcula coste y margen sin
tocar lo cobrado al cliente; contadores N/M; regresión sin presupuesto.
**Archivos:** wizard nuevo, `restaurant_search.py`, `sale_order.py`, `purchase_order.py`, vistas.

---

## Preguntas

Ninguna abierta. El bug del punto 1 se reproduce primero en dev, con test, antes de tocar código.

## Fuera de alcance (de momento)
- Filtrar Google por tipo de cocina (limitación conocida).
- Facturación, VeriFactu y localización española.
- Cualquier despliegue a producción.
