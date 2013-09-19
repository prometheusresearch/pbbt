#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from distutils.cmd import Command
from distutils.errors import DistutilsError, DistutilsOptionError
from .run import variable, module, run
import os.path


class pbbt(Command):
    # Distutils command: `python setup.py pbbt`.

    description = 'run PBBT tests'
    user_options = [
            ('input', 'i', "file with input data"),
            ('output', 'o', "file with output data"),
            ('train', 'T', "run tests in training mode"),
            ('purge', 'P', "purge stale output data"),
            ('max-errors', 'M', "halt after N errors"),
            ('define', 'D', "set a conditional variable"),
            ('extend', 'E', "load an extension"),
            ('suite', 'S', "run a specific test suite"),
    ]
    boolean_options = ['train', 'purge']

    def initialize_options(self):
        self.input = None
        self.output = None
        self.train = False
        self.purge = False
        self.max_errors = None
        self.define = None
        self.extend = None
        self.suite = None

    def finalize_options(self):
        if self.input is None:
            raise DistutilsOptionError("missing input file")
        if self.max_errors is not None:
            try:
                self.max_errors = int(self.max_errors)
            except ValueError as exc:
                raise DistutilsOptionError("invalid max-errors: %s" % exc)
        if self.define is not None:
            try:
                self.define = dict(variable(line)
                                   for line in self.define.split())
            except ValueError as exc:
                raise DistutilsOptionError("invalid define: %s" % exc)
        else:
            self.define = {}
        if self.extend is not None:
            try:
                self.extend = [module(line) for line in self.extend.split()]
            except ValueError as exc:
                raise DistutilsOptionError("invalid extend: %s" % exc)
        else:
            self.extend = []
        if self.suite is not None:
            self.suite = self.suite.split()

    def run(self):
        # Load extensions.
        for path in self.extend:
            if os.path.isfile(path):
                exec open(path) in {}
            else:
                __import__(path)

        # Execute the tests.
        exit = run(self.input, self.output,
                   variables=self.define,
                   targets=self.suite,
                   training=self.train,
                   purging=self.purge,
                   max_errors=self.max_errors,
                   quiet=not self.verbose)
        if exit != 0:
            raise DistutilsError("some tests failed")


