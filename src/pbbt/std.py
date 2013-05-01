#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import Test, Field, Record
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


def is_attribute(text, attr_re=re.compile(r'^[A-Za-z_][0-9A-Za-z_]*$')):
    return (attr_re.match(text) is not None)


def is_filename(text,
                filename_re=re.compile(r'^/?[\w_.-]+(?:/[\w_.-]+)*$')):
    return (filename_re.match(text) is not None)


def to_identifier(text, trim_re=re.compile(r'^[\W_]+|[\W_]+$'),
                        norm_re=re.compile(r'(?:[^\w.]|_)+')):
    for line in text.splitlines():
        line = norm_re.sub('-', trim_re.sub('', line)).lower()
        if line:
            return line
    return '-'


class BaseCase(object):

    class Input:
        skip = Field(bool, default=False, order=1e10+1,
                     hint="skip the test")
        if_ = Field(oneof(str, listof(str)), default=None, order=1e10+2,
                    hint="run only the condition is satisfied")
        unless = Field(oneof(str, listof(str)), default=None, order=1e10+3,
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
        for condition, expect in [(self.input.if_, True),
                                  (self.input.unless, False)]:
            if condition is None:
                continue
            if isinstance(condition, str) and is_attribute(condition):
                condition = [condition]
            if isinstance(condition, list):
                check = any(self.ctl.state.get(key) for key in condition)
            else:
                try:
                    check = bool(eval(condition, self.state))
                except:
                    self.ui.literal(traceback.format_exc())
                    self.ctl.halt("unexpected exception occurred "
                                  "when evaluating %r" % condition)
                    return True
            if check != expect:
                return True

    def start(self):
        lines = str(self.input).splitlines()
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.section()
        self.ui.header("\n".join(lines))

    def check(self):
        raise NotImplementedError("%s.check()" % self.__class__.__name__)

    def train(self):
        return self.check()


class MatchCase(BaseCase):

    class Input:
        ignore = Field(oneof(bool, str), default=False, order=1e5+1,
                       hint="ignore the output")

        @classmethod
        def __load__(cls, mapping):
            if 'ignore' in mapping and isinstance(mapping['ignore'], str):
                try:
                    re.compile(mapping['ignore'], re.X|re.M)
                except re.error, exc:
                    raise ValueError("invalid regular expression: %s" % exc)
            return super(MatchCase.Input, cls).__load__(mapping)

    def run(self):
        raise NotImplementedError("%s.run()" % self.__class__.__name__)

    def render(self, output):
        raise NotImplementedError("%s.render()" % self.__class__.__name__)

    def sanitize(self, text):
        if self.input.ignore is True:
            return ""
        if not self.input.ignore:
            return text
        ignore_re = re.compile(self.input.ignore, re.X|re.M)
        text = ignore_re.sub(self._sanitize_replace, text)
        return text

    @staticmethod
    def _sanitize_replace(match):
        if not match.re.groups:
            return ""
        spans = []
        group_start = match.start()
        for idx in range(match.re.groups):
            start, end = match.span(idx+1)
            if start < end:
                start -= group_start
                end -= group_start
                spans.append((end, start))
        spans.sort()
        spans.reverse()
        text = match.group()
        last_cut = len(text)
        for end, start in spans:
            end = min(end, last_cut)
            if start >= end:
                continue
            text = text[:start]+text[end:]
            last_cut = start
        return text

    def display(self, text, new_text):
        if text is None:
            self.ui.notice("new test output")
            self.ui.literal(new_text)
        elif text == new_text:
            self.ui.notice("test output has not changed")
        else:
            diff = difflib.unified_diff(text.splitlines(),
                                        new_text.splitlines(),
                                        n=2, lineterm='')
            lines = list(diff)[2:]
            self.ui.notice("test output has changed")
            self.ui.literal("\n".join(lines))

    def check(self):
        if self.output is None:
            self.ctl.failed("cannot find expected test output")
            return
        new_output = self.run()
        if new_output is None:
            self.ctl.failed()
            return
        text = self.render(self.output)
        new_text = self.render(new_output)
        if self.sanitize(text) != self.sanitize(new_text):
            self.display(text, new_text)
            self.ctl.failed("unexpected test output")
            return
        self.ctl.passed()

    def train(self):
        new_output = self.run()
        if new_output is None:
            self.ctl.failed()
            reply = self.ui.choice(None, ('', "halt"), ('c', "continue"))
            if reply == '':
                self.ctl.halt()
            return self.output
        text = self.render(self.output) if self.output is not None else None
        new_text = self.render(new_output)
        if text is None or self.sanitize(text) != self.sanitize(new_text):
            self.display(text, new_text)
            reply = self.ui.choice(None,
                    ('', "record"), ('s', "skip"), ('h', "halt"))
            if reply == '':
                self.ctl.updated()
                return new_output
            if reply == 'h':
                self.ctl.halt()
            self.ctl.failed()
            return self.output
        self.ctl.passed()
        return self.output


@Test
class SetCase(BaseCase):

    class Input:
        set_ = Field(oneof(str, dictof(str, object)),
                     hint="set a conditional variable")

    def check(self):
        if isinstance(self.input.set_, str):
            self.ctl.state[self.input.set_] = True
        else:
            self.ctl.state.update(self.input.set_)


@Test
class SuiteCase(BaseCase):

    class Input:
        suite = Field(str, default=None,
                      hint="suite identifier")
        title = Field(str,
                      hint="suite title")
        output = Field(str, default=None,
                       hint="file with expected output")
        tests = Field(listof(Record),
                      hint="list of test inputs")

        @classmethod
        def __recognizes__(cls, keys):
            return ('tests' in keys)

        @classmethod
        def __load__(cls, mapping):
            if 'suite' not in mapping and 'title' in mapping:
                mapping['suite'] = to_identifier(mapping['title'])
            return super(SuiteCase.Input, cls).__load__(mapping)

        def __complements__(self, other):
            if not isinstance(other, SuiteCase.Output):
                return False
            return self.suite == other.suite

        def __str__(self):
            return self.title

    class Output:
        suite = Field(str,
                      hint="suite identifier")
        tests = Field(listof(Record),
                      hint="list of test outputs")

    def __init__(self, ctl, input, output):
        super(SuiteCase, self).__init__(ctl, input, output)

    def __call__(self):
        if self.input.suite not in self.ctl.tree:
            return self.output
        self.ctl.tree.descend(self.input.suite)
        self.ctl.state.save()
        try:
            return super(SuiteCase, self).__call__()
        finally:
            self.ctl.state.restore()
            self.ctl.tree.ascend()

    def load(self):
        if self.input.output is not None and os.path.exists(self.input.output):
            output = self.ctl.load_output(self.input.output)
            if self.input.__complements__(output):
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
        lines = ["%s [%s]" % (self.input, self.ctl.tree.identify())]
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.part()
        self.ui.header("\n".join(lines))

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
            next_idx = 0
            for case in cases:
                if case in new_case_output_map:
                    new_case_output = new_case_output_map[case]
                    if new_case_output is not None:
                        if id(case.output) in case_output_index:
                            idx = case_output_index[id(case.output)]
                            updates.append((idx, new_case_output))
                            if idx >= next_idx:
                                next_idx = idx+1
                        else:
                            inserts.append((next_idx, new_case_output))
                else:
                    if id(case.output) in case_output_index:
                        idx = case_output_index[id(case.output)]
                        next_idx = idx+1
            inserts.sort(key=(lambda t: t[0]))
            for idx, case_output in updates:
                tests[idx] = case_output
            for idx, case_output in reversed(inserts):
                tests.insert(idx, case_output)
            print "TESTS:", tests

        if not tests:
            new_output = None
        elif output is not None and tests == output.tests:
            new_output = output
        else:
            new_output = self.Output(suite=self.input.suite, tests=tests)

        if self.input.output is not None:
            if output is self.output or output != new_output:
                reply = self.ui.choice(None, ('', "save changes"),
                                             ('d', "discard changes"))
                if reply == 'd':
                    return self.output
                self.ui.notice("saving test output to %r" % self.input.output)
                self.ctl.dump_output(self.input.output, new_output)
            return None

        return new_output


@Test
class IncludeCase(BaseCase):

    class Input:
        include = Field(str,
                        hint="file with tests")

    class Output:
        include = Field(str,
                        hint="file with tests")
        output = Field(Record,
                       hint="expected output")

    def load(self):
        included_input = self.ctl.load_input(self.input.include)
        case_type = included_input.__owner__
        included_output = None
        if self.output is not None:
            if included_input.__complements__(self.output.output):
                included_output = self.output.output
        case = case_type(self.ctl, included_input, included_output)
        return case

    def start(self):
        pass

    def check(self):
        case = self.load()
        self.ctl.run(case)

    def train(self):
        case = self.load()
        new_case_output = self.ctl.run(case)
        if new_case_output is None:
            output = None
        elif new_case_output == case.output:
            output = self.output
        else:
            output = self.Output(include=self.input.include,
                                 output=new_case_output)
        return output


@Test
class PythonCase(MatchCase):

    class Input:
        py = Field(str,
                   hint="file name or source code")
        stdin = Field(str, default='',
                      hint="standard input")
        except_ = Field(str, default=None,
                        hint="expected exception name")

        @property
        def py_key(self):
            if is_filename(self.py):
                return self.py
            else:
                return to_identifier(self.py)

        @property
        def py_as_filename(self):
            if is_filename(self.py):
                return self.py

        @property
        def py_as_source(self):
            if not is_filename(self.py):
                return self.py

        def __complements__(self, other):
            if not isinstance(other, PythonCase.Output):
                return False
            return (self.py_key == other.py_key)

        def __str__(self):
            return "PY: %s" % self.py_key

    class Output:
        py = Field(str,
                   hint="file name or source code identifier")
        stdout = Field(str,
                       hint="expected standard output")

        @property
        def py_key(self):
            if is_filename(self.py):
                return self.py
            else:
                return to_identifier(self.py)

    def run(self):
        filename = self.input.py_as_filename
        if filename is not None:
            try:
                stream = open(filename, 'rb')
                source = stream.read()
                stream.close()
            except IOError:
                self.ui.warning("missing file %r" % source)
                return
        else:
            source = self.input.py_as_source
            filename = "<%s>" % locate(self.input)
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
                code = compile(source, filename, 'exec')
                exec code in context
            except:
                exc_info = sys.exc_info()
            stdout = sys.stdout.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        new_output = self.Output(py=self.input.py_key, stdout=stdout)
        if exc_info is not None:
            exc_name = exc_info[0].__name__
            if self.input.except_ is None or self.input.except_ != exc_name:
                if stdout:
                    self.ui.literal(stdout)
                self.ui.literal("".join(traceback.format_exception(*exc_info)))
                self.ui.warning("unexpected exception occured")
                return
        else:
            if self.input.except_ is not None:
                if stdout:
                    self.ui.literal(stdout)
                self.ui.warning("expected exception %r did not occur"
                                % self.input.except_)
                return
        return new_output

    def render(self, output):
        return output.stdout


@Test
class ShellCase(MatchCase):

    class Input:
        sh = Field(oneof(str, listof(str)),
                   hint="command line")
        cd = Field(str, default=None,
                   hint="working directory")
        environ = Field(dictof(str, str), default=None,
                        hint="environment variables")
        stdin = Field(str, default='',
                      hint="standard input")
        exit = Field(int, default=0,
                     hint="expected exit code")

        def __str__(self):
            if isinstance(self.sh, str):
                return "SH: %s" % self.sh
            else:
                return "SH: %s" % " ".join(self.sh)

    class Output:
        sh = Field(oneof(str, listof(str)),
                   hint="command line")
        stdout = Field(str,
                       hint="expected standard output")

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
            self.ui.literal(str(exc))
            self.ui.warning("failed to execute the process")
            return
        stdout = stdout.decode('utf-8', 'replace')
        if not isinstance(stdout, str):
            stdout = stdout.encode('utf-8')
        if proc.returncode != self.input.exit:
            if stdout:
                self.ui.literal(stdout)
            self.ui.warning("unexpected exit code (%s)" % proc.returncode)
            return
        return self.Output(sh=self.input.sh, stdout=stdout)

    def render(self, output):
        return output.stdout


@Test
class WriteToFileCase(BaseCase):

    class Input:
        write = Field(str,
                      hint="file name")
        data = Field(str,
                     hint="file content")

    def check(self):
        stream = open(self.input.write, 'wb')
        stream.write(self.input.data)
        stream.close()


@Test
class ReadFromFileCase(MatchCase):

    class Input:
        read = Field(str,
                     hint="file name")

    class Output:
        read = Field(str,
                     hint="file name")
        data = Field(str,
                     hint="expected file content")

    def run(self):
        if not os.path.exists(self.input.read):
            self.ctl.fail("missing file %r" % self.input.read)
            return
        stream = open(self.input.read, 'rb')
        data = stream.read()
        stream.close()
        return self.Output(self.input.read, data)

    def render(self, output):
        return output.data


@Test
class RemoveFileCase(BaseCase):

    class Input:
        rm = Field(oneof(str, listof(str)),
                   hint="file or a list of files")

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


@Test
class MakeDirectoryCase(BaseCase):

    class Input:
        mkdir = Field(str,
                      hint="directory name")

    def check(self):
        if not os.path.isdir(self.input.mkdir):
            os.makedirs(self.input.mkdir)


@Test
class RemoveDirectoryCase(BaseCase):

    class Input:
        rmdir = Field(str,
                      hint="directory name")

    def check(self):
        if os.path.exists(self.input.rmdir):
            shutil.rmtree(self.input.rmdir)


