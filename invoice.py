# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from functools import wraps
from sql import Table

from trytond.model import ModelView, Workflow, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond import backend

__all__ = ['Invoice', 'InvoiceLine']


def process_purchase(func):
    @wraps(func)
    def wrapper(cls, invoices):
        pool = Pool()
        Purchase = pool.get('purchase.purchase')
        with Transaction().set_context(_check_access=False):
            purchases = [p for i in cls.browse(invoices) for p in i.purchases]
        func(cls, invoices)
        with Transaction().set_context(_check_access=False):
            Purchase.process(purchases)
    return wrapper


class Invoice:
    __metaclass__ = PoolMeta
    __name__ = 'account.invoice'
    purchase_exception_state = fields.Function(fields.Selection([
        ('', ''),
        ('ignored', 'Ignored'),
        ('recreated', 'Recreated'),
        ], 'Exception State'), 'get_purchase_exception_state')
    purchases = fields.Function(fields.One2Many('purchase.purchase', None,
            'Purchases'), 'get_purchases', searcher='search_purchases')

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._error_messages.update({
                'reset_invoice_purchase': ('You cannot reset to draft '
                    'an invoice generated by a purchase.'),
                })

    def get_purchase_exception_state(self, name):
        purchases = self.purchases

        recreated = tuple(i for p in purchases for i in p.invoices_recreated)
        ignored = tuple(i for p in purchases for i in p.invoices_ignored)

        if self in recreated:
            return 'recreated'
        elif self in ignored:
            return 'ignored'
        return ''

    def get_purchases(self, name):
        pool = Pool()
        PurchaseLine = pool.get('purchase.line')
        purchases = set()
        for line in self.lines:
            if isinstance(line.origin, PurchaseLine):
                purchases.add(line.origin.purchase.id)
        return list(purchases)

    @classmethod
    def search_purchases(cls, name, clause):
        return [('lines.origin.purchase' + clause[0].lstrip(name),)
            + tuple(clause[1:3]) + ('purchase.line',) + tuple(clause[3:])]

    @classmethod
    @process_purchase
    def delete(cls, invoices):
        super(Invoice, cls).delete(invoices)

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('purchases', None)
        return super(Invoice, cls).copy(invoices, default=default)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, invoices):
        Purchase = Pool().get('purchase.purchase')
        purchases = Purchase.search([
                ('invoices', 'in', [i.id for i in invoices]),
                ])
        if purchases and any(i.state == 'cancel' for i in invoices):
            cls.raise_user_error('reset_invoice_purchase')

        return super(Invoice, cls).draft(invoices)

    @classmethod
    @process_purchase
    def post(cls, invoices):
        super(Invoice, cls).post(invoices)

    @classmethod
    @process_purchase
    def paid(cls, invoices):
        super(Invoice, cls).paid(invoices)

    @classmethod
    @process_purchase
    def cancel(cls, invoices):
        super(Invoice, cls).cancel(invoices)


class InvoiceLine:
    __metaclass__ = PoolMeta
    __name__ = 'account.invoice.line'

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().connection.cursor()
        sql_table = cls.__table__()

        super(InvoiceLine, cls).__register__(module_name)

        # Migration from 2.6: remove purchase_lines
        rel_table_name = 'purchase_line_invoice_lines_rel'
        if TableHandler.table_exist(rel_table_name):
            rel_table = Table(rel_table_name)
            cursor.execute(*rel_table.select(
                    rel_table.purchase_line, rel_table.invoice_line))
            for purchase_line, invoice_line in cursor.fetchall():
                cursor.execute(*sql_table.update(
                        columns=[sql_table.origin],
                        values=['purchase.line,%s' % purchase_line],
                        where=sql_table.id == invoice_line))
            TableHandler.drop_table(
                'purchase.line-account.invoice.line', rel_table_name)

    @property
    def origin_name(self):
        pool = Pool()
        PurchaseLine = pool.get('purchase.line')
        name = super(InvoiceLine, self).origin_name
        if isinstance(self.origin, PurchaseLine):
            name = self.origin.purchase.rec_name
        return name

    @classmethod
    def _get_origin(cls):
        models = super(InvoiceLine, cls)._get_origin()
        models.append('purchase.line')
        return models
