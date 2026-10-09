# Estudio: acercar Odoo al flujo del CRM actual de Restagrup

Fecha: 2026-10-08 · Base: CRM del cliente visto **solo en lectura** (crm.restagrup.com) + nuestro código en `odoo-dev-restagrup/custom-addons`.
Objetivo (Juan): que la transición CRM → Odoo sea poco traumática, **adaptando lo máximo posible al flujo y vocabulario de ellos, añadiendo lo nuestro y sin tirar lo ya hecho**.

> Estado: propuesta para decidir. Nada de esto está implementado salvo lo marcado como «ya existe».

---

## 1. Qué hace su CRM (resumen)

Un único documento que cambia de fase. Mismo registro, misma pantalla, cambia el botón de avance.

| Fase en su CRM | Prefijo | Estado | Botón para avanzar | Qué significa de verdad |
|---|---|---|---|---|
| **Petición** | PET… | CREADO | Pasar a presupuesto | Entra el grupo de la agencia; el comercial busca restaurante+menú |
| **Presupuesto** | PRE… | PENDIENTES («Pend. contestación») | Pasar a expediente | Propuesta ya enviada a la agencia, esperando respuesta. **No es un importe pedido a un restaurante** |
| **Expediente** | EXP… | EXPEDIENTE | Cerrar Expediente | La agencia aceptó: confirmaciones, bono, cobros y pagos |
| **Terminados** | — | CERRADO | — | Evento hecho y gestión cerrada |
| (cancelado) | — | CANCELADO | «Rechazar presupuesto» | En cualquier momento |

Piezas clave que vimos:
- **Buscador de menús** en cada servicio (filtra por restaurante, lugar, zona, menú, estado, capacidad, precio) y se asigna restaurante+menú.
- **El menú trae el precio** (coste y venta, margen por menú). No se pide precio al restaurante en cada grupo.
- **Servicios**: un documento tiene 1..N servicios (fecha, población, tipo, comensales, precio/persona).
- **Gratuidades**: comensales asignados menos gratuitos; solo se cobran los de pago (ej.: 52 asignados, 2 gratis → 50 × 34,90 € = 1.745 €).
- **Panel económico**: Total coste (restaurante) + Total comisión (Restagrup) = Total servicios + Suplementos. Marcas: Restaurante visible, Fact. enviada, Pagado, Factura pendiente de recibir, Servicio pagado.
- **Correos/documentos**: Presupuesto PDF, Enviar a agencia, CONF. AGENCIA, CONF. RESTAURANTE, BONO AGENCIA. Historial («seguimientos») y Documentación adjunta.
- **Comercial asignado** por documento (8 personas). **Agencias** con código AGN…, forma de pago prepago/crédito. **Restaurantes** con ficha muy completa.
- Volumen: 11.130 documentos (834 expedientes), 1.056 agencias, 7.629 restaurantes.

## 2. Qué tenemos nosotros (ya construido)

| Concepto de ellos | Lo nuestro hoy | Módulo |
|---|---|---|
| Petición | Oportunidad `crm.lead` creada sola desde el correo por IA, con eventos | `restagrup_email_ai` |
| Servicio | `restagrup.lead.event` (ciudad, fecha, tipo, pax) | `restagrup_email_ai` |
| Buscador de restaurante | `restagrup.restaurant.search` + líneas (mapa, Google Places, ranking, avisos de aforo/cierre) | `restagrup_restaurants` |
| Menú con coste/venta | **`product.template` con `restaurant_id`** + `standard_price` (coste) + `restagrup_client_price` (con margen global) | `restagrup_service_orders` |
| «Presupuesto» (documento a la agencia) | `sale.order` (presupuesto de venta) + portal con firma + PDF de propuesta | `restagrup_service_orders` / `restagrup_agency_proposal` |
| Lo que **nosotros** llamamos presupuesto | Importe que **contesta el restaurante** por correo (`quote_amount`, leído por IA) | `restagrup_restaurants` |
| Expediente | `sale.order` confirmado + hojas de servicio por restaurante (`purchase.order`) + avisos + cambios | `restagrup_service_orders` |
| Seguimiento | Chatter del lead/búsqueda + cola de correos pendientes de aprobar + recordatorios | `restagrup_restaurants` |
| Comparativa de restaurantes al cliente (nuevo) | PDF + portal «Elijo este» | `restagrup_agency_proposal` |

