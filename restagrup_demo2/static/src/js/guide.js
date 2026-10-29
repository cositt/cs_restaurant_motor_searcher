/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onWillStart, useState } from "@odoo/owl";

const GUIDE = "restagrup.demo2.guide";
const A = {
    pending: "restagrup_restaurants.action_restagrup_pending_mail",
    restaurants: "restagrup_restaurants.action_restaurant_list",
    menus: "restagrup_restaurants.action_restaurant_menu",
    peticiones: "restagrup_service_orders.action_peticiones",
    presupuestos: "restagrup_service_orders.action_presupuestos",
    expedientes: "restagrup_service_orders.action_expedientes",
    terminados: "restagrup_service_orders.action_terminados",
};

// Cada paso: qué se hace, qué se dice (notas del presentador), dónde clicar y por qué (how) y sus botones (call = acción de la guía,
// open = abrir un registro, action = abrir una lista).
const STEPS = [
    { key: "email", title: "Llega la petición de una agencia, incompleta",
      todo: "Pulsa «Simular correo de la agencia».",
      say: "Llega un correo normal. Esta vez la agencia no dice la fecha.",
      how: [
          ["Pulsa «Simular correo de la agencia» (aquí, en la guía).", "Es como si Costa Viajes escribiera a peticiones@: el correo entra por el buzón, no lo tecleamos."],
          ["Arriba, menú «Peticiones».", "Para enseñar que la petición ya está creada sola, con la agencia y el contacto."],
      ],
      buttons: [{ label: "Simular correo de la agencia", call: "simulate_agency_email", enabled: (s) => !s.done.email }] },
    { key: "ask", title: "La IA ve que falta la fecha y prepara el aviso",
      todo: "Abre «Pendientes de aprobar»: verás el correo para la agencia pidiendo solo lo que falta.",
      say: "No pregunta lo que ya sabe: solo la fecha. Y no sale nada sin que una persona lo apruebe.",
      how: [
          ["Pulsa «Abrir Pendientes de aprobar».", "Ahí espera todo correo que la IA quiere enviar fuera: nada sale sin una persona."],
          ["Abre la línea del correo para Costa Viajes.", "Se ve el borrador: pide solo la fecha, no lo que ya dijo la agencia."],
          ["Señala el historial de la derecha.", "Está el correo original y el porqué: sin fecha no se puede mirar aforo ni disponibilidad."],
      ],
      buttons: [{ label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.email }] },
    { key: "approve", title: "Se aprueba el envío",
      todo: "Pulsa «Aprobar y enviar» en el correo pendiente.",
      say: "El clic es la aprobación humana. El correo sale por el mismo hilo de la petición.",
      how: [
          ["En ese mismo correo, pulsa «Aprobar y enviar».", "Ese clic es la aprobación humana; el correo sale por el hilo de la petición."],
          ["Vuelve a la guía con «Guía» en el menú de arriba.", "El paso queda marcado solo."],
      ],
      buttons: [{ label: "Abrir Pendientes de aprobar", action: A.pending, enabled: (s) => s.done.ask }] },
    { key: "reply", title: "La agencia contesta y la IA completa los datos",
      todo: "Pulsa «Simular respuesta de la agencia», abre la petición y mira la pestaña Eventos.",
      say: "La respuesta vuelve al hilo y la IA rellena la fecha sin pisar nada. La agencia no da presupuesto: no se bloquea ni se le pregunta; sale el precio orientativo de la comida (16 €, marcado «Estimado»). Se puede cambiar a mano en cualquier momento.",
      how: [
          ["Pulsa «Simular respuesta de la agencia».", "La agencia contesta al hilo con la fecha y la hora."],
          ["Pulsa «Abrir Peticiones» y entra en la de Costa Viajes.", "La respuesta está en el historial de la propia petición."],
          ["Pestaña «Eventos».", "Fecha y hora rellenadas por la IA; el precio sale «Estimado» porque la agencia no dio presupuesto."],
      ],
      buttons: [
          { label: "Simular respuesta de la agencia", call: "simulate_agency_reply", enabled: (s) => s.done.approve && !s.done.reply },
          { label: "Abrir Peticiones", action: A.peticiones, enabled: (s) => s.done.email },
      ] },
    { key: "menus", title: "Fichas de restaurante y menús",
      todo: "Abre Restaurantes y Menús. En Menús, filtra por población y temporada.",
      say: "Cada restaurante guarda sus menús: tipo, precio de coste y de venta (con el margen de cada restaurante) y temporada.",
      how: [
          ["Pulsa «Abrir Restaurantes» y entra en uno (p. ej. Bodega San Telmo).", "Cada restaurante tiene su ficha: aforo, contacto, margen y sus menús."],
          ["Vuelve y pulsa «Abrir Menús»; filtra por Sevilla y temporada 2026.", "Menús con tipo, coste y venta: de aquí sale lo que luego ve la agencia."],
      ],
      buttons: [
          { label: "Abrir Restaurantes", action: A.restaurants, mark: "mark_menus_seen", enabled: (s) => s.done.reply },
          { label: "Abrir Menús", action: A.menus, mark: "mark_menus_seen", enabled: (s) => s.done.reply },
      ] },
    { key: "search", title: "Buscar restaurantes",
      todo: "En la petición, pulsa «Buscar para todos los eventos».",
      say: "Salen solo los de Sevilla con aforo para 45 personas.",
      how: [
          ["Pulsa «Abrir la petición».", "La búsqueda se lanza desde la petición, con sus datos."],
          ["Arriba, botón «🍽 Buscar para todos los eventos».", "Filtra solos los restaurantes de Sevilla con aforo para 45; no se teclea nada."],
      ],
      buttons: [{ label: "Abrir la petición", open: "lead", enabled: (s) => s.done.reply }] },
    { key: "request", title: "Pedir presupuesto a tres restaurantes",
      todo: "Pulsa «Pedir presupuesto a los 3».",
      say: "Salen tres correos, uno por restaurante. El clic es la aprobación.",
      how: [
          ["Pulsa «Pedir presupuesto a los 3» (aquí, en la guía).", "Salen tres correos, uno por restaurante: el clic es la aprobación."],
          ["Pulsa «Abrir la búsqueda».", "Cada línea queda «pendiente de respuesta» con la fecha de envío."],
      ],
      buttons: [
          { label: "Pedir presupuesto a los 3", call: "request_quotes", enabled: (s) => s.done.search && !s.done.request },
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search },
      ] },
    { key: "answers", title: "Los restaurantes responden con su menú",
      todo: "Pulsa «Simular respuestas de los restaurantes».",
      say: "Cada respuesta se enlaza a su petición. La IA propone el importe, pero queda «sin confirmar».",
      how: [
          ["Pulsa «Simular respuestas de los restaurantes».", "Cada restaurante contesta con su menú y su precio por persona."],
          ["Abre la búsqueda y en una línea pulsa «Ver conversación».", "Se ve el correo del restaurante y el importe que propuso la IA, «sin confirmar»."],
      ],
      buttons: [{ label: "Simular respuestas de los restaurantes", call: "simulate_restaurant_replies",
                  enabled: (s) => s.done.request && !s.done.answers }] },
    { key: "confirm", title: "Una persona confirma los importes",
      todo: "Pulsa «Confirmar los 3 presupuestos».",
      say: "La IA propone, una persona confirma. Todo queda en el historial.",
      how: [
          ["Pulsa «Confirmar los 3 presupuestos».", "Hace lo que haría una persona con «Confirmar» en cada línea."],
          ["Pulsa «Abrir la búsqueda».", "Las tres líneas pasan a «presupuesto recibido» y queda en el historial quién lo confirmó."],
      ],
      buttons: [
          { label: "Confirmar los 3 presupuestos", call: "confirm_quotes", enabled: (s) => s.done.answers && !s.done.confirm },
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search },
      ] },
    { key: "proposal", title: "Una propuesta con varias opciones para la agencia",
      todo: "En la búsqueda, mira la comparativa con y sin «Mostrar restaurantes» y pulsa «Enviar comparativa al cliente».",
      say: "Menú y precio por persona de cada restaurante, sin totales. Con un cliente nuevo se pueden ocultar los nombres. Antes de enviar, el sistema enseña qué sale y a quién (restaurantes, precios, condiciones) y una persona lo revisa; cuando haya confianza, ese punto de revisión se desactiva en Cortafuegos.",
      how: [
          ["Pulsa «Abrir la búsqueda» y luego «Comparativa para el cliente».", "Vista previa del PDF: menú y precio por persona de cada opción, sin totales."],
          ["Apaga el interruptor «Mostrar restaurantes» (junto a «Enviar comparativa al cliente») y abre otra vez la comparativa.", "Con un cliente nuevo se enseñan las opciones sin decir dónde están; se decide justo antes de enviar."],
          ["En la búsqueda, «Enviar comparativa al cliente».", "Asunto y texto ya rellenos y «Incluir enlace de portal» marcado."],
          ["Pulsa «Enviar»; si aparece la revisión, léela y pulsa «Revisado: enviar».", "El cortafuegos enseña qué sale y a quién antes de enviarlo."],
      ],
      buttons: [
          { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.confirm },
          { label: "Abrir Presupuestos", action: A.presupuestos, enabled: (s) => s.done.proposal },
      ] },
    { key: "choose", title: "El cliente elige su restaurante",
      todo: "Abre la vista del cliente y pulsa «Elijo este».",
      say: "La agencia elige desde un enlace, sin usuario en Odoo.",
      how: [
          ["Pulsa «Ver como la agencia».", "Se abre otra pestaña: lo que ve la agencia, sin usuario en Odoo."],
          ["En una opción, «Elijo este». Luego vuelve a la pestaña de Odoo.", "La elección llega sola a la búsqueda."],
      ],
      buttons: [{ label: "Ver como la agencia", open: "portal_search", enabled: (s) => s.done.proposal && s.search_portal_url }] },
    { key: "order", title: "Presupuesto de venta",
      todo: "En la búsqueda, pulsa «Crear presupuesto de venta».",
      say: "Precio por persona con IVA incluido. El cliente no ve nuestro coste ni el margen.",
      how: [
          ["Pulsa «Abrir la búsqueda» y luego «Crear presupuesto de venta».", "Se crea solo con el restaurante y el menú que eligió la agencia: precio del restaurante más nuestro margen."],
          ["Pulsa «Abrir el presupuesto».", "Precio por persona con IVA; el cliente no ve coste ni margen."],
      ],
      buttons: [{ label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.order,
                  fallback: { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.choose } }] },
    { key: "sign", title: "La agencia firma y el grupo pasa a Expediente",
      todo: "Abre la vista del cliente y pulsa «Aceptar y firmar». Luego mira Expedientes.",
      say: "Al firmar, el grupo pasa solo de Presupuesto a Expediente y se genera la hoja de servicio.",
      how: [
          ["Pulsa «Ver como la agencia».", "La agencia ve el presupuesto en su enlace."],
          ["«Aceptar y firmar»: la firma sale con el nombre de la agencia; pulsa otra vez «Aceptar y firmar». Vuelve a Odoo.", "La firma es el sí del cliente."],
          ["Pulsa «Abrir Expedientes».", "El grupo ha pasado solo de Presupuesto a Expediente, con su hoja de servicio."],
      ],
      buttons: [
          { label: "Ver como la agencia", open: "portal_order", enabled: (s) => s.done.order },
          { label: "Abrir Expedientes", action: A.expedientes, enabled: (s) => s.done.sign },
      ] },
    { key: "docs", title: "Gratuidades y confirmaciones",
      todo: "Aplica las gratuidades y genera la confirmación al restaurante (en la hoja de servicio) y a la agencia (en el presupuesto).",
      say: "Guía y chófer no pagan, pero cuentan como comensales. El restaurante recibe su precio; la agencia, el suyo. Cada evento muestra en «Datos por cerrar» lo que falta (menú, intolerancias, contacto del guía, comensales definitivos) y, cuando se acerca la fecha, el sistema avisa al responsable.",
      how: [
          ["Pulsa «Aplicar 2 gratuidades».", "Guía y chófer no pagan pero cuentan como comensales."],
          ["«Abrir la hoja de servicio» → «Confirmación restaurante».", "Documento para el restaurante, con su precio."],
          ["«Abrir el presupuesto» → «Confirmación agencia».", "Documento para la agencia, con el suyo."],
      ],
      buttons: [
          { label: "Aplicar 2 gratuidades", call: "apply_gratuities", enabled: (s) => s.done.sign && !s.done.docs },
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
          { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sign },
      ] },
    { key: "paid", title: "Pago recibido y bono de agencia",
      todo: "En el presupuesto, «Marcar como pagado» y «Enviar bono de agencia».",
      say: "El bono lleva el sello PAGADO y ningún precio. Es el documento que viaja con el grupo.",
      how: [
          ["Pulsa «Abrir el presupuesto» → «Marcar como pagado».", "Se registra el pago de la agencia."],
          ["«Enviar bono de agencia»: revisa el correo y pulsa «Enviar».", "Le llega a la agencia con el PDF (sello PAGADO, sin precios) y queda en el historial: no hay que descargar nada."],
          ["Pulsa «Abrir Terminados».", "Cierre del recorrido: el grupo ya está listo."],
      ],
      buttons: [
          { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.sign },
          { label: "Abrir Terminados", action: A.terminados, enabled: (s) => s.done.sign },
      ] },
];

