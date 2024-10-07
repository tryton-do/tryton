# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from sql import Null
from sql.operators import Concat

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If
from trytond.transaction import Transaction


class Payment(metaclass=PoolMeta):
    __name__ = 'account.payment'

    statement_lines = fields.One2Many(
        'account.statement.line', 'related_to', "Statement Lines",
        readonly=True)

    @property
    def clearing_lines(self):
        clearing_account = self.journal.clearing_account
        yield from super().clearing_lines
        for statement_line in self.statement_lines:
            if statement_line.move:
                for line in statement_line.move.lines:
                    if line.account == clearing_account:
                        yield line


class PaymentGroup(metaclass=PoolMeta):
    __name__ = 'account.payment.group'

    statement_lines = fields.One2Many(
        'account.statement.line', 'related_to', "Statement Lines",
        readonly=True)

    @property
    def clearing_lines(self):
        clearing_account = self.journal.clearing_account
        yield from super().clearing_lines
        for statement_line in self.statement_lines:
            if statement_line.move:
                for line in statement_line.move.lines:
                    if line.account == clearing_account:
                        yield line


class Statement(metaclass=PoolMeta):
    __name__ = 'account.statement'

    @classmethod
    def _process_payments(cls, moves):
        pool = Pool()
        Payment = pool.get('account.payment')

        payments = super()._process_payments(moves)

        if payments:
            Payment.__queue__.reconcile_clearing(payments)
        return payments

    def _group_key(self, line):
        key = super(Statement, self)._group_key(line)
        if hasattr(line, 'payment'):
            key += (('payment', line.payment),)
        return key


class StatementLine(metaclass=PoolMeta):
    __name__ = 'account.statement.line'

    @classmethod
    def __setup__(cls):
        super(StatementLine, cls).__setup__()
        cls.related_to.domain['account.payment'] = [
            cls.related_to.domain.get('account.payment', []),
            If(Eval('statement_state') == 'draft',
                ('clearing_reconciled', '!=', True),
                ()),
            ]
        cls.related_to.domain['account.payment.group'] = [
            ('company', '=', Eval('company', -1)),
            If(Eval('second_currency'),
                ('currency', '=', Eval('second_currency', -1)),
                ('currency', '=', Eval('currency', -1))),
            If(Eval('statement_state') == 'draft',
                ('clearing_reconciled', '!=', True),
                ()),
            ]

    @classmethod
    def __register__(cls, module):
        table = cls.__table__()

        super().__register__(module)

        table_h = cls.__table_handler__(module)
        cursor = Transaction().connection.cursor()

        # Migration from 6.2: replace payment by related_to
        if table_h.column_exist('payment'):
            cursor.execute(*table.update(
                    [table.related_to],
                    [Concat('account.payment,', table.payment)],
                    where=table.payment != Null))
            table_h.drop_column('payment')

        # Migration from 6.2: replace payment_group by related_to
        if table_h.column_exist('payment_group'):
            cursor.execute(*table.update(
                    [table.related_to],
                    [Concat('account.payment.group,', table.payment_group)],
                    where=table.payment_group != Null))
            table_h.drop_column('payment_group')

    @classmethod
    def _get_relations(cls):
        return super()._get_relations() + ['account.payment.group']

    @property
    @fields.depends('related_to')
    def payment_group(self):
        pool = Pool()
        PaymentGroup = pool.get('account.payment.group')
        related_to = getattr(self, 'related_to', None)
        if isinstance(related_to, PaymentGroup) and related_to.id >= 0:
            return related_to

    @payment_group.setter
    def payment_group(self, value):
        self.related_to = value

    @fields.depends(methods=['payment', 'payment_group'])
    def on_change_related_to(self):
        super().on_change_related_to()
        if self.payment:
            clearing_account = self.payment.journal.clearing_account
            if clearing_account:
                self.account = clearing_account
        if self.payment_group:
            self.party = None
            clearing_account = self.payment_group.journal.clearing_account
            if clearing_account:
                self.account = clearing_account

    def payments(self):
        yield from super().payments()
        if self.payment_group:
            yield self.payment_group.kind, self.payment_group.payments

    @fields.depends('party', methods=['payment'])
    def on_change_party(self):
        super(StatementLine, self).on_change_party()
        if self.payment:
            if self.payment.party != self.party:
                self.payment = None
        if self.party:
            self.payment_group = None

    @fields.depends('account', methods=['payment', 'payment_group'])
    def on_change_account(self):
        super(StatementLine, self).on_change_account()
        if self.payment:
            clearing_account = self.payment.journal.clearing_account
        elif self.payment_group:
            clearing_account = self.payment_group.journal.clearing_account
        else:
            return
        if self.account != clearing_account:
            self.payment = None

    @classmethod
    def post_move(cls, lines):
        pool = Pool()
        Move = pool.get('account.move')
        super(StatementLine, cls).post_move(lines)
        Move.post([l.payment.clearing_move for l in lines
                if l.payment
                and l.payment.clearing_move
                and l.payment.clearing_move.state == 'draft'])


class StatementRuleLine(metaclass=PoolMeta):
    __name__ = 'account.statement.rule.line'

    def _get_related_to(self, origin, keywords, party=None, amount=0):
        return super()._get_related_to(
            origin, keywords, party=party, amount=amount) | {
            self._get_payment(origin, keywords, party=party, amount=amount),
            self._get_payment_group(origin, keywords),
            }

    def _get_party_from(self, related_to):
        pool = Pool()
        Payment = pool.get('account.payment')
        party = super()._get_party_from(related_to)
        if isinstance(related_to, Payment):
            party = related_to.party
        return party

    def _get_account_from(self, related_to):
        pool = Pool()
        Payment = pool.get('account.payment')
        PaymentGroup = pool.get('account.payment.group')
        account = super()._get_account_from(related_to)
        if isinstance(related_to, (Payment, PaymentGroup)):
            account = related_to.journal.clearing_account
        return account

    def _get_payment(self, origin, keywords, party=None, amount=0):
        pool = Pool()
        Payment = pool.get('account.payment')
        if keywords.get('payment'):
            domain = [
                ('rec_name', '=', keywords['payment']),
                ('company', '=', origin.company.id),
                ('currency', '=', origin.currency.id),
                ('state', 'in', ['processing', 'succeeded', 'failed']),
                ('clearing_reconciled', '!=', True),
                ]
            if party:
                domain.append(('party', '=', party.id))
            if amount > 0:
                domain.append(('kind', '=', 'receivable'))
            elif amount < 0:
                domain.append(('kind', '=', 'payable'))
            payments = Payment.search(domain)
            if len(payments) == 1:
                payment, = payments
                return payment

    def _get_payment_group(self, origin, keywords):
        pool = Pool()
        PaymentGroup = pool.get('account.payment.group')
        if keywords.get('payment_group'):
            groups = PaymentGroup.search([
                    ('rec_name', '=', keywords['payment_group']),
                    ('company', '=', origin.company.id),
                    ('currency', '=', origin.currency.id),
                    ('clearing_reconciled', '!=', True),
                    ])
            if len(groups) == 1:
                group, = groups
                return group
