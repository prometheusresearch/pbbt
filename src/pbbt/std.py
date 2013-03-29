#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import test_type, test_field, TestRecord
from .check import listof, oneof, dictof
from .load import locate
import sys
import os, os.path
import shutil
import re
import StringIO
import subprocess
import traceback
import difflib


def is_attr(text, attr_re=re.compile(r'^[A-Za-z_][0-9A-Za-z_]*$')):
    return (attr_re.match(text) is not None)


def is_filename(text,
                filename_re=re.compile(r'^/?[\w_.-]+(?:/[\w_.-]+)*$')):
    return (filename_re.match(text) is not None)


def to_id(text, trim_re=re.compile(r'^[\W_]+|[\W_]+$'),
                norm_re=re.compile(r'(?:[^\w.]|_)+')):
    for line in text.splitlines():
        line = norm_re.sub('-', trim_re.sub('', line)).lower()
        if line:
            return line
    return '-'


@test_type
class TestCaseMixin(object):

    class Input:
        skip = test_field(bool, default=False, order=1e10+1,
                          hint="skip the test")
        if_ = test_field(oneof(str, listof(str)), default=None, order=1e10+2,
                         hint="run only the condition is satisfied")
        unless = test_field(oneof(str, listof(str)), default=None, order=1e10+3,
                            hint="run unless the condition is satisfied")

    def __init__(self, ctl, input, output):
        self.ctl = ctl
        self.ui = ctl.ui
        self.state = ctl.state
        self.input = input
        self.output = output

    def __call__(self):
        if self.skipped():
            return self.output
        self.start()
        if self.ctl.training:
            return self.train()
        else:
            return self.check()

    def skipped(self):
        if self.input.skip:
            return True
        for condition, result in [(self.input.if_, True),
                                  (self.input.unless, False)]:
            if condition is None:
                continue
            if isinstance(condition, str) and is_attr(condition):
                condition = [condition]
            if isinstance(condition, list):
                if any(self.ctl.state.get(key) for key in condition) is not result:
                    return True
            else:
                try:
                    if eval(condition, self.state):
                        if not result:
                            return True
                    else:
                        if result:
                            return True
                except:
                    lines = traceback.format_exc().splitlines()
                    self.ui.literal(*lines)
                    self.ctl.halt("unexpected exception occurred")
                    return True

    def start(self):
        lines = []
        lines.extend(str(self.input).splitlines())
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.section()
        self.ui.header(*lines)

    def check(self):
        raise NotImplementedError("%s.check()" % self.__class__.__name__)

    def train(self):
        return self.check()


