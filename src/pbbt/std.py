#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import Test, Field, Record
from .check import maybe, listof, oneof, dictof
from .load import locate
import sys
import os, os.path
import glob
import shutil
import re
import StringIO
import subprocess
import traceback
import difflib
import shlex


def is_attribute(text, attr_re=re.compile(r'^[A-Za-z_][0-9A-Za-z_]*$')):
    # Does it look like an attribute name?
    return (attr_re.match(text) is not None)


def is_filename(text,
                filename_re=re.compile(r'^/?[\w_.-]+(?:/[\w_.-]+)*$')):
    # Does it look like a filename?
    return (filename_re.match(text) is not None)


def to_identifier(text, trim_re=re.compile(r'^[\W_]+|[\W_]+$'),
                        norm_re=re.compile(r'(?:[^\w.]|_)+')):
    # Generate an identifier from the given text.
    for line in text.splitlines():
        line = norm_re.sub('-', trim_re.sub('', line)).lower()
        if line:
            return line
    return '-'


class BaseCase(object):
    """
    Template class for all test types.
    """

    class Input:
        skip = Field(bool, default=False, order=1e10+1,
                hint="skip the test if set to true")
        if_ = Field(oneof(str, listof(str)), default=None, order=1e10+2,
                hint="skip the test if the condition is not satisfied")
        unless = Field(oneof(str, listof(str)), default=None, order=1e10+3,
                hint="skip the test if the condition is satisfied")

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
        # Check if preconditions are satisfied.
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
        # Display the header.
        lines = str(self.input).splitlines()
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.section()
        self.ui.header("\n".join(lines))

    def check(self):
        # Run the case in check mode.
        raise NotImplementedError("%s.check()" % self.__class__.__name__)

    def train(self):
        # Run the case in train mode.
        return self.check()


class MatchCase(BaseCase):
    """
    Template class for test types which produce output.
    """

    class Input:
        ignore = Field(oneof(bool, str), default=False, order=1e5+1,
                hint="ignore differences between expected and actual output")

        @classmethod
        def __load__(cls, mapping):
            # Verify that `ignore` is a valid regular expression.
            if 'ignore' in mapping and isinstance(mapping['ignore'], str):
                try:
                    re.compile(mapping['ignore'], re.X|re.M)
                except re.error, exc:
                    raise ValueError("invalid regular expression: %s" % exc)
            return super(MatchCase.Input, cls).__load__(mapping)

    def run(self):
        # Execute the case; returns produced output.
        raise NotImplementedError("%s.run()" % self.__class__.__name__)

    def render(self, output):
        # Convert output to text.
        raise NotImplementedError("%s.render()" % self.__class__.__name__)

    def sanitize(self, text):
        # Remove portions of output matching `ignore` pattern.
        if self.input.ignore is True:
            return ""
        if not self.input.ignore:
            return text
        ignore_re = re.compile(self.input.ignore, re.X|re.M)
        text = ignore_re.sub(self._sanitize_replace, text)
        return text

    @staticmethod
    def _sanitize_replace(match):
        # If `ignore` pattern does not contain subgroups, remove
        # the whole match.
        if not match.re.groups:
            return ""
        # Otherwise, remove subgroups.
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

    def compare(self, text, new_text):
        # Display difference between expected and actual output.
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
        # In checking mode, expected output must be given.
        if self.output is None:
            self.ctl.failed("cannot find expected test output")
            return
        # Execute the case.
        new_output = self.run()
        # If the case failed to execute, report test failure and exit.
        if new_output is None:
            self.ctl.failed()
            return
        # Generate text representation of the output.
        text = self.render(self.output)
        new_text = self.render(new_output)
        # Compare expected and actual output; report test failure
        # if they don't match.
        if self.sanitize(text) != self.sanitize(new_text):
            self.compare(text, new_text)
            self.ctl.failed("unexpected test output")
        else:
            self.ctl.passed()

    def train(self):
        # Execute the case; produce actual output.
        new_output = self.run()
        # If the case failed to execute, report test failure and ask the user
        # whether to halt or continue.
        if new_output is None:
            self.ctl.failed()
            reply = self.ui.choice(None, ('', "halt"), ('c', "continue"))
            if reply == '':
                self.ctl.halt()
            return self.output
        # Generate text representation of the output.
        text = self.render(self.output) if self.output is not None else None
        new_text = self.render(new_output)
        # For new or changed test output, ask the user whether to save/update
        # the output, ignore the difference or halt.
        if text is None or self.sanitize(text) != self.sanitize(new_text):
            self.compare(text, new_text)
            reply = self.ui.choice(None,
                    ('', "record"), ('s', "skip"), ('h', "halt"))
            if reply == '':
                self.ctl.updated()
                return new_output
            else:
                if reply == 'h':
                    self.ctl.halt()
                self.ctl.failed()
                return self.output
        else:
            self.ctl.passed()
            return self.output


