odoo.define('purchase_extension.action_manager', function (require) {
"use strict";
/**
 * The purpose of this file is to add the actions of type
 * 'ir_actions_xlsx_download' to the ActionManager.
 */
var ActionManager = require('web.ActionManager');
var framework = require('web.framework');
var session = require('web.session');
var crash_manager = require('web.crash_manager');
ActionManager.include({
    _executexlsxReportDownloadAction: function (action) {
        framework.blockUI();
        var def = $.Deferred();
        session.get_file({
            url: '/xlsx_reports',
            data: action.data,
            success: def.resolve.bind(def),
            complete: framework.unblockUI,
            error: crash_manager.rpc_error.bind(crash_manager)
        });
        return def;
    },
    _handleAction: function (action, options) {
        if (action.report_type === 'xlsx') {
            document.querySelector('.close').click();
            return this._executexlsxReportDownloadAction(action, options);

        }
        return this._super.apply(this, arguments);

},
    });
  });