@test_type
class RunAndCompareMixin(TestCaseMixin):

    class Input:
        ignore = test_field(oneof(bool, str), default=False, order=1e5+1,
                            hint="ignore the output")

        @classmethod
        def __load__(cls, mapping):
            if 'ignore' in mapping and isinstance(mapping['ignore'], str):
                try:
                    re.compile(mapping['ignore'], re.X|re.M)
                except re.error, exc:
                    raise ValueError("invalid regular expression: %s" % exc)
            return super(RunAndCompareMixin.Input, cls).__load__(mapping)

    def run(self):
        raise NotImplementedError("%s.run()" % self.__class__.__name__)

    def render(self, output):
        raise NotImplementedError("%s.render()" % self.__class__.__name__)

    def differs(self, text, new_text):
        text = self.normalize(text)
        new_text = self.normalize(new_text)
        return (text != new_text)

    def normalize(self, text):
        if self.input.ignore is True:
            return ""
        if not self.input.ignore:
            return text
        ignore_re = re.compile(self.input.ignore, re.X|re.M)
        def replace(match):
            if ignore_re.groups:
                spans = []
                group_start = match.start()
                for idx in range(1, ignore_re.groups+1):
                    start, end = match.span(idx)
                    if start < end:
                        spans.append((end-group_start, start-group_start))
                spans.sort()
                spans.reverse()
                group = match.group()
                last_cut = len(group)
                for end, start in spans:
                    end = min(end, last_cut)
                    if start >= end:
                        continue
                    group = group[:start]+group[end:]
                    last_cut = start
                return group
            else:
                return ""
        text = ignore_re.sub(replace, text)
        return text

    def show(self, text, new_text):
        if text is None:
            self.ui.notice("test output is new")
        elif text != new_text:
            self.ui.notice("test output has changed")
        else:
            self.ui.notice("test output has not changed")
        if text is None or text == new_text:
            lines = new_text.splitlines()
        else:
            diff = difflib.unified_diff(text.splitlines(),
                                        new_text.splitlines(),
                                        n=2, lineterm='')
            lines = list(diff)[2:]
        self.ctl.ui.literal(*lines)

    def check(self):
        if self.output is None:
            self.ctl.failed("no output data found")
            return
        new_output = self.run()
        if new_output is None:
            self.ctl.failed()
            return
        text = self.render(self.output)
        new_text = self.render(new_output)
        if self.differs(text, new_text):
            self.show(text, new_text)
            self.ctl.failed("unexpected test output")
            return
        self.ctl.passed()

    def train(self):
        new_output = self.run()
        if new_output is None:
            self.ctl.failed()
            reply = self.ui.choice(('', "halt"), ('c', "continue"))
            if reply == '':
                self.ctl.halt()
            return self.output
        text = None
        if self.output is not None:
            text = self.render(self.output)
        new_text = self.render(new_output)
        if text is None or self.differs(text, new_text):
            self.show(text, new_text)
            reply = self.ui.choice(('', "record"), ('s', "skip"), ('h', "halt"))
            if reply == '':
                self.ctl.updated()
                return new_output
            if reply == 'h':
                self.ctl.halt()
            self.ctl.failed()
            return self.output
        self.ctl.passed()
        return self.output


@test_type
class SetCase(TestCaseMixin):

    class Input:
        set_ = test_field(oneof(str, dictof(str, object)))

    def check(self):
        if isinstance(self.input.set_, str):
            self.ctl.state[self.input.set_] = True
        else:
            self.ctl.state.update(self.input.set_)