@Test
class SetCase(BaseCase):
    """
    Define a conditional variable or a set of conditional variables.
    """

    class Input:
        set_ = Field(oneof(str, dictof(str, object)),
                hint="conditional variable or dictionary of variables")

    def check(self):
        if isinstance(self.input.set_, str):
            # If value is not given, assume `True`.
            self.ctl.state[self.input.set_] = True
        else:
            self.ctl.state.update(self.input.set_)


@Test
class SuiteCase(BaseCase):
    """
    Collection of test cases.
    """

    class Input:
        suite = Field(str, default=None,
                hint="identifier of the suite")
        title = Field(str,
                hint="title of the suite")
        output = Field(str, default=None,
                hint="file containing expected output for suite tests")
        tests = Field(listof(Record),
                hint="test inputs")

        @classmethod
        def __recognizes__(cls, keys):
            return ('tests' in keys)

        @classmethod
        def __load__(cls, mapping):
            # Generate `suite` from `title` if the former is not given.
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
                hint="identifier of the suite")
        tests = Field(listof(Record),
                hint="test outputs")

    def __call__(self):
        # Check if the suite was selected.
        if self.input.suite not in self.ctl.selection:
            return self.output
        # Update the selection tree and make a snapshot of conditional
        # variables.
        self.ctl.selection.descend(self.input.suite)
        self.ctl.state.save()
        try:
            return super(SuiteCase, self).__call__()
        finally:
            # Restore the selection tree and conditional variables.
            self.ctl.state.restore()
            self.ctl.selection.ascend()

    def load(self):
        # Get expected output.
        if self.input.output is not None and os.path.exists(self.input.output):
            output = self.ctl.load_output(self.input.output)
            if self.input.__complements__(output):
                return output
        return self.output

    def complement(self, input, output):
        # Matches input and output test data; returns a list of test cases.

        # Test cases.
        cases = []
        # Input records.
        case_inputs = input.tests
        # Output records.
        case_outputs = output.tests[:] if output is not None else []
        # Generate triples of `(test_type, input, output)`.
        groups = []
        for case_input in case_inputs:
            case_type = case_input.__owner__
            for idx, case_output in enumerate(case_outputs):
                # FIXME: O(N^2).
                if case_input.__complements__(case_output):
                    groups.append((case_type, case_input, case_output))
                    del case_outputs[idx]
                    break
            else:
                groups.append((case_type, case_input, None))
        # Generate and return test cases.
        for case_type, case_input, case_output in groups:
            case = case_type(self.ctl, case_input, case_output)
            cases.append(case)
        return cases

    def start(self):
        # Display suite title.
        lines = ["%s [%s]" % (self.input, self.ctl.selection.identify())]
        location = locate(self.input)
        if location is not None:
            lines.append("(%s)" % location)
        self.ui.part()
        self.ui.header("\n".join(lines))

    def check(self):
        # Generate and execute nested test cases.
        output = self.load()
        cases = self.complement(self.input, output)
        for case in cases:
            self.ctl.run(case)
            if self.ctl.halted:
                break

    def train(self):
        # Generate nested test cases.
        output = self.load()
        cases = self.complement(self.input, output)
        # Mapping from case to produced output.
        new_case_output_map = {}
        for case in cases:
            new_case_output = self.ctl.run(case)
            if new_case_output != case.output:
                new_case_output_map[case] = new_case_output
            if self.ctl.halted:
                break

        # Generate suite output.

        # Original output data.
        tests = output.tests[:] if output is not None else []

        # If `--purge` is given, generate output from scratch.
        if self.ctl.purging and not self.ctl.halted:
            tests = []
            for case in cases:
                case_output = case.output
                if case in new_case_output_map:
                    case_output = new_case_output_map[case]
                if case_output is not None:
                    tests.append(case_output)

        # Otherwise, update original output data.
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

        # Generate new output record.
        if not tests:
            new_output = None
        elif output is not None and tests == output.tests:
            new_output = output
        else:
            new_output = self.Output(suite=self.input.suite, tests=tests)

        # Save output data.
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
    """Loads a test case from a file."""

    class Input:
        include = Field(str,
                hint="file with input test data")

    class Output:
        include = Field(str,
                hint="file with input test data")
        output = Field(Record,
                hint="expected output")

    def load(self):
        # Loads a test case from a file.
        included_input = self.ctl.load_input(self.input.include)
        case_type = included_input.__owner__
        included_output = None
        if self.output is not None:
            if included_input.__complements__(self.output.output):
                included_output = self.output.output
        case = case_type(self.ctl, included_input, included_output)
        return case

    def start(self):
        # Do not show any header.
        pass

    def check(self):
        # Load and run the test case.
        case = self.load()
        self.ctl.run(case)

    def train(self):
        # Load and run the test case in training mode.
        case = self.load()
        new_case_output = self.ctl.run(case)
        # Update expected output if necessary.
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
    """Executes Python code."""

    class Input:
        py = Field(str,
                hint="source code or file name")
        stdin = Field(str, default='',
                hint="standard input")
        except_ = Field(str, default=None,
                hint="exception type if an exception is expected")

        @property
        def py_key(self):
            # If a file name is given, use it as an identifier.
            if is_filename(self.py):
                return self.py
            # Otherwise, generate an identifier from source code.
            else:
                return to_identifier(self.py)

        @property
        def py_as_filename(self):
            # If Python file is provided, return it.
            if is_filename(self.py):
                return self.py

        @property
        def py_as_source(self):
            # If source code is provided, return it.
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
                hint="source code identifier or file name")
        stdout = Field(str,
                hint="standard output")

        @property
        def py_key(self):
            # To match `Input.py_key`.
            return self.py

    def run(self):
        # Get source code.
        filename = self.input.py_as_filename
        if filename is not None:
            try:
                stream = open(filename)
                source = stream.read()
                stream.close()
            except IOError:
                self.ui.warning("missing file %r" % source)
                return
        else:
            source = self.input.py_as_source
            filename = "<%s>" % locate(self.input)

        # Execute the code.
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdin = StringIO.StringIO(self.input.stdin)
        sys.stdout = StringIO.StringIO()
        sys.stderr = sys.stdout
        context = self.state.get('__py__', {}).copy()
        try:
            context['__name__'] = '__main__'
            context['__file__'] = filename
            context['__pbbt__'] = self.state
            exc_info = None
            try:
                try:
                    code = compile(source, filename, 'eval')
                    is_expr = True
                except SyntaxError:
                    code = compile(source, filename, 'exec')
                    is_expr = False
                if is_expr:
                    output = eval(code, context)
                    if output is not None:
                        sys.stdout.write(repr(output)+"\n")
                else:
                    exec code in context
            except:
                exc_info = sys.exc_info()
                if self.input.except_ is not None and \
                        self.input.except_ == exc_info[0].__name__:
                    sys.stdout.write(str(exc_info[1])+"\n")
            stdout = sys.stdout.getvalue()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            if '__pbbt__' in context:
                del context['__pbbt__']
            self.state['__py__'] = context

        # Generate new output record.
        new_output = self.Output(py=self.input.py_key, stdout=stdout)

        # Complain if we got an unexpected exception or didn't get an expected
        # exception.
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
    """Executes a shell script."""

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
                hint="standard output")

    def run(self):
        # Prepare the command.
        command = self.input.sh
        if isinstance(command, str):
            try:
                command = shlex.split(command)
            except ValueError:
                # Let `Popen` complain about it.
                command = [command]
        environ = None
        if self.input.environ:
            environ = os.environ.copy()
            environ.update(self.input.environ)
        # Execute the command.
        try:
            proc = subprocess.Popen(command,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    cwd=self.input.cd,
                                    env=environ)
            stdout, stderr = proc.communicate(self.input.stdin)
        except OSError, exc:
            self.ui.literal(str(exc))
            self.ui.warning("failed to execute the process")
            return
        # Make sure `stdout` is valid UTF-8 string.
        stdout = stdout.decode('utf-8', 'replace')
        if not isinstance(stdout, str):
            stdout = stdout.encode('utf-8')
        # Complain on unexpected exit code.
        if proc.returncode != self.input.exit:
            if stdout:
                self.ui.literal(stdout)
            self.ui.warning("unexpected exit code (%s)" % proc.returncode)
            return
        # Generate new output record.
        return self.Output(sh=self.input.sh, stdout=stdout)

    def render(self, output):
        return output.stdout


