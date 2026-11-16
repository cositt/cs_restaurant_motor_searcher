/** @odoo-module **/
import { onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

const BUS_TYPE = "restagrup_conversation_refresh";

/**
 * Reunión 13/11 (P13): si el grupo abierto recibe o envía un mensaje de su conversación, la ficha se recarga sola
 * para que la pestaña Conversación lo muestre sin F5. Con cambios sin guardar no se pisa nada: solo se avisa.
 */
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.resModel !== "crm.lead") {
            return;
        }
        this.restagrupBus = useService("bus_service");
        this.restagrupNotification = useService("notification");
        this.onRestagrupConversation = (payload) => this.restagrupReloadConversation(payload);
        this.restagrupBus.subscribe(BUS_TYPE, this.onRestagrupConversation);
        onWillUnmount(() => this.restagrupBus.unsubscribe(BUS_TYPE, this.onRestagrupConversation));
    },

    async restagrupReloadConversation(payload) {
        const root = this.model.root;
        if (!root || !payload || root.resId !== payload.lead_id) {
            return;
        }
        if (await root.isDirty()) {
            this.restagrupNotification.add(_t("Hay mensajes nuevos en la conversación: guarda para verlos."), {
                type: "info",
            });
            return;
        }
        await root.load();
    },
});
