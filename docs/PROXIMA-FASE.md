# Próxima fase — cerrar la brecha con el "Recorrido de un grupo en Odoo"

Origen: `2026-09-08_recorrido-grupo-odoo.pdf` (Cositt Technology, para Restagrup —
Inversiones y Promociones Aracil SL, septiembre 2026, por Gerard Perat). Es un documento
de simulación para el cliente ("no es una propuesta ni un presupuesto") que recorre un
grupo real (Viajes Sol Levante, 47 pax, Toledo+Aranjuez) en 6 pasos, comparando
HOY (RestaGest+RestaFact) vs EN ODOO.

Este doc traduce esos 6 pasos a lo que ya existe en el código y lo que falta construir.
Objetivo: que la siguiente sesión de desarrollo arranque directo por la lista, sin releer
el PDF.

## Los 6 pasos del documento → estado real del código

| # | Paso del documento | Módulo que lo cubre | Estado |
|---|---|---|---|
| 1 | Petición entra por correo → crea oportunidad sola en CRM | `restagrup_email_ai` | ✅ Construido |
| 2 | Buscar restaurante: ficha con aforo/parking/cierre/idioma/cuenta/contacto, filtro instantáneo | `restagrup_restaurants` | ✅ Construido |
| 3 | Presupuesto a la agencia, recordatorio si no contestan, confirmación con un clic | `restagrup_restaurants` (pedir presupuesto) / falta el resto | 🟡 Parcial — ver A y B |
| 4 | Confirmado → hoja por restaurante, envío conjunto, hilo propio por restaurante | `restagrup_service_orders` | ✅ Construido y probado en vivo (2026-09-29) |
| 5 | Cambio de comensales → un botón regenera y reenvía a los 3 restaurantes | `restagrup_service_orders::action_resend_restaurant_orders` | ✅ Construido — falta reenvío a la agencia (ver E) |
| 6 | Factura desde el expediente, VeriFactu, panel de dirección | Odoo core (`account` + localización española) | ⬜ No es módulo nuestro — ver F |

## Lo nuevo a construir, en orden sugerido

### A. Recordatorio automático por cron — ✅ CONSTRUIDO 2026-09-30 (solo dev, sin desplegar)

Hecho en `restagrup_restaurants` con TDD (9 tests nuevos, módulo 36/36): campo
`quote_reminder_sent_date`, `action_send_quote_reminder()`, `_cron_send_quote_reminders()`, cron
diario `ir_cron_send_quote_reminders` (`data/ir_cron_data.xml`) y texto configurable en Ajustes →
Restagrup (`restagrup.quote_reminder_text`, vacío = texto por defecto). **Un solo recordatorio por
petición**: se rearma si se vuelve a pedir presupuesto. Una línea sin email se omite sin parar el
resto. Pendiente: probar en navegador real y desplegar a prod (necesita SMTP saliente, ver TODO.md).

Diseño original (histórico):

Hoy: `quote_is_stale` calcula el badge "⚠ N días sin respuesta" y hay un botón manual
"Reenviar petición" (llama a `action_request_quote` otra vez). El documento pide que
**Odoo lo mande solo**, sin que nadie lo dispare.

- Nuevo `ir.cron` diario en `restagrup_restaurants` que busca líneas con
  `etiqueta = 'solicitado'` y `quote_is_stale = True` sin un recordatorio ya mandado hoy.
- Nuevo campo `quote_reminder_sent_date` (o reutilizar `message_ids` para detectar si ya
  se mandó un recordatorio) para no reenviar cada día sin parar.
- Plantilla de texto configurable (Ajustes → Restagrup, nuevo campo texto o
  `mail.template`) en vez de reusar el cuerpo de `action_request_quote()` tal cual —
  el documento dice "con vuestro texto", implica un mensaje distinto al de la petición
  original.
- Reusa `message_post(..., outgoing_email_to=...)` igual que `action_request_quote()` —
  mismo mecanismo de hilo, no reinventar.

### B. Confirmación del presupuesto con un clic desde el email — ✅ VERIFICADO 2026-09-30

**Resultado (probado en dev con POST real a `/my/orders/<id>/accept`, sin login):**

- Funciona de serie **con firma, sin pago**: el `sale.order` pasa a `sale`, queda `signed_by`, y
  `restagrup_service_orders` genera la hoja de servicio (purchase.order) del restaurante.
- **No existe "un clic" puro en Odoo 19**: el botón de aceptar del portal solo se muestra si el
  pedido exige firma o pago (`_has_to_be_signed()` / `_has_to_be_paid()`). Con ambos en `False`,
  `/accept` responde "El pedido no está en un estado que requiera la firma del cliente".
- **Config obligatoria en Ajustes → Ventas → Confirmación online:** firma = sí, **pago = no**.
  Por defecto la compañía trae firma **y** pago a `True`, así que la agencia tendría que pagar
  online. Hay que cambiarlo en dev y en producción.