@Test
class WriteToFileCase(BaseCase):
    """Creates a file with the given content."""

    class Input:
        write = Field(str,
                hint="file name")
        data = Field(str,
                hint="file content")

    def check(self):
        stream = open(self.input.write, 'w')
        stream.write(self.input.data)
        stream.close()


@Test
class ReadFromFileCase(MatchCase):
    """Reads content of a file."""

    class Input:
        read = Field(str,
                hint="file name")

    class Output:
        read = Field(str,
                hint="file name")
        data = Field(str,
                hint="file content")

    def run(self):
        if not os.path.exists(self.input.read):
            self.ui.warning("missing file %r" % self.input.read)
            return
        stream = open(self.input.read)
        data = stream.read()
        stream.close()
        return self.Output(self.input.read, data)

    def render(self, output):
        return output.data


@Test
class RemoveFileCase(BaseCase):
    """Deletes a file or a list of files."""

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
    """Creates a directory."""

    class Input:
        mkdir = Field(str,
                hint="directory name")

    def check(self):
        if not os.path.isdir(self.input.mkdir):
            os.makedirs(self.input.mkdir)


@Test
class RemoveDirectoryCase(BaseCase):
    """Deletes a directory."""

    class Input:
        rmdir = Field(str,
                hint="directory name")

    def check(self):
        if os.path.exists(self.input.rmdir):
            shutil.rmtree(self.input.rmdir)


