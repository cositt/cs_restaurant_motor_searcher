/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_MS = 120000; // red de seguridad por si se pierde algún aviso del bus

/**
 * Columna discreta de iconos con contador: uno por tipo de aviso con algo pendiente para el usuario conectado.
 * Se refresca en tiempo real (bus) y al volver a la pestaña; al pulsar un icono se abre la lista de lo pendiente.
 */
export class RestagrupAlerts extends Component {
    static template = "restagrup_alerts.Alerts";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.bus = useService("bus_service");
        this.state = useState({ alerts: [], bumped: {} });
        this.onRefresh = () => this.load();
        this.onVisible = () => document.visibilityState === "visible" && this.load();
        this.bus.subscribe("restagrup_alerts_refresh", this.onRefresh);
        document.addEventListener("visibilitychange", this.onVisible);
        this.timer = setInterval(this.onRefresh, REFRESH_MS);
        onWillStart(() => this.load());
        onWillUnmount(() => {
            this.bus.unsubscribe("restagrup_alerts_refresh", this.onRefresh);
            document.removeEventListener("visibilitychange", this.onVisible);
            clearInterval(this.timer);
        });
    }

    async load() {
        let alerts;
        try {
            alerts = await this.orm.silent.call("restagrup.alert.center", "get_alerts", []);
        } catch (error) {
            // Un fallo puntual (red, servidor reiniciando) no debe molestar con diálogos: se reintenta al siguiente aviso.
            console.warn("Restagrup: no se pudieron cargar los avisos", error);
            return;
        }
        const previous = Object.fromEntries(this.state.alerts.map((a) => [a.kind, a.count]));
        // Un icono «late» una vez cuando su contador sube: se nota sin tapar nada.
        this.state.bumped = Object.fromEntries(
            alerts.filter((a) => a.count > (previous[a.kind] || 0)).map((a) => [a.kind, Date.now()])
        );
        this.state.alerts = alerts;
    }

    open(alert) {
        this.action.doAction(alert.action);
    }
}

registry.category("main_components").add("restagrup_alerts.Alerts", { Component: RestagrupAlerts });
