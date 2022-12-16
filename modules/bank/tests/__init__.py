# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

try:
    from trytond.modules.bank.tests.test_bank import suite
except ImportError:
    from .test_bank import suite

__all__ = ['suite']
