# -*- coding: utf-8 -*-
"""Los presupuestos de restaurante pasan a guardarse por persona (quote_price_pp); el total del grupo
(quote_amount) se calcula. Los ya registrados guardaban solo el total: se reparte entre los comensales
de su búsqueda sin tocar el total (SQL directo, para que no se recalcule nada)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE restagrup_restaurant_search_line AS line
           SET quote_price_pp = line.quote_amount / GREATEST(COALESCE(search.min_capacity, 0), 1)
          FROM restagrup_restaurant_search AS search
         WHERE search.id = line.search_id
           AND COALESCE(line.quote_amount, 0) <> 0
           AND COALESCE(line.quote_price_pp, 0) = 0
    """)