**Conflicto central de vocabulario:** su «presupuesto» = fase de propuesta a la agencia; nuestro «presupuesto» = respuesta de precio del restaurante. Hay que separar los nombres (sección 4).

## 3. Diferencia de fondo que hay que decidir

Ellos trabajan **desde catálogo**: el menú ya trae precio, así que la propuesta sale directa. Nosotros trabajamos **pidiendo cotización** al restaurante por correo (la IA lee la respuesta). No son excluyentes:

- **Camino A (catálogo, como ellos):** servicio → elegir restaurante+menú del buscador → el precio sale del menú → propuesta a la agencia. Rápido, su forma habitual. *Ya soportado:* `restagrup.menu.selection.wizard` crea el presupuesto de venta desde productos-menú.
- **Camino B (cotización, lo nuestro):** servicio → pedir precio a uno o varios restaurantes → llegan respuestas → comparar → propuesta. Útil para menús a medida, restaurantes sin menú cargado o fechas especiales.

**Propuesta:** el comercial elige el camino por servicio; los dos acaban en la **misma propuesta a la agencia**. El A es el predeterminado (familiar para ellos); el B es un botón «Pedir cotización» que añade valor sin quitar nada. La comparativa multi-restaurante con portal vale para ambos.

## 4. Vocabulario y fases en Odoo (la capa «familiar»)

Principio: **no tocar el motor, cambiar la superficie**. Etiquetas, etapas, menús y listas iguales a las suyas.

1. **Etapas del lead = sus fases:** Petición → Presupuesto → Expediente → Cerrado (+ Cancelado). Barra de estado visible como la de su pantalla.
   - *Petición*: recoge lo que hoy son «Buscando» y «Presupuestos pedidos» de nuestro buscador (trabajo interno, no cambia de fase para la agencia).
   - *Presupuesto*: se pasa al **enviar la propuesta a la agencia** (PDF + portal opcional). Equivale a «Pend. contestación».
   - *Expediente*: cuando la agencia acepta (firma en portal o botón «Pasar a expediente») → se confirma el `sale.order` y se generan las hojas de servicio (ya existe).
   - *Cerrado*: botón «Cerrar expediente» tras el evento.
2. **Numeración** PET/PRE/EXP + año/mes + secuencia, **conservando el mismo número a lo largo de la vida del grupo** (como ellos: cambia el prefijo, no el documento).
3. **Menús de Odoo** iguales a los suyos: Peticiones · Presupuestos · Expedientes · Terminados · Agencias · Restaurantes, cada uno una lista filtrada por etapa con **las mismas columnas** (Nº Doc, Agencia, Ref. Grupo, Nº servicios, Fecha 1º servicio, Población, Restaurante, Nº comensales, Asignado a, Estado).
4. **Renombrar lo nuestro para quitar el choque:**
   - «Presupuesto del restaurante» → **«Cotización»** (la respuesta de precio del restaurante).
   - «Presupuesto» queda para el documento a la agencia (como ellos).
   - «Comparativa para el cliente» → **«Propuesta a la agencia»** / «Presupuesto PDF» (su botón), con N opciones.
5. **Etiquetas de botones iguales:** Presupuesto PDF, Enviar a agencia, Pasar a presupuesto, Pasar a expediente, Cerrar expediente, Rechazar presupuesto (→ Cancelado, con motivo: ya tenemos `restagrup.cancel.reason`).

## 5. Menús (decidido por Juan, 2026-10-08)

Se **adapta nuestro modelo `restagrup.restaurant.menu`** a los campos del menú del CRM del cliente, **estructurado (no texto libre) y 100 % editable**:

| Campo de su menú | En nuestro modelo |
|---|---|
| Nombre | `name` |
| Tipo menú (Almuerzo, Buffet, Cena, Desayuno, Picnic, Show, Sin definir) | `menu_type` |
| Descripción (texto libre) | **Platos por tipo** (entrante/principal/postre/bebida) con alérgenos, editables en línea + observaciones |
| Precio coste | `cost_price` |
| Precio venta + «% beneficio» | `sale_price` (se calcula con el margen del restaurante, **pero se puede escribir otro**) + `profit_percent` informativo |
| Capacidad | `max_pax` (y `min_pax`) |
| Activo/inactivo | `active` |