@test_type
class SuiteCase(TestCaseMixin):

    class Input:
        suite = test_field(str, default=None)
        title = test_field(str)
        output = test_field(str, default=None)
        tests = test_field(listof(TestRecord))

        @classmethod
        def __recognizes__(cls, keys):
            return ('tests' in keys)

        @classmethod
        def __load__(cls, mapping):
            if 'suite' not in mapping and 'title' in mapping:
                mapping['suite'] = to_id(mapping['title'])
            return super(SuiteCase.Input, cls).__load__(mapping)

        def __complements__(self, other):
            if not isinstance(other, SuiteCase.Output):
                return False
            return self.suite == other.suite

        def __str__(self):
            return self.title

    class Output:
        suite = test_field(str)
        tests = test_field(listof(TestRecord))

    def __init__(self, ctl, input, output):
        super(SuiteCase, self).__init__(ctl, input, output)

    def __call__(self):
        self.ctl.save_state()
        try:
            return super(SuiteCase, self).__call__()
        finally:
            self.ctl.restore_state()

    def load(self):
        if self.input.output is not None and os.path.exists(self.input.output):
            output = self.ctl.load_output(self.input.output)
            if isinstance(output, SuiteCase.Output):
                return output
        return self.output

    def complement(self, input, output):
        cases = []
        case_inputs = input.tests
        case_outputs = output.tests[:] if output is not None else []
        groups = []
        for case_input in case_inputs:
            case_type = case_input.__owner__
            for idx, case_output in enumerate(case_outputs):
                if case_input.__complements__(case_output):
                    groups.append((case_type, case_input, case_output))
                    del case_outputs[idx]
                    break
            else:
                groups.append((case_type, case_input, None))
        for case_type, case_input, case_output in groups:
            case = case_type(self.ctl, case_input, case_output)
            cases.append(case)
        return cases

    def start(self):
        lines = [str(self.input)]
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.part()
        self.ui.header(*lines)

    def check(self):
        output = self.load()
        cases = self.complement(self.input, output)
        for case in cases:
            self.ctl.run(case)
            if self.ctl.halted:
                break

    def train(self):
        output = self.load()
        cases = self.complement(self.input, output)
        new_case_output_map = {}
        for case in cases:
            new_case_output = self.ctl.run(case)
            if new_case_output != case.output:
                new_case_output_map[case] = new_case_output
            if self.ctl.halted:
                break

        tests = output.tests[:] if output is not None else []

        if self.ctl.purging and not self.ctl.halted:
            tests = []
            for case in cases:
                case_output = case.output
                if case in new_case_output_map:
                    case_output = new_case_output_map[case]
                if case_output is not None:
                    tests.append(case_output)

        elif new_case_output_map:
            inserts = []
            updates = []
            case_output_index = {}
            for idx, case_output in enumerate(tests):
                case_output_index[id(case_output)] = idx
            new_idx = 0
            for case in cases:
                if case in new_case_output_map:
                    new_case_output = new_case_output_map[case]
                    if new_case_output is not None:
                        if id(case.output) in case_output_index:
                            idx = case_output_index[id(case.output)]
                            updates.append((idx, new_case_output))
                            if idx >= new_idx:
                                new_idx = idx+1
                        else:
                            inserts.append((new_idx, new_case_output))
                            new_idx += 1
                else:
                    if id(case.output) in case_output_index:
                        idx = case_output_index[id(case.output)]
                        new_idx = idx+1
            for idx, case_output in updates:
                tests[idx] = case_output
            for idx, case_output in reversed(sorted(inserts)):
                tests.insert(idx, case_output)

        if not tests:
            new_output = None
        elif output is not None and tests == output.tests:
            new_output = output
        else:
            new_output = self.Output(suite=self.input.suite, tests=tests)

        if self.input.output is not None:
            if output is self.output or output != new_output:
                reply = self.ui.choice(('', "save changes"),
                                       ('d', "discard changes"))
                if reply == 'd':
                    return self.output
                self.ui.notice("saving test output to %r" % self.input.output)
                self.ctl.dump_output(self.input.output, new_output)
            return None

        return new_output


@test_type
class IncludeCase(TestCaseMixin):

    class Input:
        include = test_field(str)

    class Output:
        include = test_field(str)
        output = test_field(TestRecord)

    def load(self):
        included_input = self.ctl.load_input(self.input.include)
        case_type = included_input.__owner__
        included_output = None
        if self.output is not None:
            if included_input.__complements__(self.output.output):
                included_output = self.output.output
        case = case_type(self.ctl, included_input, included_output)
        return case

    def check(self):
        case = self.load()
        self.ctl.run(case)

    def train(self):
        case = self.load()
        new_output = self.ctl.run(case)
        if new_output is None:
            output = None
        elif new_output != case.output:
            output = self.Output(include=self.input.include, output=new_output)
        else:
            output = self.output
        return output


@test_type
class PythonCase(RunAndCompareMixin):

    class Input:
        py = test_field(str)
        stdin = test_field(str, default='')
        except_ = test_field(str, default=None)

        def __complements__(self, other):
            if not isinstance(other, PythonCase.Output):
                return False
            if is_filename(self.py):
                return (self.py == other.py)
            else:
                return (to_id(self.py) == to_id(other.py))

        def __str__(self):
            if is_filename(self.py):
                return "PY: %s" % self.py
            else:
                return "PY: %s" % to_id(self.py)

    class Output:
        py = test_field(str)
        stdout = test_field(str)

    def run(self):
        if is_filename(self.input.py):
            py_id = self.input.py
            try:
                source = open(self.input.py, 'rb')
            except IOError:
                self.ui.notice("missing file %r" % self.input.py)
                return
        else:
            py_id = to_id(self.input.py)
            source = self.input.py
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdin = StringIO.StringIO(self.input.stdin)
        sys.stdout = StringIO.StringIO()
        sys.stderr = sys.stdout
        try:
            context = {}
            context['__pbbt__'] = self.state
            exc_info = None
            try:
                exec source in context
            except:
                exc_info = sys.exc_info()
            stdout = sys.stdout.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        new_output = self.Output(py=py_id, stdout=stdout)
        if exc_info is not None:
            exc_name = exc_info[0].__name__
            if self.input.except_ is None or self.input.except_ != exc_name:
                lines = traceback.format_exception(*exc_info)
                lines = "".join(lines).splitlines()
                self.ui.notice("unexpected exception occured")
                if stdout:
                    self.ui.literal(*stdout.splitlines())
                self.ui.literal(*lines)
                return
        else:
            if self.input.except_ is not None:
                self.ui.notice("exception %r did not occur"
                               % self.input.except_)
                if stdout:
                    self.ui.literal(*stdout.splitlines())
                return
        return new_output

    def render(self, output):
        return output.stdout


