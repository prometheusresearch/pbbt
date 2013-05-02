#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .ctl import Control
import re
import argparse
import os, os.path


def variable(text):
    # Checks if `text` looks like `VAR` or `VAR=VALUE`; returns `(var, value)`.
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
    # Checks is `text` is a file name or a Python module.
    if os.path.isfile(text):
        return text
    if not re.match(r'^[A-Za-z_][0-9A-Za-z_]*'
                    r'(?:\.[A-Za-z_][0-9A-Za-z_]*)*', text):
        raise ValueError("invalid module or file name: %r" % text)


DESCRIPTION = """\
pbbt is a pluggable black-box testing harness;
for more information, see:

    http://bitbucket.org/prometheus/pbbt
"""


# Command-line parameters for `pbbt` script.
parser = argparse.ArgumentParser(
        description=DESCRIPTION)
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
        type=int,
        default=0,
        metavar="N",
        help="halt after N errors")
parser.add_argument('-D', '--define',
        action='append',
        type=variable,
        default=[],
        metavar="VAR",
        help="set a conditional variable")
parser.add_argument('-E', '--extend',
        action='append',
        type=module,
        default=[],
        metavar="MOD",
        help="load an extension")
parser.add_argument('-S', '--suite',
        action='append',
        default=[],
        metavar="ID",
        help="run a specific test suite")
parser.add_argument('input',
        metavar="INPUT",
        help="file with input data")
parser.add_argument('output',
        nargs='?',
        metavar="OUTPUT",
        help="file with output data")


def main():
    """Entry point for `pbbt` script."""
    # Parse command-line parameters.
    args = parser.parse_args()
    # Load extensions.
    for path in args.extend:
        if os.path.isfile(path):
            exec open(path) in {}
        else:
            __import__(path)
    # Prepare configuration.
    input = args.input
    output = args.output
    variables = dict(args.define)
    targets = args.suite or None
    training = args.train
    purging = args.purge
    max_errors = args.max_errors
    quiet = args.quiet
    # Execute the tests.
    return run(input, output,
               variables=variables,
               targets=targets,
               training=training,
               purging=purging,
               max_errors=max_errors,
               quiet=quiet)


def run(input, output=None, **configuration):
    """Runs a collection of tests."""
    ctl = Control(**configuration)
    return ctl(input, output)