**Margen por restaurante:** cada restaurante puede tener margen propio (`restaurant_margin_custom` + `restaurant_margin_percent`); si no, el general (20 % en Ajustes). Lo resuelve `restagrup.pricing.margin_percent(partner=…)` / `apply_margin(…, partner=…)`.

Aviso de duplicidad: ya existen menús como `product.template` con restaurante (usados por el presupuesto de venta y las hojas de servicio). Hoy conviven los dos; **falta decidir cómo se relacionan** (p.ej. que cada menú genere/sincronice su producto).

## 6. Panel económico y gratuidades

- **Coste / Comisión / Total / Suplementos** como cabecera del expediente. Mapa: coste = suma del coste de las líneas (hojas de servicio / `standard_price × pax de pago`), comisión = precio cliente − coste (nuestro margen), total = `sale.order`, suplementos = líneas extra.
- **Gratuidades:** `pax de pago = asignados − gratuidades`; afecta a cantidad de la línea y a la hoja del restaurante.
- **Marcas** Fact. enviada / Pagado / Factura pendiente de recibir / Servicio pagado → estados de factura de cliente y de proveedor en Odoo Contabilidad (facturar = botón estándar, con VeriFactu ya previsto en `PROXIMA-FASE` F). Son campos calculados en vez de casillas manuales, con opción de marcarlas a mano mientras no se factura en Odoo.
- **Restaurante visible:** casilla por documento (la agencia ve o no el nombre en la propuesta).

## 7. Correos y documentos de su flujo

| Suyo | Nuestro punto de partida |
|---|---|
| Presupuesto PDF / Enviar a agencia | Propuesta a la agencia (PDF + portal opcional) — **hecho hoy** |
| CONF. AGENCIA | Confirmación al aceptar (plantilla nueva; ya hay re-envío de proforma tras cambios) |
| CONF. RESTAURANTE | Hoja de servicio al restaurante (**ya existe**) |
| BONO AGENCIA | **Documento nuevo** (informe QWeb) |
| Envío de correo al restaurante desde la fila | Aviso a restaurantes (`notice.wizard`, **ya existe**) |
| Historial / seguimientos | Chatter (+ nota manual = «Nuevo seguimiento») |
| Documentación | Adjuntos del lead/pedido |

Necesitamos **los textos reales** de sus correos y el aspecto de sus PDFs (los veremos «comparando con el suyo», como dijo Juan).

## 8. Datos y migración

**Aparcado por decisión de Juan:** la importación de restaurantes, agencias y documentos **no se hace por ahora**; es antes de la entrega y «ya veremos cómo lo sacamos». No se piden exportaciones. Del CRM del cliente **no se toca nada** (solo se estudió).

## 9. Qué se conserva y qué aporta Odoo (valor añadido, no se pierde)

Se mantiene todo lo ya hecho: lectura de correo por IA → lead y eventos, buscador con mapa y Google Places, ranking, avisos de aforo/cierre, cotización por correo con extracción IA, recordatorios y **cola de aprobación**, hojas de servicio por restaurante, avisos y cambios de comensales con reenvío, portal con firma, comparativa multi-restaurante con «Elijo este», panel de actividad IA. Esto es lo que su CRM no tiene.

## 10. Plan por fases (de menos a más riesgo)

| Fase | Contenido | Riesgo | Depende de |
|---|---|---|---|
| 0 | Decidir menú único (sección 5) y renombrar «presupuesto»→«cotización» en pantallas y textos | Bajo | Juan |
| 1 | Etapas Petición/Presupuesto/Expediente/Cerrado + numeración + menús y listas con sus columnas | Bajo-medio | Fase 0 |
| 2 | Menú catálogo ampliado (tipo, descripción, margen por menú, capacidad, gratuidades) + camino A en el servicio | Medio | Fase 0 |
| 3 | Propuesta a la agencia con N opciones (ya hecha) integrada en la etapa «Presupuesto» | Bajo | Fase 1 |
| 4 | Panel económico, gratuidades, marcas de cobro/pago, bono y confirmaciones | Medio-alto | Textos y PDFs del cliente |
| 5 | Importación de agencias, restaurantes, menús y documentos | Alto | Exportación del cliente |
| 6 | Periodo en paralelo y formación (guía de usuario actualizada) | Medio | Todo lo anterior |

