#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


import sys


class UI(object):
    """Provides user interaction services."""

    def part(self):
        """Starts a new section."""
        raise NotImplementedError("%s.part()" % self.__class__.__name__)

    def section(self):
        """Starts a subsection."""
        raise NotImplementedError("%s.section()" % self.__class__.__name__)

    def header(self, text):
        """Shows a section header."""
        raise NotImplementedError("%s.header()" % self.__class__.__name__)

    def notice(self, text):
        """Shows a notice.""" 
        raise NotImplementedError("%s.notice()" % self.__class__.__name__)

    def warning(self, text):
        """Shows a warning."""
        raise NotImplementedError("%s.warning()" % self.__class__.__name__)

    def error(self, text):
        """Shows an error."""
        raise NotImplementedError("%s.error()" % self.__class__.__name__)

    def literal(self, text):
        """Shows a literal text."""
        raise NotImplementedError("%s.literal()" % self.__class__.__name__)

    def choice(self, text, *choices):
        """Asks a single-choice question."""
        raise NotImplementedError("%s.choice()" % self.__class__.__name__)


class ConsoleUI(UI):
    """Implements :class:`UI` for console."""

    def __init__(self, stdin=None, stdout=None, stderr=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr

    def part(self):
        self.stdout.write("="*72+"\n")
        self.stdout.flush()

    def section(self):
        self.stdout.write("-"*72+"\n")
        self.stdout.flush()

    def header(self, text):
        for line in text.splitlines():
            self.stdout.write("  "+line+"\n")
        self.stdout.flush()

    def notice(self, text):
        for line in text.splitlines():
            self.stdout.write("* "+line+"\n")
        self.stdout.flush()

    def warning(self, text):
        for line in text.splitlines():
            self.stdout.write("* "+line+"\n")
        self.stdout.flush()

    def error(self, text):
        for line in text.splitlines():
            self.stdout.write("! "+line+"\n")
        self.stdout.flush()

    def literal(self, text):
        for line in text.splitlines():
            self.stdout.write("  "+line+"\n")
        self.stdout.flush()

    def choice(self, text, *choices):
        if text:
            for line in text.splitlines():
                self.stdout.write("> "+line+"\n")
        shortcuts = set()
        question = ""
        for shortcut, choice in choices:
            shortcuts.add(shortcut)
            if not question:
                question += "Press"
            else:
                question += ","
            if shortcut:
                question += " '%s'+ENTER" % shortcut
            else:
                question += " ENTER"
            question += " to %s" % choice
        self.stdout.write("> "+question+"\n")
        self.stdout.flush()
        line = None
        while line not in shortcuts:
            self.stdout.write("> ")
            self.stdout.flush()
            line = self.stdin.readline().strip().lower()
        return line


class SilentUI(UI):
    """Implements :class:`UI` for use with ``--quiet`` option."""

    def __init__(self, backend):
        # The backend UI.
        self.backend = backend
        self.queue = []
        self.visible = False

    def restart(self):
        # Flush the queue.
        del self.queue[:]
        self.visible = False

    def force(self):
        # Execute the queued actions.
        self.visible = True
        self.process()

    def process(self):
        if self.visible:
            for method, args in self.queue:
                method(*args)
            del self.queue[:]

    def part(self):
        self.restart()
        self.queue.append((self.backend.part, ()))
        self.process()

    def section(self):
        self.restart()
        self.queue.append((self.backend.section, ()))
        self.process()

    def header(self, text):
        self.queue.append((self.backend.header, (text,)))
        self.process()

    def notice(self, text):
        self.queue.append((self.backend.notice, (text,)))
        self.process()

    def warning(self, text):
        self.queue.append((self.backend.warning, (text,)))
        self.force()

    def error(self, text):
        self.queue.append((self.backend.error, (text,)))
        self.force()

    def literal(self, text):
        self.queue.append((self.backend.literal, (text,)))
        self.process()

    def choice(self, text, *choices):
        self.force()
        return self.backend.choice(text, *choices)


