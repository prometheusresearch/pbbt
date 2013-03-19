#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import test_type, test_field
from .ctl import TestCtl
from .std import TestCaseMixin, RunAndCompareMixin


def test(filename, ui=None, training=False):
    ctl = TestCtl(ui=ui, training=training)
    return ctl(filename)


