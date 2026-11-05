# -*- coding: utf-8 -*-
"""Botón «Guardar» visible y colores de botones como en el CRM de Restagrup (PPT de Conchita 2026-11-04,
diapositiva 1): verde = avanzar, azul = guardar, rojo = rechazar."""
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import file_open

CSS = 'restagrup_core/static/src/css/restagrup_buttons.css'


@tagged('post_install', '-at_install')
class TestButtonColors(TransactionCase):

    def test_stylesheet_is_loaded_in_the_backend(self):
        paths = [path for path, *_rest in self.env['ir.asset']._get_asset_paths('web.assets_backend', {})]
        self.assertTrue(any(path.endswith(CSS) for path in paths))

    def test_save_is_labelled_and_coloured(self):
        with file_open(CSS) as css:
            text = css.read()
        self.assertIn('.o_form_button_save', text)
        self.assertIn('Guardar', text)
        for colour in ('--restagrup-advance', '--restagrup-save', '--restagrup-reject'):
            self.assertIn(colour, text)