## 11. Preguntas abiertas

1. **Varias opciones a la agencia:** ¿cómo lo hacen hoy? (cada servicio tiene un único restaurante+menú). ¿Varios presupuestos PDF? ¿Por correo fuera del CRM?
2. ¿Qué espera exactamente «Pend. contestación»: la respuesta de la **agencia**? ¿Y se confirma con restaurante antes de enviar?
3. ~~Margen~~ **Decidido:** por restaurante, 20 % general por defecto.
3b. ¿Los documentos conservan su numeración (PET→PRE→EXP) o hay una numeración nueva en Odoo?
4. **Margen:** ¿por menú (como ellos) o global (como nosotros)? ¿La comisión de ellos es siempre venta − coste?
5. ¿Un documento con varios servicios: cada servicio puede tener un restaurante distinto (sí, parece), y en nuestro modelo es un evento con su búsqueda — confirmar que cuadra.
6. Textos reales de CONF. AGENCIA / CONF. RESTAURANTE / BONO y sus PDFs.
7. ¿Quién factura y con qué (RestaFact hoy)? ¿Entra la facturación en esta fase o después?
8. Conservar o no los platos estructurados y alérgenos de los menús.
9. ¿Importamos el histórico completo o solo lo abierto?
10. Exportación de datos: ¿quién la puede dar?

## 12. Lo que no se toca

- Cola de aprobación de correos externos (límite acordado).
- Margen global como valor por defecto (mientras no se decida otra cosa).
- Producción: nada de esto se despliega sin pasar por Juan.

---

## 13. Lo que aporta el cliente (manual, 4 PDFs y correo de Conchita, 2026-10-08)

Conchita (RestaGrup) envió el **manual de uso del CRM**, **ejemplos de presupuesto, confirmación agencia, confirmación restaurante y bono** (expediente EXP202610-17699) y un correo con una advertencia sobre datos incompletos. Resuelve casi todas las preguntas abiertas de la sección 11.

### 13.1 Flujo real confirmado (manual)
1. Entra la solicitud (email, teléfono o formulario web). Se identifica la agencia (existente o nueva: nombre fiscal, CIF, dirección fiscal, CP, teléfono, email, email de administración/facturas, nombre comercial, **método de pago: Prepago**; contacto principal).
2. **Nueva petición**: agencia + contacto, referencia del grupo («Grupo adulto/estudiante/senior/deportista» o el nombre dado), población, servicio, fecha (hora genérica 13:00 si no hay), **nº de comensales incluyendo chofer y guía**, **precio por persona** (el presupuesto de la agencia o, si no lo da, **un precio aproximado según tipo de grupo y servicio**), una línea por servicio. Se asigna comercial.
3. **Buscar restaurantes por menús**: lugar + año de temporada («Sevilla 25») para ver solo menús de la temporada; precio máximo; aforo; zona; nombre. Ojo/«+» para ver el menú/añadirlo. **Se pueden añadir varios restaurantes para dar más de una opción** (respuesta a la pregunta abierta nº 1). Si el restaurante no existe se crea (contrato = NO; menú con tipo, coste con IVA, venta = coste + 20 %, descripción copiada tal cual del restaurante).
4. **«Restaurante visible»**: si está activo la agencia ve nombre y dirección; si no, solo el menú. Normalmente visible, salvo cliente nuevo o sospechoso de saltarse la gestión.
5. **Presupuesto PDF** → se envía por email por el mismo hilo («los menús deben ser iguales para todo el grupo») → botón **«Pasar presupuesto»** (sale de Peticiones y entra en Presupuestos). Espera la confirmación en firme o cambios.
6. **Confirmar**: revisar lo que confirma la agencia (restaurante, menú, comensales), introducir comensales totales y **gratuidades**, botón **Confirmación restaurante** (proforma al restaurante) → esperar su **confirmación por escrito** → **Confirmación agencia** (proforma con datos bancarios) → se envía por el mismo hilo.
7. **Cambios**: nunca confirmar a la agencia antes de que el restaurante confirme por escrito. Cada cambio → proforma actualizada a agencia y restaurante. **Añadir servicios** a un expediente (nueva pestaña; «Restaurante visible» se desactiva solo y hay que reactivarlo); un servicio no confirmado se envía como presupuesto y se **cierra la pestaña** para dejar solo lo confirmado.
8. Antes del servicio: elección definitiva de platos, intolerancias, contacto del guía. **Observaciones** (salen en los PDFs de agencia y restaurante) vs **Notas internas** (solo Restagrup).
9. **Pago**: se pide ~1 semana antes del primer servicio, solo transferencia, 100 %; se verifica el justificante contra el total → «Pagado» → **Bono de agencia** (PDF con sello PAGADO). Administración doble control y avisa 72 h antes si no hay pago; paga a restaurantes y les envía justificante + proforma 48 h antes.
10. **Factura**: solo por email, la envía administración automáticamente, máx. 7 días **después** del último servicio.
11. **Incidencias**: las lleva el coordinador del grupo hasta resolverlas; ajustes económicos a administración.