export class Demo2Guide extends Component {
    static template = "restagrup_demo2.Guide";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.state = useState({ data: null, busy: false, notes: false });
        this.steps = STEPS;
        onWillStart(() => this.refresh());
    }

    async refresh() {
        this.state.data = await this.orm.call(GUIDE, "get_state", []);
    }

    get currentIndex() {
        const done = this.state.data.done;
        const index = STEPS.findIndex((step) => !done[step.key]);
        return index === -1 ? STEPS.length : index;
    }

    stepClass(index) {
        if (this.state.data.done[STEPS[index].key]) return "is-done";
        return index === this.currentIndex ? "is-current" : "is-pending";
    }

    buttonsFor(step) {
        return step.buttons.map((button) => {
            const label = typeof button.label === "function" ? button.label(this.state.data) : button.label;
            if (button.enabled(this.state.data)) return { ...button, label };
            if (button.fallback && button.fallback.enabled(this.state.data)) return { ...button.fallback };
            return { ...button, label, disabled: true };
        });
    }

    async onButton(button) {
        if (button.call) {
            this.state.busy = true;
            try {
                await this.orm.call(GUIDE, button.call, []);
            } finally {
                this.state.busy = false;
            }
            await this.refresh();
            return;
        }
        if (button.mark) {
            await this.orm.call(GUIDE, button.mark, []);  // pasos de «mirar»: abrirlos ya cuenta como hecho
        }
        if (button.action) {
            return this.action.doAction(button.action);
        }
        const d = this.state.data;
        if (button.open === "portal_search") {
            return this.action.doAction({ type: "ir.actions.act_url", url: d.search_portal_url, target: "new" });
        }
        if (button.open === "portal_order") {
            return this.action.doAction({ type: "ir.actions.act_url", url: d.order_portal_url, target: "new" });
        }
        const forms = {
            lead: ["crm.lead", d.lead_id],
            search: ["restagrup.restaurant.search", d.search_id],
            order: ["sale.order", d.order_id],
            sheet: ["purchase.order", d.sheet_id],
        };
        const [model, id] = forms[button.open];
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]],
        });
    }

    toggleNotes() {
        this.state.notes = !this.state.notes;
    }

    askReset() {
        this.dialog.add(ConfirmationDialog, {
            title: "Reiniciar la demo",
            body: "Se borrarán la petición de este recorrido, sus búsquedas, el presupuesto y la hoja de servicio. Los documentos de ejemplo de las listas se quedan. ¿Continuar?",
            confirmLabel: "Reiniciar",
            confirm: async () => {
                await this.orm.call(GUIDE, "reset_demo", []);
                await this.refresh();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("restagrup_demo2.guide", Demo2Guide);