- Si se quiere un clic real sin dibujar firma: habría que escribir una ruta propia tokenizada que
  llame a `action_confirm()`. No se ha hecho; decisión pendiente de Juan.

Texto original del paso (histórico):

El documento describe: la agencia recibe el presupuesto, hace clic, y el `sale.order`
pasa a confirmado solo. **Esto ya existe nativo en Odoo** (portal de presupuestos +
aceptación online) — antes de escribir código, verificar en el dev local:

1. Enviar un presupuesto real (`action_quotation_send` / botón "Enviar") a una `sale.order`
   con un restaurante elegido.
2. Abrir el link de portal que recibe el cliente y confirmar que "Aceptar" funciona sin
   login y pasa el pedido a `sale`.
3. Si funciona de serie: no hay nada que construir, solo probarlo y documentarlo en la
   guía de usuario.
4. Si no funciona (falta configuración, o el flujo de `restagrup_service_orders` lo
   rompe en algún punto): ahí sí investigar qué lo bloquea antes de tocar código.

### C. Menús como productos con precio (el cambio de modelo más grande)

Hoy `restagrup.restaurant.search.line.quote_amount` es un float suelto y
`quote_notes` es texto libre. El documento muestra menús como líneas de producto real
("Menú grupo Toledo — comida", cantidad, precio unitario) que se arrastran al
presupuesto sin copiar nada a mano.

- Nuevo modelo `restagrup.restaurant.menu` (o extender `product.template` con un campo
  `restaurant_id`) — un menú = un producto vendible, con precio, ligado a un restaurante.
- Vista en la ficha del restaurante (`res.partner`) para gestionar sus menús.
- En `restagrup_service_orders::action_create_sale_order`, en vez de una sola línea con
  `quote_amount`, permitir elegir uno o más menús del restaurante y que cada uno sea su
  propia `sale.order.line`.
- Esto es el cambio que más toca: afecta `restagrup_restaurants` (nuevo modelo + vista) y
  `restagrup_service_orders` (generación de la sale order). Hacerlo el último de los
  tres primeros para no bloquear A y B mientras se diseña bien el modelo de menús.

### D. Resumen "qué restaurante confirmó / cuál no" — ✅ CONSTRUIDO 2026-09-30 (solo dev)

"Confirmado" = hoja de servicio no cancelada con `restagrup_response_state == 'accepted'` (la
clasificación IA de la respuesta del restaurante). Campos `restagrup_confirmed_count`,
`restagrup_pending_count`, `restagrup_confirmation_summary` ("1/3") en `sale_order.py` + stat button
en la vista del presupuesto. Rechazado / falta info / poco claro cuentan como pendiente. 6 tests.

Diseño original (histórico):

Dato ya existe (`purchase.order.state` por cada hoja de servicio) — falta mostrarlo de
un vistazo en el `sale.order`.

- Campo computado `restagrup_confirmed_count` / `restagrup_pending_count` en
  `restagrup_service_orders/models/sale_order.py`.
- Un stat button o badge en la vista del presupuesto ("2/3 restaurantes confirmados").

### E. Proforma actualizada auto-reenviada a la agencia — ✅ CONSTRUIDO 2026-09-30 (solo dev)

`action_resend_restaurant_orders` ahora, si reenvió algo a algún restaurante, manda también el
presupuesto actualizado a la agencia (`sale.email_template_edi_sale`) y lo anota en el chatter. Sin
email de agencia no falla: deja una nota para avisarla a mano. Sin cambios no manda nada. 3 tests.

Diseño original (histórico):

Hoy `action_resend_restaurant_orders` reenvía solo a los restaurantes. El documento dice
que la proforma actualizada también sale sola a la agencia desde el mismo sitio.

- Extender `action_resend_restaurant_orders` (o un botón hermano) para que además mande
  la `sale.order` actualizada al contacto de la agencia (mismo mecanismo de email que ya
  existe para las hojas de servicio).

### F. VeriFactu (no es código nuestro — es checklist de configuración)

Obligatorio desde 2027-01-01. Es la localización fiscal española de Odoo
(`l10n_es` + módulo VeriFactu), no un módulo Restagrup. Tarea: verificar en
`restagrup.cositt.net` que la compañía tiene la localización española instalada y
VeriFactu configurado, antes de esa fecha. No depende de esta fase de desarrollo, pero
hay que confirmar que no lo bloquea nada de lo que estamos construyendo encima
(facturación desde `sale.order` en el paso 6).

## Qué NO tocar

El documento es explícito: el agente de IA de `motor-restaurantes` sigue sobre RestaGest
tal cual, no se toca. Si algún día migra a Odoo, se conecta reusando A (el correo que ya
sabe leer), lo construido en `restagrup_restaurants` (paso 2) y E (avisos del paso 5) —
no hay que preparar nada especial para eso ahora.
