# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    cost_sale_shipments = fields.One2Many(
        'stock.shipment.out', 'cost_sale_invoice_line',
        "Cost Sale of Shipments",
        readonly=True)

    @classmethod
    def copy(cls, lines, default=None):
        default = default.copy() if default is not None else {}
        default.setdefault('cost_sale_shipments', None)
        return super().copy(lines, default=default)
