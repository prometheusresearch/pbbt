#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .load import load, dump, locate
from .core import registry
from .ui import ConsoleUI
import sys


class TestCtl(object):

    def __init__(self, ui=None, training=False, purging=False, max_errors=1):
        if ui is None:
            ui = ConsoleUI()
        self.ui = ui
        self.training = training
        self.purging = purging
        self.success_num = 0
        self.failure_num = 0
        self.update_num = 0
        self.max_errors = max_errors
        self.halted = False
        self.state = {}
        self.saved_states = []

    def save_state(self):
        self.saved_states.append(self.state.copy())

    def restore_state(self):
        self.state = self.saved_states.pop()

    def passes(self, *lines):
        self.ui.notice(*lines)
        self.success_num += 1

    def fails(self, *lines):
        self.ui.notice(*lines)
        self.failure_num += 1
        if self.max_errors and self.failure_num >= self.max_errors:
            self.halted = True

    def updates(self, *lines):
        self.ui.notice(*lines)
        self.update_num += 1

    def halts(self, *lines):
        self.ui.notice(*lines)
        self.halted = True

    def load_input(self, path):
        return load(path, registry.input_types)

    def load_output(self, path):
        return load(path, registry.output_types)

    def dump_output(self, path, data):
        return dump(path, data)

    def __call__(self, path):
        input = self.load_input(path)
        output = None
        case = input.__owner__(self, input, output)
        self.run(case)

    def run(self, case):
        return case()