@Test
class DoctestCase(BaseCase):
    """Runs ``doctest`` tests."""

    class Input:
        doctest = Field(str,
                hint="file pattern")

    def check(self):
        # Convert the file pattern to a list of files.
        paths = sorted(glob.glob(self.input.doctest))
        if not paths:
            self.ctl.failed("missing file %r" % self.input.doctest)
            return

        # Initialize doctest.
        import doctest
        parser = doctest.DocTestParser()
        runner = doctest.DocTestRunner(verbose=False, optionflags=0)
        report_stream = StringIO.StringIO()

        # Run all tests.
        for path in paths:
            name = os.path.basename(path)
            text = open(path).read()
            globs = { '__name__': '__main__' }
            test = parser.get_doctest(text, globs, name, path, 0)
            runner.run(test, out=report_stream.write)

        # Prepare test summary.
        old_stdout = sys.stdout
        sys.stdout = report_stream
        result = runner.summarize()
        self.stdout = old_stdout
        report = report_stream.getvalue()

        # Report failures.
        if result.failed:
            self.ctl.failed("some tests failed")
            self.ui.literal(report)
            if self.ctl.training:
                reply = self.ui.choice(None, ('', "halt"), ('c', "continue"))
                if reply == '':
                    self.ctl.halt()
            return

        self.ctl.passed()


@Test
class UnittestCase(BaseCase):
    """Runs ``unittest`` tests."""

    class Input:
        unittest = Field(str,
                hint="file pattern")

    def check(self):
        import unittest

        # Load tests.
        dirname = os.path.dirname(self.input.unittest)
        basename = os.path.basename(self.input.unittest)
        loader = unittest.TestLoader()
        test = loader.discover(dirname, basename)

        # Run tests.
        report_stream = StringIO.StringIO()
        runner = unittest.TextTestRunner(report_stream)
        result = runner.run(test)
        report = report_stream.getvalue()

        # Report failures.
        if not result.wasSuccessful():
            self.ctl.failed("some tests failed")
            self.ui.literal(report)
            if self.ctl.training:
                reply = self.ui.choice(None, ('', "halt"), ('c', "continue"))
                if reply == '':
                    self.ctl.halt()
            return

        self.ctl.passed()


