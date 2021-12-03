# -*- coding: utf-8 -*-

from odoo import fields, models, api


class ResCompany(models.Model):
    _inherit = "res.company"

    purge_old_open_credit_limit = fields.Integer(default=120, string="Open Credit Active Days")


ResCompany()


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    credit_purge_account = fields.Many2one('account.account',
        string='Old credit purge: Account',
        config_parameter='purge_old_open_credits.credit_purge_account')

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