### 13.2 Documentos (PDF)
| Documento | Contenido clave |
|---|---|
| **Presupuesto** | Cabecera (nº doc, ref. grupo, agencia, contacto, agente RestaGrup), por servicio: restaurante (si visible), tipo, hora, menú en texto, **«PRECIO NETO: 34,9 € + 2 gratuidades»** (**precio por menú, sin total**), nota de comensales finales a 48 h laborables, «sujeto a disponibilidad» |
| **Confirmación de reserva (agencia)** | Igual + «PVD 34,90 € IVA incluido, comensales 50 + 2 gratuidades», **total importe de reserva 1.745,00 €**, datos bancarios, justificante a grupos@, nota de 48 h |
| **Confirmación de reserva restaurante** | Sin precios de venta: **precio del restaurante 30,00 × 50 PAX = 1.500,00 €**, comensales 52, nota de facturación/SII |
| **Bono de servicio** | Sin precios; menú, total comensales, sello **PAGADO** |
Todos con logo, datos de empresa y pie. El menú aparece como bloque de texto (el que pegó el comercial).

### 13.3 Correo de Conchita: datos incompletos
- La agencia no siempre da todo: puede dar fecha, ciudad y comensales **sin presupuesto**. Se trabaja con **precio estimado/estándar** para crear la petición **sin volver a preguntar**. Igual con intolerancias, nº definitivo de comensales, etc. (se concretan durante el proceso).
- Cuando falte un dato **realmente necesario**: un aviso o «**cortafuegos**» para que el sistema consulte antes de continuar.

### 13.4 Impacto en lo que tenemos (diferencias a resolver)

