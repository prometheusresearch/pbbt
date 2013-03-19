#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import test_type, test_field, TestRecord
from .check import listof, oneof
from .load import locate
import sys
import os
import re
import StringIO


class TestCaseMixin(object):

    class Input:
        skip = test_field(bool, default=False, order=1e10+1)
        if_ = test_field(oneof(str, listof(str)), default=None, order=1e10+2)
        unless = test_field(oneof(str, listof(str)), default=None, order=1e10+3)

    def __init__(self, ctl, input, output):
        self.ctl = ctl
        self.ui = ctl.ui
        self.input = input
        self.output = output

    def __call__(self):
        if self.skipped():
            return self.output
        self.header()
        if self.ctl.training:
            return self.train()
        else:
            return self.check()

    def __len__(self):
        return 1

    def skipped(self):
        if self.input.skip:
            return True
        for condition, result in [(self.input.if_, True),
                                  (self.input.unless, False)]:
            if condition is None:
                continue
            if isinstance(condition, str) and \
                    re.match(r'^[A-Za-z_][0-9A-Za-z_]*$', condition):
                condition = [condition]
            if isinstance(condition, list):
                if any(self.ctl.state.get(key) for key in condition) is not result:
                    return True
            else:
                try:
                    if eval(condition, self.ctl.state):
                        if not result:
                            return True
                    else:
                        if result:
                            return True
                except:
                    lines = traceback.format_exc().splitlines()
                    self.ui.literal(lines)
                    self.ctl.halts("unexpected exception occurred")
                    return True

    def header(self):
        lines = []
        if self.Input.__fields__:
            attr = self.Input.__fields__[0].attr
            value = getattr(self.input, attr)
            if isinstance(value, list):
                text = " ".join(str(item) for item in value)
            else:
                text = str(value)
            lines.append(text)
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.section()
        self.ui.header(*lines)

    def check(self):
        raise NotImplementedError("%s.check()" % self.__class__.__name__)

    def train(self):
        return self.check()


class RunAndCompareMixin(TestCaseMixin):

    def run(self):
        raise NotImplementedError("%s.run()" % self.__class__.__name__)

    def render(self, output):
        raise NotImplementedError("%s.render()" % self.__class__.__name__)

    def matches(self, output, new_output):
        return (output == new_output)

    def compare(self, output, new_output):
        lines = None
        if output is not None:
            lines = self.render(output)
        new_lines = self.render(new_output)
        if lines is None:
            self.ui.notice("test output is new")
        elif lines != new_lines:
            self.ui.notice("test output has changed")
        else:
            self.ui.notice("test output has not changed")
        if lines is None or lines == new_lines:
            lines = new_lines
        else:
            diff = difflib.unified_diff(lines, new_lines, n=2, lineterm='')
            lines = list(diff)[2:]
        self.ctl.ui.literal(*lines)

    def check(self):
        if self.output is None:
            return self.ctl.fails("no output data found")
        new_output = self.run()
        if new_output is None:
            return self.ctl.fails()
        if not self.matches(self.output, new_output):
            self.compare(self.output, new_output)
            return self.ctl.fails("unexpected test output")
        return self.ctl.passes()

    def train(self):
        new_output = self.run()
        if new_output is None:
            reply = self.ui.choice(('', "halt"), ('c', "continue"))
            if reply == '':
                self.ctl.halts()
            else:
                self.ctl.fails()
            return self.output
        if not self.matches(self.output, new_output):
            self.compare(self.output, new_output)
            reply = self.ui.choice(('', "record"), ('s', "skip"), ('h', "halt"))
            if reply == 'h':
                self.ctl.halts()
                return self.output
            if reply == '':
                self.ctl.updates()
                return new_output
            self.ctl.fails()
            return self.output

        self.ctl.passes()
        return self.output


@test_type
class SetCase(TestCaseMixin):

    class Input:
        set_ = test_field(str)

    def check(self):
        self.ctl.state[self.input.set_] = True


