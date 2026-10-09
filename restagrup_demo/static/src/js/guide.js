/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onWillStart, useState } from "@odoo/owl";

const GUIDE = "restagrup.demo.guide";

// Cada paso: qué se ve, qué se hace, qué se dice (notas del presentador) y qué botón lleva.
const STEPS = [
    { key: "email", title: "Llega la petición de una agencia",
      todo: "Pulsa «Simular correo de la agencia».",
      say: "Llega un correo normal de una agencia; nadie lo copia a mano.",
      button: { label: "Simular correo de la agencia", call: "simulate_agency_email", enabled: (s) => !s.done.email } },
    { key: "ai", title: "La IA lee el correo y propone los datos",
      todo: "Abre la petición: verás el correo y la nota de la IA en el historial.",
      say: "La IA ha leído el correo y propone los datos: Málaga, 32 personas, 13 de noviembre. Una persona los revisa.",
      button: { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.email } },
    { key: "search", title: "Buscar restaurantes",
      todo: "En la petición, pulsa «Buscar para todos los eventos».",
      say: "Salen solo restaurantes con aforo y parking adecuados; el de 25 plazas ya no aparece.",
      button: { label: "Abrir la petición", open: "lead", enabled: (s) => s.done.email } },
    { key: "request", title: "Pedir presupuesto al restaurante",
      todo: "En la búsqueda, pulsa «Pedir presupuesto» en el Asador Sierra Blanca.",
      say: "El clic es la aprobación humana: el correo sale al restaurante.",
      button: { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.search } },
    { key: "reply", title: "El restaurante responde",
      todo: "Pulsa «Simular respuesta del restaurante».",
      say: "La respuesta se enlaza sola. La IA propone el importe, pero queda «sin confirmar».",
      button: { label: "Simular respuesta del restaurante", call: "simulate_restaurant_reply",
                enabled: (s) => s.done.request && !s.done.reply } },
    { key: "chosen", title: "Confirmar el importe y elegir",
      todo: "En la búsqueda, «Confirmar presupuesto» y «Elegir».",
      say: "Una persona confirma. Todo queda registrado en el historial.",
      button: { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.reply } },
    { key: "order", title: "Presupuesto de venta para la agencia",
      todo: "En la búsqueda, pulsa «Crear presupuesto de venta».",
      say: "Precio por persona más nuestro margen, con IVA. El cliente no ve nuestro coste.",
      button: { label: "Abrir el presupuesto", open: "order", enabled: (s) => s.done.order,
                fallback: { label: "Abrir la búsqueda", open: "search", enabled: (s) => s.done.chosen } } },
    { key: "signed", title: "La agencia firma desde el enlace",
      todo: "Abre la vista del cliente y pulsa «Aceptar y firmar».",
      say: "La agencia firma desde un enlace, sin usuario en Odoo.",
      button: { label: "Ver como la agencia", open: "portal", enabled: (s) => s.done.order } },
    { key: "sheet", title: "Hoja de servicio para el restaurante",
      todo: "Abre la hoja de servicio generada.",
      say: "Se genera sola, con lo que cobra el restaurante.",
      button: { label: "Abrir la hoja de servicio", open: "sheet", enabled: (s) => s.done.sheet } },
];

export class DemoGuide extends Component {
    static template = "restagrup_demo.Guide";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
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

    buttonFor(step) {
        const button = step.button;
        if (button.enabled(this.state.data)) return button;
        if (button.fallback && button.fallback.enabled(this.state.data)) return button.fallback;
        return { ...button, disabled: true };
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
        const d = this.state.data;
        const forms = {
            lead: ["crm.lead", d.lead_id],
            search: ["restagrup.restaurant.search", d.search_id],
            order: ["sale.order", d.order_id],
            sheet: ["purchase.order", d.sheet_id],
        };
        if (button.open === "portal") {
            return this.action.doAction({ type: "ir.actions.act_url", url: d.portal_url, target: "new" });
        }
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
            body: "Se borrarán la petición, la búsqueda, el presupuesto y la hoja de servicio de esta demo. ¿Continuar?",
            confirmLabel: "Reiniciar",
            confirm: async () => {
                await this.orm.call(GUIDE, "reset_demo", []);
                await this.refresh();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("restagrup_demo.guide", DemoGuide);