@Test
class PytestCase(BaseCase):
    """Runs ``pytest`` tests."""

    class Input:
        pytest = Field(str,
                hint="file pattern")

    def check(self):
        # Check if py.test is installed.
        try:
            import pytest
        except ImportError:
            self.ctl.failed("py.test is not installed")
            return

        # Convert the file pattern to a list of files.
        paths = sorted(glob.glob(self.input.pytest))
        if not paths:
            self.ctl.failed("missing file %r" % self.input.pytest)
            return

        # Patch terminalwriter to set text width to 70.
        import py._io.terminalwriter
        old_get_terminal_width = py._io.terminalwriter.get_terminal_width
        py._io.terminalwriter.get_terminal_width = lambda: 70

        # Redirect output to StringIO and run the test suite.
        report_stream = StringIO.StringIO()
        old_stdout = sys.stdout
        sys.stdout = report_stream
        result = pytest.main(paths+['-q'])
        sys.stdout = old_stdout
        report = report_stream.getvalue()

        # Restore terminalwriter.
        py._io.terminalwriter.get_terminal_width = old_get_terminal_width

        # Report failures.
        if result != 0:
            self.ctl.failed("some tests failed")
            self.ui.literal(report)
            if self.ctl.training:
                reply = self.ui.choice(None, ('', "halt"), ('c', "continue"))
                if reply == '':
                    self.ctl.halt()
            return

        self.ctl.passed()


@Test
class CoverageCase(BaseCase):
    """Starts code coverage with ``coverage.py``."""

    class Input:
        coverage = Field(maybe(str),
                hint="configuration file")
        data_file = Field(str, default=None,
                hint="data file to use")
        auto_data = Field(bool, default=False,
                hint="save coverage data")
        timid = Field(bool, default=None,
                hint="use simpler trace function")
        branch = Field(bool, default=None,
                hint="measure branch coverage")
        source = Field(listof(str), default=None,
                hint="list of file paths or package names")
        include = Field(listof(str), default=None,
                hint="patterns for files to measure")
        omit = Field(listof(str), default=None,
                hint="patterns for files to omit")

    def check(self):
        # Check if coverage.py is installed.
        try:
            import coverage
        except ImportError:
            self.ctl.failed("coverage.py is not installed")
            return

        # Check if coverage already started.
        if '__coverage__' in self.state:
            self.ctl.failed("coverage is already started")

        # Start coverage.
        self.state['__coverage__'] = coverage.coverage(
                config_file=self.input.coverage or False,
                data_file=self.input.data_file,
                auto_data=self.input.auto_data,
                timid=self.input.timid,
                branch=self.input.branch,
                source=self.input.source,
                include=self.input.include,
                omit=self.input.omit)
        self.state['__coverage__'].start()


@Test
class CoverageCheckCase(BaseCase):
    """Report coverage results."""

    class Input:
        coverage_check = Field(float,
                hint="expected coverage in percent")

    def check(self):
        # Find coverage instance.
        coverage = self.state.get('__coverage__')
        if coverage is None:
            self.ctl.failed("coverage has not been started")
            return

        # Stop coverage.
        if coverage._started:
            coverage.stop()
        if getattr(coverage, 'auto_data', None) or \
           getattr(coverage, '_auto_data', None) or \
           getattr(coverage, '_auto_load', None) or \
           getattr(coverage, '_auto_save', None):
            coverage.save()
            coverage.combine()

        # Generate the report.
        report_stream = StringIO.StringIO()
        check = coverage.report(file=report_stream)
        report = report_stream.getvalue()

        # Display the report and complain if coverage is insufficient.
        self.ui.literal(report)
        if check < self.input.coverage_check:
            self.ctl.failed("insufficient coverage: %s (expected: %s)"
                            % (check, self.input.coverage_check))


@Test
class CoverageReportCase(BaseCase):
    """Save coverage results in HTML."""

    class Input:
        coverage_report = Field(str,
                hint="directory where to save the report")

    def check(self):
        # Find coverage instance.
        coverage = self.state.get('__coverage__')
        if coverage is None:
            self.ctl.failed("coverage has not been started")
            return

        # Stop coverage.
        if coverage._started:
            coverage.stop()
        if getattr(coverage, 'auto_data', None) or \
           getattr(coverage, '_auto_data', None) or \
           getattr(coverage, '_auto_load', None) or \
           getattr(coverage, '_auto_save', None):
            coverage.save()
            coverage.combine()

        # Save the report.
        coverage.html_report(directory=self.input.coverage_report)
        self.ui.notice("coverage report saved to %s"
                       % os.path.join(self.input.coverage_report, 'index.html'))