| # | Hallazgo | Lo nuestro hoy | Cambio propuesto |
|---|---|---|---|
| 1 | El **presupuesto muestra precio por menú, sin total**; el total aparece al confirmar | La comparativa (PDF y portal) enseña **precio por persona y total** | **Quitar el total** de la comparativa/propuesta; el total sale en la confirmación |
| 2 | **«Restaurante visible»** oculta nombre y dirección | La comparativa siempre enseña el restaurante | Añadir el interruptor (por servicio/búsqueda; por defecto visible; se desactiva solo en servicios nuevos como hacen ellos, o según cliente) |
| 3 | **Menú = texto copiado del restaurante** | Menú estructurado en platos | Añadir **descripción en texto** (opcional) y que los PDFs usen la descripción si existe y, si no, los platos; decidir con Juan |
| 4 | Precio de venta **manual por menú** (ej. 30 → 34,90; ejemplo del manual 15 → 18 = 20 %) | `sale_price` editable con margen por restaurante (hecho) | Ya encaja; el 20 % es el valor por defecto |
| 5 | **Precio estimado** si la agencia no da presupuesto; no se vuelve a preguntar | No existe precio objetivo por servicio; la IA solo pide ciudad, fecha y comensales (bien) | Añadir **precio por persona estimado** al evento/servicio y **precios estándar** configurables por tipo de grupo y servicio |
| 6 | **«Cortafuegos»** ante datos realmente necesarios | Ya pedimos a la agencia ciudad/fecha/comensales (cola de aprobación) | Definir qué es imprescindible en cada etapa (p.ej. para confirmar: comensales finales, gratuidades, cuenta bancaria del restaurante) y bloquear el avance con aviso interno |
| 7 | **Gratuidades** y comensales incluyen chofer/guía | Sin concepto de gratuidad | Campo de gratuidades en el servicio; cobrar `comensales − gratuidades` |
| 8 | **Confirmación restaurante → escrita → Confirmación agencia** | Hoja de servicio al restaurante (sin esperar su confirmación) y proforma | Añadir **paso de confirmación escrita del restaurante** como condición para confirmar a la agencia; documentos con su formato |
| 9 | **Bono** tras marcar pagado, con sello PAGADO | No existe | Informe nuevo + estado «Pagado» |
| 10 | **Observaciones** (salen en PDFs) vs **Notas internas** | Chatter | Dos campos separados por servicio |
| 11 | **Pasar presupuesto**: la agencia se mueve de Peticiones a Presupuestos al enviar el PDF | Sin etapas | Etapas del apartado 4 (se confirma) |
| 12 | Cambios: restaurante primero, proforma actualizada a ambos | `change_wizard` ya regenera y reenvía | Alinear orden (restaurante confirma antes de avisar a la agencia) |
| 13 | **Menús por temporada** («Sevilla 25») | Sin temporada | Campo temporada/año o validez del menú; filtro rápido |
| 14 | Precios **con IVA incluido** | Presupuesto de venta con IVA 21 % provisional | Revisar que los importes se muestren con IVA incluido como ellos |
| 15 | Pago solo por transferencia, 100 %, ~1 semana antes; avisos 72 h / 48 h | Sin recordatorios de pago | Recordatorios y estados de pago (cola de aprobación) |
| 16 | Factura solo tras el último servicio, ≤ 7 días | Facturación no cubierta (VeriFactu pendiente) | Regla en la facturación (fase posterior) |

### 13.5 Preguntas que siguen abiertas
1. Menú: ¿descripción de texto, platos estructurados, o ambos? (punto 3).
2. «Restaurante visible»: ¿por servicio o por documento? ¿Por defecto activado o según el cliente?
3. Precios estándar estimados: ¿quién los fija y por qué ejes (tipo de grupo × servicio × ciudad)?
4. ¿Qué datos son «imprescindibles» en cada etapa para el cortafuegos?
5. ~~Pagos~~ **Decidido por Juan:** plazos y textos configurables en Ajustes y los gestionan ellos (administración).

---

## 14. Decisiones de Juan sobre §13 y siguientes pasos (2026-10-08)

**Hecho (dev, sin commit; 388 tests OK):**
- Margen por restaurante aplicado también al presupuesto de venta, producto-menú y cambio de restaurante.
- Comparativa/propuesta **sin total** (solo precio por persona); el total llegará con la confirmación.
- **«Restaurante visible»** por servicio/búsqueda, **activado por defecto**; desactivado muestra «Opción 1, 2…» y solo menú y precio. Aviso: el nombre del menú puede contener el del restaurante (como en su CRM, donde el nombre del menú sí sale).
- Menú con **descripción en texto Y platos estructurados** (ambos): si hay descripción es lo que sale; si no, los platos.

**Por decidir/diseñar:**

### 14.1 Precio estimado (lo fija Conchita) — opciones
Objetivo: crear la petición sin volver a preguntar a la agencia cuando no da presupuesto.
- **Opción A (mínima):** un único precio estándar por **tipo de servicio** (almuerzo, cena, desayuno, picnic…).
- **Opción B (recomendada):** tabla **tipo de grupo × tipo de servicio** (grupo adulto/estudiante/senior/deportista × almuerzo/cena/…), con un precio por casilla y un valor por defecto si no hay coincidencia.
- **Opción C (más fina):** B + **ciudad o país** (Sevilla ≠ Madrid ≠ París) y **temporada**.
- Variante útil con cualquiera: **precio automático por histórico** (media de los últimos X presupuestos de esa ciudad y servicio), siempre editable.
- Se configura en Ajustes → Restagrup por Conchita; el precio estimado se marca «estimado» hasta que la agencia o el restaurante lo concreten.

