#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import registry
from .ui import ConsoleUI as StandardUI
#from .fs import StandardFS
from .load import load, dump, locate
import sys


class TestCtl(object):

    def __init__(self, ui=None, fs=None, substitutes=None,
                 training=False, purging=False, max_errors=1):
        if ui is None:
            ui = StandardUI()
        #if fs is None:
        #    fs = StandardFS()
        self.ui = ui
        #self.fs = fs
        self.training = training
        self.purging = purging
        self.success_num = 0
        self.failure_num = 0
        self.update_num = 0
        self.max_errors = max_errors
        self.halted = False
        self.state = {}
        if substitutes:
            self.state.update(substitutes)
        self.saved_states = []

    def save_state(self):
        self.saved_states.append(self.state.copy())

    def restore_state(self):
        self.state.clear()
        self.state.update(self.saved_states.pop())

    def passed(self, *lines):
        if lines:
            self.ui.notice(*lines)
        self.success_num += 1

    def failed(self, *lines):
        if lines:
            self.ui.notice(*lines)
        self.failure_num += 1
        if self.max_errors and self.failure_num >= self.max_errors:
            self.halted = True

    def updated(self, *lines):
        if lines:
            self.ui.notice(*lines)
        self.update_num += 1

    def halt(self, *lines):
        if lines:
            self.ui.notice(*lines)
        self.halted = True

    def load_input(self, path):
        return load(path, registry.input_types, self.state)

    def load_output(self, path):
        return load(path, registry.output_types)

    def dump_output(self, path, data):
        return dump(path, data)

    def __call__(self, path):
        input = self.load_input(path)
        output = None
        case = input.__owner__(self, input, output)
        self.run(case)
        line = []
        if self.success_num:
            line.append("%s passed" % self.success_num)
        if self.update_num:
            line.append("%s updated" % self.update_num)
        if self.failure_num:
            line.append("%s FAILED!" % self.failure_num)
        line = ", ".join(line)
        self.ui.part()
        if line:
            line = "TESTS: %s" % line
            self.ui.notice(line)
        return (not self.failure_num)

    def run(self, case):
        return case()


