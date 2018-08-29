#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .ctl import Control
import re
import argparse
import os, os.path
import ConfigParser
import yaml


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
    return text


DESCRIPTION = """\
pbbt is a pluggable black-box testing harness;
for more information, see:

    http://bitbucket.org/prometheus/pbbt
"""


# Command-line parameters for `pbbt` script.
parser = argparse.ArgumentParser(
        description=DESCRIPTION)
parser.add_argument('-q', '--quiet',
        default=None,
        action='store_true',
        help="display warnings and errors only")
parser.add_argument('-T', '--train',
        default=None,
        action='store_true',
        help="run tests in the training mode")
parser.add_argument('-P', '--purge',
        default=None,
        action='store_true',
        help="purge stale output data")
parser.add_argument('-M', '--max-errors',
        type=int,
        default=None,
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
        nargs='?',
        metavar="INPUT",
        help="file with input data")
parser.add_argument('output',
        nargs='?',
        metavar="OUTPUT",
        help="file with output data")


def main():
    """Entry point for `pbbt` script."""
    # Default configuration.
    extend = []
    input = None
    output = None
    variables = {}
    targets = None
    training = False
    purging = False
    max_errors = 0
    quiet = False

    # Load configuration from setup.cfg.
    if os.path.exists('setup.cfg'):
        setup_cfg = ConfigParser.SafeConfigParser()
        setup_cfg.read('setup.cfg')
        if setup_cfg.has_option('pbbt', 'extend'):
            lines = setup_cfg.get('pbbt', 'extend')
            extend.extend(module(line) for line in lines.split())
        if setup_cfg.has_option('pbbt', 'input'):
            input = setup_cfg.get('pbbt', 'input')
        if setup_cfg.has_option('pbbt', 'output'):
            output = setup_cfg.get('pbbt', 'output')
        if setup_cfg.has_option('pbbt', 'define'):
            lines = setup_cfg.get('pbbt', 'define')
            variables.update(variable(line) for line in lines.split())
        if setup_cfg.has_option('pbbt', 'suite'):
            lines = setup_cfg.get('pbbt', 'suite')
            targets = lines.split()
        if setup_cfg.has_option('pbbt', 'train'):
            training = setup_cfg.getboolean('pbbt', 'train')
        if setup_cfg.has_option('pbbt', 'purge'):
            purging = setup_cfg.getboolean('pbbt', 'purge')
        if setup_cfg.has_option('pbbt', 'max_errors'):
            max_errors = setup_cfg.getint('pbbt', 'max_errors')
        if setup_cfg.has_option('pbbt', 'quiet'):
            quiet = setup_cfg.getboolean('pbbt', 'quiet')

    # Load configuration from pbbt.yaml.
    if os.path.exists('pbbt.yaml'):
        try:
            pbbt_cfg = yaml.safe_load(open('pbbt.yaml'))
        except yaml.YAMLError, error:
            print str(error)
            return "pbbt: error: ill-formed configuration file: pbbt.yaml"
        if pbbt_cfg is None:
            pbbt_cfg = {}
        if not isinstance(pbbt_cfg, dict):
            return "pbbt: error: ill-formed configuration file: pbbt.yaml"
        if 'extend' in pbbt_cfg:
            extend.extend(pbbt_cfg['extend'])
        if 'input' in pbbt_cfg:
            input = pbbt_cfg['input']
        if 'output' in pbbt_cfg:
            output = pbbt_cfg['output']
        if 'define' in pbbt_cfg:
            variables.update(pbbt_cfg['define'])
        if 'suite' in pbbt_cfg:
            if isinstance(pbbt_cfg['suite'], str):
                targets = pbbt_cfg['suite'].split()
            else:
                targets = pbbt_cfg['suite']
        if 'train' in pbbt_cfg:
            training = pbbt_cfg['train']
        if 'purge' in pbbt_cfg:
            purging = pbbt_cfg['purge']
        if 'max-errors' in pbbt_cfg:
            max_errors = pbbt_cfg['max-errors']
        if 'quiet' in pbbt_cfg:
            quiet = pbbt_cfg['quiet']

    # Parse command-line parameters.
    args = parser.parse_args()
    extend.extend(args.extend)
    if args.input:
        input = args.input
    if args.output:
        output = args.output
    variables.update(args.define)
    if args.suite:
        targets = args.suite
    if args.train is not None:
        training = args.train
    if args.purge is not None:
        purging = args.purge
    if args.max_errors is not None:
        max_errors = args.max_errors
    if args.quiet is not None:
        quiet = args.quiet

    # Check if input file was provided.
    if input is None:
        parser.print_help()
        return "pbbt: error: input file is not specified"

    # Load extensions.
    for path in extend:
        if os.path.isfile(path):
            exec open(path).read() in {}
        else:
            __import__(path)

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


