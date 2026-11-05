/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onWillStart, useState } from "@odoo/owl";
import { CHANGES, STEPS } from "./steps";

const GUIDE = "restagrup.demo3.guide";

export class Demo3Guide extends Component {
    static template = "restagrup_demo3.Guide";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ data: null, busy: false, notes: false, changes: true });
        this.steps = STEPS;
        this.changes = CHANGES;
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

    get doneCount() {
        return STEPS.filter((step) => this.state.data.done[step.key]).length;
    }

    phaseStart(index) {
        return index === 0 || STEPS[index - 1].phase !== STEPS[index].phase;
    }

    stepClass(index) {
        if (this.state.data.done[STEPS[index].key]) return "is-done";
        return index === this.currentIndex ? "is-current" : "is-pending";
    }

    buttonsFor(step) {
        return step.buttons.map((button) => {
            if (button.enabled(this.state.data)) return { ...button };
            if (button.fallback && button.fallback.enabled(this.state.data)) return { ...button.fallback };
            return { ...button, disabled: true };
        });
    }

    async onButton(button) {
        if (button.call) {
            this.state.busy = true;
            try {
                await this.orm.call(GUIDE, button.call, []);
                if (button.after) this.notification.add(button.after, { type: "success" });
            } finally {
                this.state.busy = false;
            }
            await this.refresh();
            return;
        }
        if (button.mark) {
            await this.orm.call(GUIDE, "mark_seen", [button.mark]);  // pasos de «mirar»: abrirlos ya cuenta
        }
        if (button.action) {
            return this.action.doAction(button.action);
        }
        const d = this.state.data;
        if (button.open === "portal_search" || button.open === "portal_order") {
            const url = button.open === "portal_search" ? d.search_portal_url : d.order_portal_url;
            return this.action.doAction({ type: "ir.actions.act_url", url, target: "new" });
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

    toggleChanges() {
        this.state.changes = !this.state.changes;
    }

    toggleNotes() {
        this.state.notes = !this.state.notes;
    }

    askReset() {
        this.dialog.add(ConfirmationDialog, {
            title: "Reiniciar la demo",
            body: "Se borrarán la petición de este recorrido y todo lo que cuelga de ella (búsqueda, presupuesto, hoja de servicio, correos pendientes), los menús que creó la IA y las cuentas bancarias de los tres restaurantes. Los documentos de ejemplo de las listas se quedan. ¿Continuar?",
            confirmLabel: "Reiniciar",
            confirm: async () => {
                await this.orm.call(GUIDE, "reset_demo", []);
                await this.refresh();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("restagrup_demo3.guide", Demo3Guide);