@test_type
class SuiteCase(TestCaseMixin):

    class Input:
        id = test_field(str, default=None)
        title = test_field(str)
        filename = test_field(str, default=None)
        tests = test_field(listof(TestRecord))

        @classmethod
        def __detects__(cls, keys):
            return ('tests' in keys)

        @classmethod
        def __load__(cls, mapping):
            if 'id' not in mapping and 'title' in mapping:
                mapping['id'] = mapping['title'].lower().replace(' ', '-')
            if 'tests' in mapping and isinstance(mapping['tests'], list):
                for idx, test in enumerate(mapping['tests']):
                    if isinstance(test, dict) and test:
                        raise ValueError("invalid test #%s: cannot find"
                                         " any test type with fields %s"
                                         % (idx+1, ", ".join(repr(key)
                                                    for key in sorted(test))))
                    elif not isinstance(test, TestRecord):
                        raise ValueError("invalid test #%s" % (idx+1))
            return super(SuiteCase.Input, cls).__load__(mapping)

        def __matches__(self, other):
            if not isinstance(other, SuiteCase.Output):
                return False
            return (self.id == other.id)

    class Output:
        id = test_field(str)
        tests = test_field(listof(TestRecord))

    def __init__(self, ctl, input, output):
        super(SuiteCase, self).__init__(ctl, input, output)
        self.ext_output = None
        if input.filename is not None and os.path.exists(input.filename):
            self.ext_output = self.ctl.load_output(input.filename)
        self.cases = []
        groups = []
        available_outputs = []
        if self.ext_output is not None:
            available_outputs = self.ext_output.tests[:]
        elif self.output is not None:
            available_outputs = self.output.tests[:]
        for case_input in self.input.tests:
            case_type = case_input.__owner__
            for idx, case_output in enumerate(available_outputs):
                if case_input.__matches__(case_output):
                    groups.append((case_type, case_input, case_output))
                    del available_outputs[idx]
                    break
            else:
                groups.append((case_type, case_input, None))
        for case_type, case_input, case_output in groups:
            case = case_type(ctl, case_input, case_output)
            self.cases.append(case)

    def __len__(self):
        return len(self.cases)

    def __call__(self):
        self.ctl.save_state()
        try:
            return super(SuiteCase, self).__call__()
        finally:
            self.ctl.restore_state()

    def header(self):
        lines = [self.input.title]
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.part()
        self.ui.header(*lines)

    def check(self):
        for case in self.cases:
            self.ctl.run(case)
            if self.ctl.halted:
                break

    def train(self):
        new_output_map = {}
        for case in self.cases:
            new_output = self.ctl.run(case)
            if new_output != case.output:
                new_output_map[case] = new_output
            if self.ctl.halted:
                break
        output = self.make_output(new_output_map)
        if self.input.filename is not None:
            if output != self.ext_output:
                reply = self.ui.choice(('', "save changes"),
                                       ('d', "discard changes"))
                if reply == 'd':
                    return self.output
                self.ui.notice("saving test output to %r" % self.input.filename)
                self.ctl.dump_output(self.input.filename, output)
            return None
        return output

    def make_output(self, new_output_map):
        tests = []
        if self.output is not None:
            tests = self.output.tests[:]
        if self.ext_output is not None:
            tests = self.ext_output.tests[:]

        if self.ctl.purging and not self.ctl.halted:
            tests = []
            for case in self.cases:
                output = case.output
                if case in new_output_map:
                    output = new_output_map[case]
                if output is not None:
                    tests.append(output)

        elif new_output_map:
            new_idx = 0
            for case in self.cases:
                if case in new_output_map:
                    new_output = new_output_map[case]
                    if new_output is not None:
                        if case.output in tests:
                            idx = tests.index(case.output)
                            tests[idx] = new_output
                            if idx >= new_idx:
                                new_idx = idx+1
                        else:
                            tests.insert(new_idx, new_output)
                            new_idx += 1
                else:
                    if case.output in tests:
                        idx = tests.index(case.output)
                        new_idx = idx+1
        if not tests:
            return None

        if self.input.filename is not None:
            if self.ext_output is not None and self.ext_output.tests == tests:
                return self.ext_output
        else:
            if self.output is not None and self.output.tests == tests:
                return self.output
        return self.Output(id=self.input.id, tests=tests)


