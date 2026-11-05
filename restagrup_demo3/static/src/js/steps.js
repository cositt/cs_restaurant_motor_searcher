/** @odoo-module **/
// Recorrido de la demo 3: un grupo de principio a fin. Cada paso: fase, qué se hace (todo), qué se dice (say), dónde
// clicar y por qué (how) y sus botones (call = acción de la guía, open = abrir un registro, action = abrir una lista,
// mark = paso de «mirar» que cuenta como hecho al abrirlo).

const A = {
    pending: "restagrup_restaurants.action_restagrup_pending_mail",
    restaurants: "restagrup_restaurants.action_restaurant_list",
    menus: "restagrup_restaurants.action_restaurant_menu",
    templates: "restagrup_restaurants.action_restagrup_mail_template",
    aiLog: "restagrup_restaurants.action_ai_log",
    peticiones: "restagrup_service_orders.action_peticiones",
    presupuestos: "restagrup_service_orders.action_presupuestos",
    expedientes: "restagrup_service_orders.action_expedientes",
    terminados: "restagrup_service_orders.action_terminados",
    firewall: "restagrup_service_orders.action_firewall_checks",
    restaurantPayments: "restagrup_agency_proposal.action_restaurant_payments",
};

// Resumen de lo que cambia con la PPT de Conchita (2026-11-04): se enseña arriba de la guía.
export const CHANGES = [
    ["Peticiones", "Título = referencia del grupo; fecha con hora y año; «Servicios» primero; «Guardar» y colores."],
    ["Correos de entrada", "Agencia y contacto desde la firma; CIF y razón social se piden al firmar, por la cola."],
    ["Buscador", "Volver a la petición, Grupo/Agencia, filtros plegados, búsqueda por nombre, orden por precio estimado."],
    ["Restaurantes", "Etapas en la tarjeta, «Ver menús» con coste y venta, pedir un menú concreto, «Pegar respuesta»."],
    ["Correos a restaurantes", "Localizador en todos los correos y asunto nuevo; agencia visible en la cola."],
    ["Menús", "Pestaña «Menús» en la petición; «Completar platos con IA» para los menús sin platos."],
    ["Propuesta y presupuesto", "Una propuesta con todos los servicios desde la petición, la agencia elige en un enlace y un único presupuesto PET… con vuestro formato."],
    ["Envío y firma", "«Enviar presupuesto a la agencia», aviso del siguiente paso y sin «Aceptar» en la vista previa del empleado."],
];

const P1 = "1 · Llega la petición";
const P2 = "2 · Restaurantes y presupuestos";
const P3 = "3 · Propuesta, elección y firma";
const P4 = "4 · Expediente y hoja de servicio";
const P5 = "5 · Pagos (unos días antes del servicio)";
const P6 = "6 · Factura y cierre (después del servicio)";
const P7 = "7 · Lo configuráis vosotros";

