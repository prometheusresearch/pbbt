#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


import re
import argparse
import os, os.path
from . import test


def variable(text):
    if '=' in text:
        name, value = text.split('=')
        if not value:
            value = None
    else:
        name = text
        value = True
    if not re.match(r'^[A-Za-z_][0-9A-Za-z_]*$', name):
        raise ValueError("invalid variable name: %r" % name)
    return (name, value)


def module(text):
    if os.path.isfile(text):
        return text
    if not re.match(r'^[A-Za-z_][0-9A-Za-z_]*'
                    r'(?:\.[A-Za-z_][0-9A-Za-z_]*)*', text):
        raise ValueError("invalid module or file name: %r" % text)


parser = argparse.ArgumentParser(
        description="Run tests.")
parser.add_argument('-q', '--quiet',
        action='store_true',
        help="display warnings and errors only")
parser.add_argument('-T', '--train',
        action='store_true',
        help="run tests in the training mode")
parser.add_argument('-P', '--purge',
        action='store_true',
        help="purge stale output data")
parser.add_argument('-M', '--max-errors',
        metavar="N", type=int, default=0,
        help="halt after N errors")
parser.add_argument('-D', '--define',
        metavar="VAR", action='append', default=[], type=variable,
        help="set a conditional variable")
parser.add_argument('-E', '--extend',
        metavar="MOD", default=[], type=module,
        action='append',
        help="load an extension")
parser.add_argument('-S', '--suite',
        metavar="ID", action='append', default=[],
        help="run a specific test suite")
parser.add_argument('input',
        metavar="INPUT",
        help="file with input data")
parser.add_argument('output',
        metavar="OUTPUT", nargs='?',
        help="file with output data")


def main():
    args = parser.parse_args()
    for path in args.extend:
        if os.path.isfile(path):
            exec open(path) in {}
        else:
            __import__(path)
    input = args.input
    output = args.output
    substitutes = dict(args.define)
    paths = args.suite or None
    training = args.train
    purging = args.purge
    max_errors = args.max_errors
    quiet = args.quiet
    return test(input, output,
                substitutes=substitutes,
                paths=paths,
                training=training,
                purging=purging,
                max_errors=max_errors,
                quiet=quiet)