### 14.2 Cortafuegos (aviso antes de continuar) — propuesta según lo visto
Solo avisos **internos** al comercial (nunca correo a la agencia):
| Paso | Se avisa si falta |
|---|---|
| Crear petición | ciudad, fecha o comensales (ya lo pide la IA a la agencia) |
| Enviar propuesta | al menos un restaurante con menú y precio; comensales; precio por persona |
| Confirmación restaurante | comensales totales, gratuidades (aunque sean 0), hora, email del restaurante |
| Confirmación agencia | **confirmación escrita del restaurante**, cuenta bancaria del restaurante |
| Emitir bono | pago marcado como recibido |
| Antes del servicio | platos definitivos, intolerancias, contacto del guía |

### 14.3 Avisos y plazos configurables por ellos
En Ajustes → Restagrup, editables por RestaGrup: días antes del servicio para pedir el pago (hoy ~7), aviso de pago pendiente (72 h), pago a restaurantes (48 h), plazo de comensales finales (48 h laborables), plazo máximo de factura (7 días tras el último servicio) y los **textos** de cada aviso. Los avisos salen por la cola de aprobación.

## 15. Documentos de reserva — hecho (2026-10-08, dev, sin commit; 398 tests OK)

En `restagrup_agency_proposal`: **Confirmación de reserva (agencia)**, **Confirmación de reserva (restaurante)** y **Bono de servicio**, con el formato de los PDFs de Conchita (ejemplos en `docs/ejemplos/`).
- **Gratuidades** por línea de venta (`restagrup_gratuities`): la cantidad son los que pagan; en los documentos «50 + 2 gratuidades», PAX total 52.
- **Observaciones** del pedido (salen en agencia y restaurante; las notas internas siguen en el chatter y no salen).
- **Marcar como pagado / Desmarcar** + **Bono de agencia**: el bono no se emite hasta que está pagado; lleva sello PAGADO y **ningún precio**.
- **Agencia:** PVD, total, datos bancarios (cuenta de la compañía), nota de 48 h. Nunca coste ni margen.
- **Restaurante:** su precio (coste) × comensales de pago, sin precio al cliente; nota SII.
- Botones: «Confirmación agencia», «Marcar como pagado», «Bono de agencia» en el pedido; «Confirmación restaurante» en la hoja de servicio; columna Gratuidades en las líneas.
- **Pendiente de decidir (IVA):** su PVD incluye IVA (34,90 × 50 = 1.745 €); nuestro pedido suma el impuesto por encima (en dev 1.744,95 + impuestos = 2.006,69). Hay que decidir si el precio de venta lleva el IVA incluido (impuesto «precio incluido») para que cuadre con su documento.
- **Config. de compañía pendiente:** logo y diseño de documentos (cabecera/pie), moneda (€) y cuenta bancaria; en dev salen en blanco/«$».

## 16. Etapas, numeración e IVA — hecho (2026-10-08, dev, sin commit; 417 tests OK)

**Etapas del grupo (`restagrup_service_orders`):** Petición → Presupuesto → Expediente → Cerrado (+ cancelado con «perdido» de Odoo). El mismo registro cambia de fase.
- **Numeración PET/PRE/EXP + AAAAMM + nº** (ej. `PRE202610-17711`): el número no cambia en toda la vida del grupo, el prefijo sí. La secuencia empieza en **17711** (el último del CRM actual era 17710); es editable en Ajustes técnicos → Secuencias.
- **Botones** en la ficha: «Pasar a presupuesto», «Pasar a expediente», «Cerrar expediente» (solo en la fase que toca).
- **Automático:** enviar la propuesta/comparativa al cliente → Presupuesto; confirmar el pedido de venta (firma de la agencia o a mano) → Expediente. Solo hacia delante, nunca reabre un Cerrado. Cada cambio deja nota en el chatter.
- **Menús** Restagrup → Peticiones / Presupuestos / Expedientes / Terminados con sus columnas: Nº documento, Agencia, Ref. grupo, Nº servicios, Fecha y Población del 1º servicio, Restaurante, Nº comensales, Asignado a, Estado; buscador por número, agencia, referencia y población.
- **Migración de leads existentes** (idempotente): New→Petición, Qualified/Proposition→Presupuesto, Won→Cerrado, con pedido confirmado→Expediente; numeración a los que no tenían. Las etapas de serie de Odoo quedan al final y plegadas (no se borran).