@test_type
class ShellCase(RunAndCompareMixin):

    class Input:
        sh = test_field(oneof(str, listof(str)))
        cd = test_field(str, default=None)
        environ = test_field(dictof(str, str), default=None)
        stdin = test_field(str, default='')
        exit = test_field(int, default=0)

        def __str__(self):
            if isinstance(self.sh, str):
                return "SH: %s" % self.sh
            else:
                return "SH: %s" % " ".join(self.sh)

    class Output:
        sh = test_field(oneof(str, listof(str)))
        stdout = test_field(str)

    def run(self):
        command = self.input.sh
        if isinstance(command, str):
            command = command.split()
        environ = None
        if self.input.environ:
            environ = os.environ.copy()
            environ.update(self.input.environ)
        try:
            proc = subprocess.Popen(command,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    cwd=self.input.cd,
                                    env=environ)
            stdout, stderr = proc.communicate(self.input.stdin)
        except OSError, exc:
            self.ui.literal(*str(exc).splitlines())
            self.ui.notice("failed to execute the process")
            return
        if proc.returncode != self.input.exit:
            if stdout:
                self.ui.literal(*stdout.splitlines())
            self.ui.notice("unexpected exit code (%s)" % proc.returncode)
            return
        return self.Output(sh=self.input.sh, stdout=stdout)

    def render(self, output):
        return output.stdout


@test_type
class WriteToFileCase(TestCaseMixin):

    class Input:
        write = test_field(str)
        data = test_field(str)

    def check(self):
        stream = open(self.input.write, 'wb')
        stream.write(self.input.data)
        stream.close()


@test_type
class ReadFromFileCase(RunAndCompareMixin):

    class Input:
        read = test_field(str)

    class Output:
        read = test_field(str)
        data = test_field(str)

    def run(self):
        if not os.path.exists(self.input.read):
            self.ctl.fail("missing file %r" % self.input.read)
            return
        stream = open(self.input.read, 'rb')
        data = stream.read()
        stream.close()
        return self.Output(self.input.read, data)

    def render(self, output):
        return self.output.data


@test_type
class RemoveFileCase(TestCaseMixin):

    class Input:
        rm = test_field(oneof(str, listof(str)))

        def __str__(self):
            if isinstance(self.rm, str):
                return "RM: %s" % self.rm
            else:
                return "RM: %s" % " ".join(self.rm)

    def check(self):
        if isinstance(self.input.rm, str):
            filenames = [self.input.rm]
        else:
            filenames = self.input.rm
        for filename in filenames:
            if os.path.exists(filename):
                os.unlink(filename)


@test_type
class MakeDirectoryCase(TestCaseMixin):

    class Input:
        mkdir = test_field(str)

    def check(self):
        if not os.path.isdir(self.input.mkdir):
            os.makedirs(self.input.mkdir)


@test_type
class RemoveDirectoryCase(TestCaseMixin):

    class Input:
        rmdir = test_field(str)

    def check(self):
        if os.path.exists(self.input.rmdir):
            shutil.rmtree(self.input.rmdir)


