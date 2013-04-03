#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import registry
from .ui import ConsoleUI, SilentUI
#from .fs import StandardFS
from .load import load, dump, locate
import sys
import os.path


class Tree(object):

    def __init__(self, paths):
        self.parents = []
        self.targets = []
        if not paths:
            self.targets = None
        else:
            for path in paths:
                if isinstance(path, str):
                    target = tuple(path.strip('/').split('/'))
                    if not target:
                        self.targets = None
                        break
                    else:
                        self.targets.append(target)
        self.saved_targets = []

    def __contains__(self, suite):
        if self.targets is None:
            return True
        for target in self.targets:
            if target[0] == '*' or target[0] == suite:
                return True
        return False

    def identify(self):
        if not self.parents:
            return "/"
        return "".join("/"+suite for suite in self.parents)

    def descend(self, suite):
        self.saved_targets.append(self.targets)
        self.parents.append(suite)
        if self.targets is None:
            return
        self.targets = [target[1:] for target in self.targets
                                   if target[0] == '*' or target[0] == suite]
        if () in self.targets:
            self.targets = None

    def ascend(self):
        self.targets = self.saved_targets.pop()
        self.parents.pop()


class State(dict):

    __slots__ = ('_saves')

    def __init__(self, *args, **kwds):
        super(State, self).__init__(*args, **kwds)
        self._saves = []

    def save(self):
        self._saves.append(self.copy())

    def restore(self):
        self.clear()
        self.update(self._saves.pop())


class TestCtl(object):

    def __init__(self, ui=None, fs=None,
                 substitutes=None, paths=None,
                 training=False, purging=False, max_errors=1,
                 quiet=False):
        if ui is None:
            ui = ConsoleUI()
        if quiet:
            ui = SilentUI(ui)
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
        self.quiet = quiet
        self.halted = False
        self.state = State(substitutes or {})
        self.tree = Tree(paths)

    def passed(self, text=None):
        if text:
            self.ui.notice(text)
        self.success_num += 1

    def failed(self, text=None):
        if text:
            self.ui.warning(text)
        self.failure_num += 1
        if self.max_errors and self.failure_num >= self.max_errors:
            self.halted = True

    def updated(self, text=None):
        if text:
            self.ui.notice(text)
        self.update_num += 1

    def halt(self, text=None):
        if text:
            self.ui.error(text)
        self.halted = True

    def load_input(self, path):
        return load(path, registry.input_types, self.state)

    def load_output(self, path):
        return load(path, registry.output_types)

    def dump_output(self, path, data):
        return dump(path, data)

    def __call__(self, input_path, output_path):
        input = self.load_input(input_path)
        output = None
        if output_path is not None and os.path.exists(output_path):
            output = self.load_output(output_path)
            if not input.__complements__(output):
                output = None
        case = input.__owner__(self, input, output)
        new_output = self.run(case)
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
            if self.failure_num:
                self.ui.error(line)
            else:
                self.ui.notice(line)
        if (output_path is not None and
                new_output is not None and new_output != output):
            self.ui.notice("saving test output to %r" % output_path)
            self.dump_output(output_path, new_output)
        return int(bool(self.failure_num))

    def run(self, case):
        return case()


