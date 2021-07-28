# -*- coding: utf-8 -*-

from odoo import models, fields


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    show_in_route = fields.Boolean(string='Show in assign route', default=False)
    exclude_late_order = fields.Boolean(string='Prevent being Late Order', default=False)


DeliveryCarrier()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