@test_type
class IncludeCase(TestCaseMixin):

    class Input:
        include = test_field(str)

    class Output:
        include = test_field(str)
        output = test_field(TestRecord)

    def __init__(self, ctl, input, output):
        super(IncludeCase, self).__init__(ctl, input, output)
        self.included_input = ctl.load_input(input.include)
        case_type = self.included_input.__owner__
        self.included_output = None
        if self.output is not None:
            if self.included_input.__matches__(self.output.output):
                self.included_output = self.output.output
        self.case = case_type(ctl, self.included_input, self.included_output)

    def check(self):
        self.case()

    def train(self):
        new_output = self.case()
        if new_output is None:
            output = None
        elif new_output != self.included_output:
            output = self.Output(include=self.input.include,
                                 output=new_output)
        else:
            new_output = self.output
        return output


@test_type
class PythonCase(RunAndCompareMixin):

    class Input:
        py = test_field(str)
        stdin = test_field(str, default='')
        except_ = test_field(str, default=None)

        @property
        def id(self):
            lines = self.py.strip().splitlines()
            if lines:
                return lines[0]
            return None

        @property
        def filename(self, regex=re.compile(r'^/?[\w_.-]+(?:/[\w_.-]+)*\.py$')):
            if regex.match(self.py):
                return self.py
            return None

        def __matches__(self, other):
            if not (self.__owner__ is other.__owner__ and
                    self.__class__ is not other.__class__):
                return False
            return (self.id == other.id)

    class Output:
        py = test_field(str)
        stdout = test_field(str)

        @property
        def id(self):
            return self.py

    def run(self):
        filename = self.input.filename
        if filename is not None:
            try:
                stream = open(filename, 'rb')
                code = stream.read()
                stream.close()
            except IOError:
                return self.ctl.fails("missing file %r" % filename)
        else:
            code = self.input.py
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdin = StringIO.StringIO(self.input.stdin)
        sys.stdout = StringIO.StringIO()
        sys.stderr = sys.stdout
        try:
            context = {}
            context['__state__'] = self.ctl.state
            exc_info = None
            try:
                exec code in context
            except:
                exc_info = sys.exc_info()
            stdout = sys.stdout.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        new_output = self.Output(py=self.input.id, stdout=stdout)
        if exc_info is not None:
            exc_name = exc_info[0].__name__
            if self.input.except_ is None or self.input.except_ != exc_name:
                self.ctl.fails("an unexpected exception occured")
                return
        else:
            if self.input.except_ is not None:
                self.ctl.fails("an expected exception did not occur")
                return
        return new_output

    def render(self, output):
        return output.stdout.splitlines()


@test_type
class ShellCase(RunAndCompareMixin):

    class Input:
        sh = test_field(oneof(str, listof(str)))
        stdin = test_field(str, default='')
        exit = test_field(int, default=0)

    class Output:
        sh = test_field(oneof(str, listof(str)))
        stdout = test_field(str)


@test_type
class WriteCase(TestCaseMixin):

    class Input:
        write = test_field(str)
        data = test_field(str)


@test_type
class ReadCase(RunAndCompareMixin):

    class Input:
        read = test_field(str)

    class Output:
        read = test_field(str)
        data = test_field(str)


@test_type
class RemoveCase(TestCaseMixin):

    class Input:
        rm = test_field(str)


@test_type
class MakeDirectoryCase(TestCaseMixin):

    class Input:
        mkdir = test_field(str)


@test_type
class RemoveDirectoryCase(TestCaseMixin):

    class Input:
        rmdir = test_field(str)



