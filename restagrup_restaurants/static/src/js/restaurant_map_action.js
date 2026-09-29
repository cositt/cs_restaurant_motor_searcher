import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";
import { Component, onMounted, useRef } from "@odoo/owl";

const LINE_MODEL = "restagrup.restaurant.search.line";
const LINE_FIELDS = [
    "name", "latitude", "longitude", "etiqueta", "quote_amount", "address",
    "is_chosen", "partner_id", "rating", "review_count", "price_label",
];

// Mismas etiquetas que el kanban del buscador (restaurant_search.py) -- si esa
// selección cambia, actualizar aquí también.
const ETIQUETA_LABELS = {
    visto: "Visto",
    interesado: "Interesado",
    solicitado: "Solicitado",
    presupuesto_recibido: "Presupuesto recibido",
    descartado: "Descartado",
};

// Colores saturados a propósito -- el gris/azul apagado original se perdía contra
// los tonos beige/gris claro de los tiles de OpenStreetMap.
const MARKER_COLOR_CHOSEN = "#00c853"; // verde vivo
const MARKER_COLOR_QUOTE_RECEIVED = "#2979ff"; // azul vivo
const MARKER_COLOR_DISCARDED = "#9e9e9e"; // gris apagado -- descartados no deben competir visualmente
const MARKER_COLOR_DEFAULT = "#ff3d00"; // rojo-naranja vivo -- "aún sin resolver"

export class RestaurantMapAction extends Component {
    static template = "restagrup_restaurants.RestaurantMapAction";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.mapRef = useRef("map");
        this.searchId = this.props.action.params.search_id;
        this.markersLayer = null;
        this.map = null;
        onMounted(() => this.loadAndRender(true));
    }

    async loadAndRender(fitBounds) {
        const lines = await this.orm.searchRead(
            LINE_MODEL,
            [["search_id", "=", this.searchId], ["latitude", "!=", false], ["longitude", "!=", false]],
            LINE_FIELDS,
        );

        if (!this.map) {
            this.map = L.map(this.mapRef.el);
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: "&copy; OpenStreetMap contributors",
            }).addTo(this.map);
            this.markersLayer = L.layerGroup().addTo(this.map);
        }
        this.markersLayer.clearLayers();

        if (!lines.length) {
            this.map.setView([40.4168, -3.7038], 5); // Sin resultados con coordenadas -- vista de España por defecto.
            return;
        }

        const markers = lines.map((line) => this._createMarker(line));
        markers.forEach((marker) => this.markersLayer.addLayer(marker));
        if (fitBounds) {
            this.map.fitBounds(L.featureGroup(markers).getBounds().pad(0.15));
        }

        // Leaflet calcula el tamaño del contenedor en el momento de crear el mapa --
        // si el layout todavía no había terminado de asentarse, el mapa queda
        // recortado hasta el próximo resize manual del usuario. Un invalidateSize
        // async lo corrige sin que se note.
        requestAnimationFrame(() => this.map.invalidateSize());
    }

    _markerColor(line) {
        if (line.is_chosen) return MARKER_COLOR_CHOSEN;
        if (line.etiqueta === "presupuesto_recibido") return MARKER_COLOR_QUOTE_RECEIVED;
        if (line.etiqueta === "descartado") return MARKER_COLOR_DISCARDED;
        return MARKER_COLOR_DEFAULT;
    }

    _createMarker(line) {
        const marker = L.circleMarker([line.latitude, line.longitude], {
            radius: 10, fillColor: this._markerColor(line), color: "#fff", weight: 3, fillOpacity: 1,
        });
        marker.bindPopup(this._buildPopupContent(line), { minWidth: 260 });
        return marker;
    }

    // --- Contenido del popup: la misma card del kanban, pero con acciones reales ---

    _buildPopupContent(line) {
        const root = document.createElement("div");
        root.className = "o_restagrup_map_popup";

        const title = document.createElement("h4");
        title.textContent = line.name;
        root.appendChild(title);

        if (line.address) {
            const addr = document.createElement("div");
            addr.className = "o_restagrup_map_popup_addr";
            addr.textContent = "📍 " + line.address;
            root.appendChild(addr);
        }

        if (line.rating) {
            const rating = document.createElement("div");
            rating.className = "o_restagrup_map_popup_meta";
            rating.textContent = `★ ${line.rating} (${line.review_count || 0})` + (line.price_label ? ` · ${line.price_label}` : "");
            root.appendChild(rating);
        }

        const badge = document.createElement("span");
        badge.className = `badge-etiqueta etiqueta-${line.etiqueta}`;
        badge.textContent = ETIQUETA_LABELS[line.etiqueta] || line.etiqueta;
        root.appendChild(badge);

        if (line.quote_amount) {
            const amount = document.createElement("span");
            amount.className = "o_restagrup_quote_amount";
            amount.textContent = ` 💶 ${line.quote_amount} €`;
            root.appendChild(amount);
        }

        const actions = document.createElement("div");
        actions.className = "o_restagrup_map_popup_actions";
        root.appendChild(actions);

        this._addActionButton(actions, _t("Interesado"), line, "action_mark_interesado");
        this._addActionButton(actions, _t("Descartar"), line, "action_mark_descartado");
        if (line.etiqueta !== "presupuesto_recibido") {
            const quoteLabel = line.etiqueta === "solicitado" ? _t("Reenviar petición") : _t("Pedir presupuesto");
            this._addActionButton(actions, quoteLabel, line, "action_request_quote");
            this._addActionButton(actions, _t("Registrar presupuesto"), line, "action_open_quote_form");
        }
        this._addActionButton(
            actions, line.is_chosen ? _t("Quitar elegido") : _t("Elegir"), line, "action_toggle_chosen",
        );

        if (line.partner_id) {
            const ratingRow = document.createElement("div");
            ratingRow.className = "o_restagrup_map_popup_actions";
            this._addActionButton(ratingRow, "👍", line, "action_rate_liked");
            this._addActionButton(ratingRow, "➖", line, "action_rate_neutral");
            this._addActionButton(ratingRow, "👎", line, "action_rate_disliked");
            root.appendChild(ratingRow);
        }

        return root;
    }

    _addActionButton(container, label, line, methodName) {
        const button = document.createElement("button");
        button.className = "btn btn-outline-secondary btn-sm";
        button.textContent = label;
        button.addEventListener("click", () => this._callAction(line.id, methodName));
        container.appendChild(button);
    }

    async _callAction(lineId, methodName) {
        // Mismo mecanismo que un botón type="object" normal de Odoo -- si el método
        // devuelve una acción (p.ej. el diálogo de "Registrar presupuesto"), la abre
        // y normaliza el dict del lado del servidor; si no devuelve nada, no hace
        // nada más. En ambos casos refrescamos los marcadores al terminar.
        await this.action.doActionButton({
            type: "object",
            resModel: LINE_MODEL,
            resId: lineId,
            name: methodName,
            onClose: () => this.loadAndRender(false),
        });
        await this.loadAndRender(false);
    }
}

registry.category("actions").add("restagrup_restaurant_map", RestaurantMapAction);
