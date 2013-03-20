#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


import sys


class UI(object):

    def part(self):
        raise NotImplementedError("%s.part()" % self.__class__.__name__)

    def section(self):
        raise NotImplementedError("%s.section()" % self.__class__.__name__)

    def header(self, *lines):
        raise NotImplementedError("%s.header()" % self.__class__.__name__)

    def notice(self, *lines):
        raise NotImplementedError("%s.notice()" % self.__class__.__name__)

    def literal(self, *lines):
        raise NotImplementedError("%s.literal()" % self.__class__.__name__)

    def choice(self, *choices):
        raise NotImplementedError("%s.form()" % self.__class__.__name__)


class ConsoleUI(UI):

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

    def header(self, *lines):
        for line in lines:
            self.stdout.write("  "+line+"\n")
        self.stdout.flush()

    def notice(self, *lines):
        for line in lines:
            self.stdout.write("*** "+line+"\n")
        self.stdout.flush()

    def literal(self, *lines):
        for line in lines:
            self.stdout.write("  "+line+"\n")
        self.stdout.flush()

    def choice(self, *choices):
        shortcuts = set()
        question = ""
        for shortcut, text in choices:
            shortcuts.add(shortcut)
            if not question:
                question += "Press"
            else:
                question += ","
            if shortcut:
                question += " '%s'+ENTER" % shortcut
            else:
                question += " ENTER"
            question += " to %s" % text
        self.stdout.write(">>> "+question+"\n")
        self.stdout.flush()
        line = None
        while line not in shortcuts:
            self.stdout.write("> ")
            self.stdout.flush()
            line = self.stdin.readline().strip().lower()
        return line


