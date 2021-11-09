# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.addons.mail.controllers.main import MailController


class PPTMailController(MailController):

    @http.route('/mail/assign', type='http', auth='user', methods=['GET'])
    def mail_action_assign(self, model, res_id, token=None):
        comparison, record, redirect = self._check_token_and_record_or_redirect(model, int(res_id), token)
        if comparison and record:
            if record._name == 'helpdesk.ticket' and record.user_id:
                return redirect
            try:
                record.write({'user_id': request.uid})
            except Exception:
                return self._redirect_to_messaging()
        return redirect


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
