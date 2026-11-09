# -*- coding: utf-8 -*-
"""Fechas y condiciones de pago a restaurantes. Sin modelos: se puede importar desde cualquier fichero sin alterar
el orden en que se cargan las clases del módulo."""
from datetime import timedelta

FRIDAY = 4
PAYMENT_TERMS = [
    ('standard', '48 h antes del servicio'),
    ('immediate', 'Pago inmediato'),
    ('deposit', 'Señal + resto 48 h antes'),
]
DEFAULT_DEPOSIT_PERCENT = 50.0


def restaurant_payment_due_date(service_date, hours):
    """Día en que toca pagar al restaurante: `hours` antes del servicio; si cae en fin de semana, el viernes antes
    (así los grupos del lunes y del martes se pagan el viernes)."""
    if not service_date:
        return False
    due = service_date - timedelta(hours=hours)
    if due.weekday() > FRIDAY:
        due -= timedelta(days=due.weekday() - FRIDAY)
    return due