export const STEPS = [
    // --- 1 · petición ---
    { phase: P1, key: "email", title: "Llega la petición de una agencia, sin fecha",
      news: ["La petición se llama como la referencia del grupo («Senior Andalucía CV-2611») y en la lista la fecha sale con hora y año (diapo. 1).", "Agencia y contacto salen de la firma: teléfono, dirección y web en la ficha de la agencia (diapo. 2)."],
      todo: "Pulsa «Simular correo de la agencia» y abre Peticiones.",
      say: "Un correo normal de una agencia. Nadie teclea nada: la petición se crea sola, con la agencia como empresa y Lucía como contacto. Sale en rojo «Pendiente de asignación» y salta el aviso abajo a la izquierda.",
      how: [
          ["Pulsa «Simular correo de la agencia».", "Es como si Costa Viajes escribiera al buzón de peticiones."],
          ["Pulsa «Abrir Peticiones».", "La petición ya está, con población y comensales leídos por la IA; en rojo, sin asignar."],
          ["Señala la burbuja de avisos abajo a la izquierda.", "Cada persona ve lo que tiene pendiente sin buscarlo."],
      ],
      buttons: [
          { label: "Simular correo de la agencia", call: "simulate_agency_email", enabled: (s) => !s.done.email },
          { label: "Abrir Peticiones", action: A.peticiones, enabled: (s) => s.done.email },
      ] },
    { phase: P1, key: "assign", title: "Se asigna a un comercial",
      news: ["Botón «Guardar» a la vista y colores: verde para avanzar, azul para guardar, rojo para cancelar (diapo. 1)."],
      todo: "En la petición, elige un Comercial y guarda.",
      say: "Asignación manual, como pedisteis. Al asignarla, a esa persona le llega el aviso y los correos de este grupo pasan a ser suyos.",
      how: [
          ["Pulsa «Abrir la petición».", "La ficha del grupo, con el correo original a la derecha. Título: la referencia del grupo."],
          ["Abre el contacto (Lucía Prieto) y su empresa, Costa Viajes Ibéricos.", "Teléfono, dirección y web rellenados desde la firma del correo."],
          ["Campo «Comercial»: elige a Marta (o a quien quieras) y pulsa «Guardar».", "Desaparece el rojo y queda anotado en el historial."],
      ],
      buttons: [{ label: "Abrir la petición", open: "lead", enabled: (s) => s.done.email }] },
    { phase: P1, key: "ask", title: "La IA ve que falta la fecha y prepara el correo",
      news: ["Todos los correos llevan el localizador de la petición («Ref.: …») y en la cola se ve la agencia, solo para el equipo (diapo. 4)."],
      todo: "Abre «Pendientes de aprobar»: está el correo para la agencia pidiendo solo lo que falta.",
      say: "No pregunta lo que ya sabe: solo la fecha. Y no sale nada sin que una persona lo apruebe.",
      how: [
          ["Pulsa «Abrir Pendientes de aprobar» y entra en el correo para Costa Viajes.", "El borrador pide solo la fecha; a la derecha, el correo original y el porqué."],
      ],
      buttons: [{ label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.email }] },
    { phase: P1, key: "approve", title: "Se aprueba el envío",
      todo: "Pulsa «Aprobar y enviar» en el correo pendiente.",
      say: "El clic es la aprobación humana. El correo sale por el mismo hilo de la petición. Si un día os fiáis, cada tipo de correo se puede poner en automático.",
      how: [
          ["En ese correo, «Aprobar y enviar». Vuelve a la guía con «Guía» en el menú.", "El paso se marca solo."],
      ],
      buttons: [{ label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.ask }] },
    { phase: P1, key: "reply", title: "La agencia contesta y la IA completa los datos",
      news: ["«Servicios» es la primera pestaña de la petición y «Evento» pasa a llamarse «Servicio» (diapo. 1)."],
      todo: "Pulsa «Simular respuesta de la agencia» y mira la pestaña Servicios de la petición.",
      say: "La respuesta vuelve al hilo y la IA rellena fecha y hora sin pisar nada. La agencia no da presupuesto: sale un precio orientativo, marcado «Estimado», sacado de los baremos.",
      how: [
          ["Pulsa «Simular respuesta de la agencia».", "La agencia da la fecha: dentro de 5 días, a las 14:00."],
          ["«Abrir la petición» → pestaña «Servicios».", "Fecha y hora rellenadas por la IA; precio por persona «Estimado»."],
      ],
      buttons: [
          { label: "Simular respuesta de la agencia", call: "simulate_agency_reply", enabled: (s) => s.done.approve && !s.done.reply },
          { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.email },
      ] },
    // --- 2 · restaurantes ---
    { phase: P2, key: "menus", title: "Fichas de restaurante y menús",
      news: ["Menús con «Platos sin completar»: «Completar platos con IA» los saca de la descripción, de uno en uno o todos a la vez (diapo. 6)."],
      todo: "Abre Restaurantes y Menús.",
      say: "Cada restaurante guarda sus menús: tipo, coste, precio de venta con su margen y temporada.",
      how: [
          ["«Abrir Restaurantes» → entra en Bodega San Telmo.", "Aforo, contacto, margen y su pestaña de menús."],
          ["«Abrir Menús»; filtra por Sevilla y temporada 2026.", "De aquí sale lo que luego ve la agencia."],
          ["Selecciona los menús con «Platos sin completar» → «Completar platos con IA».", "La IA saca los platos de la descripción y queda en Actividad IA."],
      ],
      buttons: [
          { label: "Abrir Restaurantes", action: A.restaurants, mark: "menus", enabled: (s) => s.done.reply },
          { label: "Abrir Menús", action: A.menus, mark: "menus", enabled: (s) => s.done.reply },
      ] },
    { phase: P2, key: "search", title: "Buscar restaurantes",
      news: ["«← Volver a la petición» y Grupo y Agencia por separado (diapo. 3).", "Filtros plegados y «Buscar restaurante por nombre» (diapo. 3).", "Ordenados por cercanía al precio estimado; aviso en los que se salen más de un 15 % (diapo. 2)."],
      todo: "En la petición, pulsa «Buscar para todos los servicios».",
      say: "Salen solo los de Sevilla con aforo para 45, ordenados por cercanía al precio estimado: primero los nuestros y después los de Google. Con vuestros baremos (comida, 16 €) casi todos avisan de que se salen: es la señal para revisar el baremo o hablarlo con la agencia.",
      how: [
          ["«Abrir la petición» → «Buscar para todos los servicios».", "La búsqueda nace con la ciudad, la fecha y los comensales del grupo."],
      ],
      buttons: [{ label: "Abrir la petición", open: "lead", enabled: (s) => s.done.reply }] },
    { phase: P2, key: "request", title: "Pedir presupuesto a tres restaurantes",
      news: ["Cada tarjeta muestra la etapa: Interesado → Pedido → Recibido → Elegido (diapo. 5).", "«👁 Ver menús»: menús del restaurante con coste y venta, y pedir disponibilidad de uno concreto (diapo. 5).", "Asunto nuevo: «Presupuesto para grupos — localizador — ciudad fecha» (diapo. 4)."],
      todo: "Marca «Interesado» en Taberna del Patio Andaluz, Casa Giralda Grupos y Bodega San Telmo y pulsa «Pedir presupuesto a interesados».",
      say: "Un correo a cada restaurante, con fecha, servicio y comensales. Al restaurante le llega nuestro precio de coste, nunca el de venta.",
      how: [
          ["«Abrir la búsqueda»: enseña el orden por precio estimado, los filtros plegados y «Volver a la petición».", "Los que se salen del precio llevan aviso."],
          ["En Bodega San Telmo, «👁 Ver menús».", "Coste y venta de cada menú; desde ahí se pide un menú concreto."],
          ["«Interesado» en los tres.", "La etapa de la tarjeta se ilumina: Interesado."],
          ["Arriba, «Pedir presupuesto a interesados» → «Aceptar».", "Salen los tres correos. (Atajo: «Pedir presupuesto a los 3».)"],
      ],
      buttons: [
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search },
          { label: "Pedir presupuesto a los 3", call: "request_quotes", enabled: (s) => s.done.search && !s.done.request },
      ] },
    { phase: P2, key: "answers", title: "Los restaurantes contestan con su menú",
      news: ["Los restaurantes dan precio por persona y así se registra (urgente 1)."],
      todo: "Pulsa «Simular respuestas de los restaurantes».",
      say: "Cada respuesta se enlaza sola a su restaurante. La IA lee el importe y además guarda el menú que proponen en la ficha del restaurante, con sus platos.",
      how: [
          ["Pulsa «Simular respuestas de los restaurantes» (tarda unos segundos: la IA lee tres correos).", "Cada uno contesta en texto libre, como lo haría de verdad."],
          ["«Abrir la búsqueda»: a la derecha, las respuestas.", "El importe propuesto queda «sin confirmar»."],
      ],
      buttons: [
          { label: "Simular respuestas de los restaurantes", call: "simulate_restaurant_replies", enabled: (s) => s.done.request && !s.done.answers },
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search },
      ] },
    { phase: P2, key: "menu_review", title: "Revisar los menús que ha creado la IA",
      news: ["Los menús que crea la IA ya traen sus platos; los antiguos se completan con el botón de IA (diapo. 6)."],
      todo: "Abre Menús: los nuevos salen «Sin revisar». Entra en cada uno y pulsa «Revisado».",
      say: "La IA no pisa lo que hay: si ya había uno parecido, crea otro con la fecha y avisa. Lo que crea queda marcado hasta que una persona lo revisa.",
      how: [
          ["«Abrir Menús» → filtro «Sin revisar».", "Los menús que acaban de mandar los restaurantes, con platos y precio de coste."],
          ["En cada uno: comprueba platos y precio → «Revisado».", "Se quita la marca naranja."],
      ],
      buttons: [{ label: "Abrir Menús", action: A.menus, enabled: (s) => s.done.answers }] },
    { phase: P2, key: "confirm", title: "Una persona confirma los importes",
      news: ["Un solo sitio para la respuesta: «Pegar respuesta» → «Leer con IA: precio y menú» → «Registrar» (diapo. 4).", "Precio por persona y precio a la agencia con la comisión, a la vista en la tarjeta (urgente 1)."],
      todo: "En cada restaurante, «Pegar respuesta» → «Registrar» (o el atajo «Confirmar los 3»).",
      say: "La IA propone, una persona confirma. El importe no cuenta hasta que alguien lo da por bueno.",
      how: [
          ["«Abrir la búsqueda» → en una tarjeta, «Pegar respuesta» → «Registrar».", "Así lo haría una persona; enseña uno a mano."],
          ["Para los otros dos, «Confirmar los 3».", "Pasan a «Presupuesto recibido»."],
      ],
      buttons: [
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search },
          { label: "Confirmar los 3", call: "confirm_quotes", enabled: (s) => s.done.answers && !s.done.confirm },
      ] },
    // --- 3 · propuesta ---
    { phase: P3, key: "proposal", title: "Propuesta con varias opciones para la agencia",
      news: ["La propuesta sale desde la petición, con todos los servicios del grupo (urgente 4).", "Pestañas «Propuesta» y «Menús» en la petición (diapo. 6). El buscador ya no envía nada al cliente."],
      todo: "En la petición, «Enviar propuesta a la agencia».",
      say: "Todos los servicios del grupo en una sola propuesta: menú y precio por persona de cada opción, IVA incluido y sin totales. Con un cliente nuevo se ocultan los nombres. Antes de enviar sale la revisión: qué sale y a quién.",
      how: [
          ["«Abrir la petición» → pestaña «Propuesta».", "Los restaurantes con presupuesto de cada servicio, con el precio a la agencia y nuestro coste."],
          ["«Enviar propuesta a la agencia»: «Mostrar los restaurantes» se puede apagar.", "Las opciones sin decir dónde están."],
          ["«Enviar» → «Revisado: enviar».", "El cortafuegos enseña lo que sale antes de enviarlo. El grupo pasa a Presupuesto."],
      ],
      buttons: [
          { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.confirm },
          { label: "Abrir Presupuestos", action: A.presupuestos, enabled: (s) => s.done.proposal },
      ] },
    { phase: P3, key: "choose", title: "La agencia elige su restaurante",
      news: ["Un solo enlace: la agencia elige un restaurante por servicio (urgente 4)."],
      todo: "«Ver como la agencia» → «Elijo este» en una opción de cada servicio.",
      say: "La agencia elige desde un enlace, sin usuario, un restaurante por servicio. A nosotros nos salta el aviso «la agencia ha elegido».",
      how: [
          ["Pulsa «Ver como la agencia».", "Otra pestaña: lo que ve la agencia, servicio a servicio."],
          ["«Elijo este» en una opción y vuelve a Odoo.", "La elección llega sola a la petición."],
      ],
      buttons: [{ label: "Ver como la agencia", open: "portal_search", enabled: (s) => s.done.proposal && s.search_portal_url }] },
    { phase: P3, key: "order", title: "Presupuesto de venta",
      news: ["«Crear presupuesto» en la petición: uno solo con todos los servicios (urgente 4).", "Número de la petición, válido hasta el día del servicio, sin «Mostrar margen» y PDF con vuestro formato (urgentes 2 y 3).", "Botón «Enviar presupuesto a la agencia» y aviso del siguiente paso arriba (diapo. 8)."],
      todo: "En la petición, «Crear presupuesto».",
      say: "Un solo presupuesto con todos los servicios y el restaurante elegido en cada uno: precio por persona con nuestro margen e IVA incluido. Lleva el número de la petición y vale hasta el día del servicio. La agencia nunca ve nuestro coste.",
      how: [
          ["«Abrir la petición» → «Crear presupuesto».", "Una línea por servicio: restaurante, fecha, hora, comensales, menú."],
          ["«Imprimir»: el PDF con vuestro formato.", "Cabecera del grupo, un bloque por servicio y el precio neto por persona."],
      ],
      buttons: [{ label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.order,
                  fallback: { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.choose } }] },
    { phase: P3, key: "sign", title: "La agencia firma y el grupo pasa a Expediente",
      news: ["Al firmar se prepara, en la cola, el correo a la agencia pidiendo CIF y razón social (diapo. 2).", "En la vista previa desde Odoo el empleado ya no ve «Aceptar y firmar» ni «Rechazar» (diapo. 8); aquí la demo lo deja para hacer de agencia."],
      todo: "«Ver como la agencia» → «Aceptar y firmar». Luego mira Expedientes.",
      say: "Al firmar, el grupo pasa solo a Expediente y se crea la hoja de servicio del restaurante, con nuestro coste.",
      how: [
          ["«Ver como la agencia» → «Aceptar y firmar» (la firma sale con su nombre) → «Aceptar y firmar».", "La firma es el sí del cliente."],
          ["Vuelve a Odoo → «Abrir Expedientes».", "El grupo ya está en Expedientes; columna «Pendiente para cerrar»."],
      ],
      buttons: [
          { label: "Ver como la agencia", open: "portal_order", enabled: (s) => s.done.order },
          { label: "Abrir Expedientes", action: A.expedientes, enabled: (s) => s.done.sign },
      ] },
    // --- 4 · expediente ---
    { phase: P4, key: "docs", title: "Gratuidades y confirmaciones",
      todo: "«Aplicar 2 gratuidades» y mira «Confirmación agencia» en el presupuesto.",
      say: "Guía y chófer no pagan, pero cuentan como comensales. Cada uno recibe su documento: el restaurante con su precio, la agencia con el suyo.",
      how: [
          ["Pulsa «Aplicar 2 gratuidades».", "45 comensales, 43 de pago."],
          ["«Abrir el presupuesto» → «Confirmación agencia».", "PDF para la agencia."],
      ],
      buttons: [
          { label: "Aplicar 2 gratuidades", call: "apply_gratuities", enabled: (s) => s.done.sign && !s.done.docs },
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
      ] },
    { phase: P4, key: "sheets_sent", title: "Enviar la hoja de servicio al restaurante",
      todo: "En el presupuesto, «Enviar hojas de servicio».",
      say: "Cada restaurante recibe su hoja para confirmar por escrito: servicio, menú, comensales y su precio de coste, nunca el de la agencia.",
      how: [
          ["«Abrir el presupuesto» → «Enviar hojas de servicio» → confirma.", "Sale el correo con el PDF de la hoja."],
          ["«Abrir la hoja de servicio».", "Lo que nos cobra el restaurante y, a la derecha, el correo enviado."],
      ],
      buttons: [
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
          { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sign },
      ] },
    { phase: P4, key: "restaurant_ok", title: "El restaurante confirma la reserva",
      todo: "Pulsa «Simular confirmación del restaurante» y abre la hoja.",
      say: "El restaurante contesta como quiera; la IA entiende que acepta, lo marca «Aceptado» y deja un resumen.",
      how: [
          ["Pulsa «Simular confirmación del restaurante».", "Contesta al correo de la hoja."],
          ["«Abrir la hoja de servicio».", "Respuesta «Aceptado» con su resumen; en el presupuesto, restaurantes confirmados 1/1."],
      ],
      buttons: [
          { label: "Simular confirmación del restaurante", call: "simulate_restaurant_confirmation", enabled: (s) => s.done.sheets_sent && !s.done.restaurant_ok },
          { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sign },
      ] },
    // --- 5 · pagos ---
    { phase: P5, key: "daily", title: "La revisión diaria prepara los correos de pago",
      news: ["En «Pendientes de aprobar» también está la petición de CIF y razón social a la agencia (diapo. 2)."],
      todo: "Pulsa «Ejecutar la revisión diaria» y abre «Pendientes de aprobar».",
      say: "Cada mañana el sistema revisa los grupos. Faltan 5 días: prepara la petición de pago a la agencia, la petición de cuenta bancaria al restaurante (con la proforma) y lo que falta por cerrar. Nadie tiene que acordarse.",
      how: [
          ["Pulsa «Ejecutar la revisión diaria».", "Es lo que hace el sistema solo cada mañana; aquí lo lanzamos a mano."],
          ["«Abrir Pendientes de aprobar».", "Cada correo con su motivo: «Servicio el … y sin pago», «… y sin cuenta bancaria»."],
      ],
      buttons: [
          { label: "Ejecutar la revisión diaria", call: "run_daily_checks", after: "Revisión diaria hecha", enabled: (s) => s.done.sign && !s.done.daily },
          { label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.sign },
      ] },
    { phase: P5, key: "payments_sent", title: "Se aprueban los correos de pago",
      todo: "Aprueba la petición de pago a la agencia y la de la cuenta bancaria al restaurante.",
      say: "Texto editable antes de enviar. Lleva el importe, nuestros datos bancarios y, al restaurante, la proforma adjunta.",
      how: [
          ["En cada uno: revisa el texto → «Aprobar y enviar».", "Si queda alguno de «datos por cerrar», se puede aprobar o descartar."],
      ],
      buttons: [{ label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.daily }] },
    { phase: P5, key: "agency_paid", title: "La agencia paga: justificante y bono",
      todo: "«Simular justificante de la agencia» → en el presupuesto, «Confirmar pago» → «Enviar bono de agencia».",
      say: "La IA lee el justificante en PDF y avisa con el importe, y si no cuadra con el pedido. Pero nunca marca pagado sola: una persona mira el banco y confirma. Después sale el bono, con sello PAGADO y sin precios.",
      how: [
          ["Pulsa «Simular justificante de la agencia».", "La agencia contesta al correo de pago con el PDF."],
          ["«Abrir el presupuesto»: aviso con el importe leído → «Confirmar pago».", "Queda Pagado con su fecha."],
          ["«Enviar bono de agencia» → «Enviar».", "Es el documento que presenta el grupo en el restaurante."],
      ],
      buttons: [
          { label: "Simular justificante de la agencia", call: "simulate_agency_payment_proof", enabled: (s) => s.done.payments_sent && !s.done.agency_paid },
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
      ] },
    { phase: P5, key: "restaurant_paid", title: "Pago al restaurante",
      todo: "«Simular cuenta del restaurante» → en la hoja, «Transferencia hecha» → «Enviar justificante».",
      say: "El restaurante contesta con su IBAN: se comprueba que es válido y se guarda en su ficha, sin teclearlo. Hecha la transferencia, se le manda el justificante con nuestros datos fiscales para la factura.",
      how: [
          ["Pulsa «Simular cuenta del restaurante».", "Contesta al correo de la cuenta con su IBAN."],
          ["«Abrir la hoja de servicio»: «Tenemos su cuenta» → «Transferencia hecha».", "Sale en «Pagos a restaurantes» como hecho."],
          ["«Enviar justificante»: confirmación + datos fiscales (el del banco se adjunta con el clip) → «Enviar».", "Todo lo que necesita para hacer bien la factura."],
      ],
      buttons: [
          { label: "Simular cuenta del restaurante", call: "simulate_restaurant_bank", enabled: (s) => s.done.payments_sent && !s.done.restaurant_paid },
          { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sign },
          { label: "Abrir Pagos a restaurantes", action: A.restaurantPayments, enabled: (s) => s.done.sign },
      ] },
    // --- 6 · cierre ---
    { phase: P6, key: "service_done", title: "Pasa el día del servicio: se reclama la factura",
      todo: "Pulsa «Ha pasado el servicio» y abre «Pendientes de aprobar».",
      say: "Al día siguiente del servicio, si el restaurante no ha mandado la factura, se prepara la primera reclamación. Luego a los 7, 15 y 30 días, cada vez más firme; la cuarta, la legal, la revisa siempre una persona.",
      how: [
          ["Pulsa «Ha pasado el servicio».", "Movemos la fecha del grupo a ayer y corre la revisión diaria."],
          ["«Abrir Pendientes de aprobar» → «Reclamación 1 de 4» → «Aprobar y enviar».", "Lleva la reserva, el importe y nuestros datos fiscales."],
      ],
      buttons: [
          { label: "Ha pasado el servicio", call: "simulate_service_done", after: "Fecha del grupo movida a ayer", enabled: (s) => s.done.sign && !s.done.service_done },
          { label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.service_done },
      ] },
    { phase: P6, key: "invoice_ok", title: "Llega la factura del restaurante",
      todo: "«Simular factura del restaurante» → en la hoja, «Factura correcta».",
      say: "La IA lee el PDF: número, fecha, importe y nuestro CIF, y comprueba que cuadra con la hoja. Una persona la da por buena.",
      how: [
          ["Pulsa «Simular factura del restaurante».", "Contesta a la reclamación con la factura en PDF."],
          ["«Abrir la hoja de servicio»: aviso con lo leído y «cuadra con la hoja» → «Factura correcta».", "Queda «Factura recibida y revisada»."],
      ],
      buttons: [
          { label: "Simular factura del restaurante", call: "simulate_restaurant_invoice", enabled: (s) => s.done.service_done && !s.done.invoice_ok },
          { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sign },
      ] },
    { phase: P6, key: "agency_invoice", title: "Cortafuegos: no se cierra con algo pendiente",
      todo: "En Expedientes, intenta «Cerrar expediente»: el cortafuegos lo para. Marca «Factura enviada» en el presupuesto.",
      say: "No se puede cerrar con algo pendiente y el sistema dice exactamente qué falta: aquí, la factura a la agencia.",
      how: [
          ["«Abrir la petición» → «Cerrar expediente».", "Sale «Falta enviar la factura a la agencia»."],
          ["«Abrir el presupuesto» → «Factura enviada».", "Lo único que faltaba."],
      ],
      buttons: [
          { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.sign },
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
      ] },
    { phase: P6, key: "closed", title: "Se cierra el expediente",
      todo: "En la petición, «Cerrar expediente» y mira Terminados.",
      say: "Con el pago de la agencia, el pago al restaurante y las dos facturas en orden, el grupo queda cerrado y ganado.",
      how: [
          ["«Abrir la petición» → «Cerrar expediente» → «Aceptar».", "Cinta GANADO."],
          ["«Abrir Terminados».", "Ahí queda el grupo."],
      ],
      buttons: [
          { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.agency_invoice },
          { label: "Abrir Terminados", action: A.terminados, enabled: (s) => s.done.closed },
      ] },
    // --- 7 · configuración ---
    { phase: P7, key: "control", title: "Plantillas, cortafuegos y actividad de la IA",
      todo: "Abre Plantillas de correo, Cortafuegos y Actividad IA.",
      say: "Los textos son vuestros y se cambian sin llamarnos; cada correo puede ir con aprobación o en automático. Las reglas de los cortafuegos las ponéis vosotros. Y todo lo que lee la IA queda registrado, también si alguien lo corrigió.",
      how: [
          ["«Plantillas de correo» → abre una.", "Asunto, texto, marcadores entre llaves e interruptor «Enviar automáticamente»."],
          ["«Cortafuegos».", "Antes de qué paso, qué se comprueba y si avisa o impide."],
          ["«Actividad IA».", "Qué leyó, de dónde y si alguien lo revisó o corrigió."],
      ],
      buttons: [
          { label: "Plantillas de correo", action: A.templates, mark: "control", enabled: (s) => s.done.email },
          { label: "Cortafuegos", action: A.firewall, mark: "control", enabled: (s) => s.done.email },
          { label: "Actividad IA", action: A.aiLog, mark: "control", enabled: (s) => s.done.email },
      ] },
];