**IVA como el suyo (precio con IVA incluido):** en dev el impuesto de venta está marcado «precio incluido». Para que el código no dependa de esa configuración: la **comisión** (margen) se calcula como precio × cantidad − coste × cantidad (1.745 − 1.500 = 245, como su panel) y «mantener precio al cliente» al cambiar de restaurante usa el importe con IVA (antes restaba el IVA). **Checklist para producción:** marcar el impuesto de venta como «Incluido en el precio» y moneda EUR en la compañía.

## 17. Cortafuegos — hecho (2026-10-08, dev, sin commit)

Antes de un paso importante el sistema **avisa de lo que falta y consulta**: muestra la lista y la persona elige «Volver a revisar» o «Continuar de todos modos» (queda anotado en el chatter quién continuó y qué se saltó). Es un aviso interno: nunca escribe a la agencia.
- **Configurable por RestaGrup** (Restagrup → Cortafuegos, solo administradores): cada comprobación se puede **desactivar** y poner en **«Avisar y consultar»** (por defecto) o **«Impedir continuar»**.
- **Comprobaciones de serie:** Pasar a presupuesto (agencia con contacto · servicios con ciudad, fecha y comensales · algún restaurante con presupuesto o menú) · Pasar a expediente (restaurante elegido · comensales) · Cerrar expediente (pago recibido · último servicio terminado) · Confirmación agencia (**restaurante confirmó por escrito** · restaurante con cuenta bancaria · compañía con cuenta bancaria) · Confirmación restaurante (fecha y hora · email del restaurante).
- Los botones «Confirmación agencia» y «Confirmación restaurante» pasan por el cortafuegos; el avance automático (enviar propuesta, confirmar pedido) no lo necesita.
- Pendiente de ampliar con lo que Conchita indique: platos definitivos, intolerancias y contacto del guía antes del servicio (hoy no hay campos para ello).

## 18. Plazos de pago y temporada del menú — hecho (2026-10-08, dev, sin commit)

**Plazos y textos de pago configurables (Ajustes → Restagrup).** Los fija y los lleva RestaGrup (administración): el sistema solo los calcula y los enseña, **no manda avisos solo**. De serie, como en su manual: pedir el pago 7 días antes del primer servicio, aviso de impago a las 72 h, pago a restaurantes a las 48 h, comensales finales 48 h laborables antes, factura como máx. 7 días tras el último servicio. Dos textos editables (pedir el pago y recordatorio urgente) con `{agencia}`.
- En cada pedido, grupo **«Plazos de pago»** con las fechas calculadas y los textos listos para copiar.
- Menú **Restagrup → Pagos pendientes**: pedidos confirmados sin cobrar, ordenados por fecha del primer servicio, con sus fechas.
- La nota de «comensales finales» de la confirmación a la agencia usa el plazo configurado.

**Temporada del menú.** Campo `Temporada` (año completo, por defecto el actual) y buscador de menús (Restagrup → Menús) por restaurante, población, temporada, **precio máximo** y **capacidad mínima**, con filtro «Temporada actual» y agrupación. Equivale al «Sevilla 25» del CRM actual.

## 19. Demo 2 — montada (2026-10-08)

Base aparte `bd-demo2` (puerto 8076) con el módulo `restagrup_demo2`; la demo 1 sigue intacta. 15 pasos: petición **incompleta** → la IA pide solo la fecha (cola de aprobación) → respuesta de la agencia → fases como su CRM (listas con 12 documentos de ejemplo) → fichas y menús con buscador → tres presupuestos de restaurante → propuesta con varias opciones (restaurante visible/oculto, portal «Elijo este») → pedido y firma (pasa a Expediente) → gratuidades, confirmaciones, pago y bono. Guion en `demo2/README.md`. Recorrido completo validado con la IA real y 13 tests propios. **Fuera de la demo, a propósito:** cortafuegos, plazos de pago e importación de datos.
Errores reales hallados al montarla y corregidos: líneas de presupuesto de restaurante perdían el precio al cambiar los comensales; lista de Peticiones sin la agencia en leads por correo; temporada con separador de miles; formulario del grupo con campos de embudo de ventas.
