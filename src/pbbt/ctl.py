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
import fnmatch


class Selection(object):
    # Set of path patterns that identify selected suites.

    def __init__(self, targets):
        # Path to the current suite.
        self.path = []
        # Suite patterns relative to the current path.
        self.targets = set()
        if not targets:
            # Everything is selected.
            self.targets = None
        else:
            # Convert given targets from filesystem notation to tuples.
            for target in targets:
                if isinstance(target, str):
                    target = tuple(target.strip('/').split('/'))
                if not target:
                    # Root suite is selected.
                    self.targets = None
                    break
                self.targets.add(target)
        # Targets relative to parent suites.
        self.saved_targets = []

    def __contains__(self, suite):
        # Checks if the given suite is selected.
        if self.targets is None:
            return True
        return any(fnmatch.fnmatchcase(suite, target[0])
                   for target in self.targets)

    def identify(self):
        # Returns the current path in filesystem notation.
        if not self.path:
            return "/"
        return "".join("/"+suite for suite in self.path)

    def descend(self, suite):
        # Descends down to the given suite.
        self.path.append(suite)
        # Update the set of selected targets.
        self.saved_targets.append(self.targets)
        if self.targets is not None:
            self.targets = set(target[1:]
                               for target in self.targets
                               if fnmatch.fnmatchcase(suite, target[0]))
            if () in self.targets:
                self.targets = None

    def ascend(self):
        # Exits from the current suite.
        self.path.pop()
        self.targets = self.saved_targets.pop()


class State(dict):
    # Storage for conditional variables.

    __slots__ = ('_snapshots')

    def __init__(self, *args, **kwds):
        super(State, self).__init__(*args, **kwds)
        # Saved copies of the state.
        self._snapshots = []

    def save(self):
        # Makes a snapshot.
        self._snapshots.append(self.copy())

    def restore(self):
        # Reverts to the last snapshot.
        self.clear()
        self.update(self._snapshots.pop())


class Control(object):
    """Test harness."""

    def __init__(self,
                 ui=None,
                 fs=None,
                 variables=None,
                 targets=None,
                 training=False,
                 purging=False,
                 max_errors=1,
                 quiet=False):
        # User interface abstraction.
        if ui is None:
            ui = ConsoleUI()
        if quiet:
            ui = SilentUI(ui)
        self.ui = ui
        ## File system access abstraction.
        #if fs is None:
        #    fs = StandardFS()
        #self.fs = fs
        # If set, the harness is in training mode.
        self.training = training
        # If set, purge stale test output data.
        self.purging = purging
        # Numbers of passed, failed and updated test cases.
        self.success_num = 0
        self.failure_num = 0
        self.update_num = 0
        # Permitted number of failures before the harness halts.
        self.max_errors = max_errors
        # If set, display only warnings and errors.
        self.quiet = quiet
        # If set, the harness is halted.
        self.halted = False
        # Set of conditional variables.
        self.state = State(variables or {})
        # Selected suites.
        self.selection = Selection(targets)

    def passed(self, text=None):
        """Attests that a test case has passed."""
        if text:
            self.ui.notice(text)
        self.success_num += 1

    def failed(self, text=None):
        """Attests that a test case has failed."""
        if text:
            self.ui.warning(text)
        self.failure_num += 1
        if self.max_errors and self.failure_num >= self.max_errors:
            self.halted = True

    def updated(self, text=None):
        """Attests that a test case has been updated."""
        if text:
            self.ui.notice(text)
        self.update_num += 1

    def halt(self, text=None):
        """Halts the testing process."""
        if text:
            self.ui.error(text)
        self.halted = True

    def load_input(self, path):
        """Loads input test data from the given file."""
        return load(path, registry.input_types, self.state)

    def load_output(self, path):
        """Loads output test data from the given file."""
        return load(path, registry.output_types)

    def dump_output(self, path, data):
        """Saves output test data to the given file."""
        return dump(path, data)

    def run(self, case):
        """Executes a test case."""
        return case()

    def __call__(self, input_path, output_path):
        """Runs the testing process with the given input and output."""
        # Load input and output data.
        input = self.load_input(input_path)
        output = None
        if output_path is not None and os.path.exists(output_path):
            output = self.load_output(output_path)
            if not input.__complements__(output):
                output = None
        # Generate and run a test case.
        case = input.__owner__(self, input, output)
        new_output = self.run(case)
        # Display statistics.
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
        # Save updated output data.
        if (output_path is not None and
                new_output is not None and new_output != output):
                reply = self.ui.choice(None, ('', "save changes"),
                                             ('d', "discard changes"))
                if reply == '':
                    self.ui.notice("saving test output to %r" % output_path)
                    self.dump_output(output_path, new_output)
        return int(bool(self.failure_num))


