# Restagrup — Buscador de restaurantes y flujo de presupuesto (Odoo 19)

Módulos custom de Odoo 19 que cubren el flujo completo de una agencia que organiza eventos de
grupo en restaurantes: desde que llega la petición por email hasta la propuesta final al
cliente, pasando por la búsqueda de restaurantes, la petición y captura de presupuestos, y la
generación de las hojas de servicio.

Guía de uso completa, con capturas reales de cada paso: [`docs/Guia-usuario-flujo-restaurantes-presupuesto.pdf`](docs/Guia-usuario-flujo-restaurantes-presupuesto.pdf).

## Módulos

| Módulo | Qué hace | Depende de |
|---|---|---|
| `restagrup_core` | Ajustes compartidos: claves de Google Places API y de los proveedores LLM (Groq/Gemini), margen de venta por defecto. No aporta funcionalidad visible por sí solo. | `base` |
| `restagrup_restaurants` | Campos de restaurante en Contactos (aforo, parking de autobús, cocina, precio...) y el buscador de restaurantes por zona: combina partners ya guardados con resultados en vivo de Google Places, con mapa propio (Leaflet), pipeline de presupuesto (pedir → recibir → elegir) y captura automática de la respuesta del restaurante por email. | `mail`, `contacts`, `crm`, `restagrup_core`, `base_geolocalize` |
| `restagrup_service_orders` | Al confirmar un presupuesto, genera una hoja de servicio (pedido de compra) por cada restaurante elegido. Detecta cambios posteriores (comensales, notas) y permite reenviar solo lo afectado. Clasifica por IA las respuestas de los restaurantes a la hoja de servicio. | `sale_management`, `purchase`, `restagrup_restaurants`, `restagrup_core` |
| `restagrup_email_ai` | Extrae por IA ciudad, fechas, comensales y tipo de grupo del email de la agencia al crear el lead — siempre a revisar antes de convertir en presupuesto. | `crm`, `restagrup_core` |
| `restagrup_agency_proposal` | Genera el PDF de propuesta final agrupado por restaurante, con link de portal para que la agencia lo vea sin cuenta interna. | `sale_management`, `portal`, `restagrup_service_orders` |

Todos con licencia LGPL-3.

## Instalación

1. Copiar estas 5 carpetas a un `addons_path` de una instancia Odoo 19 (Community o Enterprise —
   `restagrup_restaurants` usa `base_geolocalize`, que es de Community; no depende de nada
   exclusivo de Enterprise).
2. Actualizar la lista de aplicaciones (Ajustes → Aplicaciones → Actualizar lista de
   aplicaciones).
3. Instalar **Restagrup - Propuesta a agencias** (`restagrup_agency_proposal`) — Odoo instala en
   cascada el resto de dependencias (`restagrup_service_orders` → `restagrup_restaurants` →
   `restagrup_core`) y `restagrup_email_ai` puede instalarse aparte si no hace falta la propuesta
   de agencia.

## Configuración necesaria

En **Ajustes → Restagrup**:

- **Google Places API Key** — necesaria para que el buscador traiga candidatos nuevos por
  ciudad/zona. Sin ella, el buscador solo devuelve partners ya guardados en Odoo.
- **Orden de proveedores IA** (p. ej. `groq,gemini`) y sus claves — usados para extraer datos del
  lead, clasificar respuestas y proponer importe/notas de presupuesto a partir de texto. Sin
  clave configurada, esas extracciones simplemente no proponen nada — nunca bloquean el flujo
  manual.
- **Margen por defecto (%)** — aplicado automáticamente al crear un presupuesto de venta desde el
  restaurante elegido. En 0, el presupuesto sale a coste.

### Opcional: captura automática de la respuesta del restaurante

Para que la respuesta de un restaurante a una petición de presupuesto se enlace sola a la línea
correcta (sin copiar/pegar el texto a mano), configurar en **Ajustes → Técnico → Correo entrante
→ Servidores de correo entrante** un servidor IMAP apuntando al buzón que recibe esas respuestas,
con **"Crear un nuevo registro"** puesto en **Resultado del buscador de restaurantes**. Sin este
paso, el flujo sigue funcionando igual: la respuesta se pega a mano en el diálogo "Registrar
presupuesto" y se pulsa "Extraer con IA" (ver guía de uso, Parte 1, Paso 8).

## Flujo de datos (de un vistazo)

```
crm.lead (petición del grupo, datos extraídos por IA)
  └─ restagrup.restaurant.search (una búsqueda: ciudad, aforo, filtros)
       └─ restagrup.restaurant.search.line (cada candidato: partner propio o Google Places)
            · pedir presupuesto → email real (mail.thread) → respuesta capturada sola o pegada a mano
            · elegir (solo con presupuesto recibido)
                └─ sale.order (presupuesto de venta, margen aplicado)
                     └─ purchase.order por restaurante (hoja de servicio, al confirmar)
                          └─ PDF de propuesta a la agencia (restagrup_agency_proposal)
```

## Tests

`restagrup_restaurants` (29 tests) y `restagrup_service_orders` (10 tests), `TransactionCase`,
LLM mockeado con `unittest.mock.patch` — sin llamadas de red reales.

```bash
odoo -d <base_de_datos> --test-enable \
  --test-tags /restagrup_restaurants,/restagrup_service_orders \
  --stop-after-init --http-port=8973
```

(`--http-port` con un puerto libre distinto del servidor web normal — necesario si el servidor
ya está corriendo en el mismo contenedor/proceso.)
