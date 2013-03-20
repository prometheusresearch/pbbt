#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import TestRecord
import weakref
import re
import yaml


class Location(object):

    def __init__(self, filename, line):
        self.filename = filename
        self.line = line

    def __str__(self):
        return "\"%s\", line %s" % (self.filename, self.line)


class LocationRef(weakref.ref):

    __slots__ = ('oid', 'location')

    oid_to_ref = {}

    @staticmethod
    def cleanup(ref, oid_to_ref=oid_to_ref):
        del oid_to_ref[ref.oid]

    def __new__(cls, record, location):
        self = super(LocationRef, cls).__new__(cls, record, cls.cleanup)
        self.oid = id(record)
        self.location = location
        cls.oid_to_ref[self.oid] = self
        return self

    def __init__(self, record, location):
        super(LocationRef, self).__init__(record, location)

    @classmethod
    def locate(cls, record):
        ref = cls.oid_to_ref.get(id(record))
        if ref is not None:
            return ref.location

    @classmethod
    def mark(cls, record, location):
        cls(record, location)
        return record


# The base classes for the YAML loaders and dumpers.  When available,
# use the fast, LibYAML-based variants, if not, use the slow pure-Python
# versions.
BaseYAMLLoader = yaml.SafeLoader
if hasattr(yaml, 'CSafeLoader'):
    BaseYAMLLoader = yaml.CSafeLoader
BaseYAMLDumper = yaml.SafeDumper
if hasattr(yaml, 'CSafeDumper'):
    BaseYAMLDumper = yaml.CSafeDumper


class TestLoader(BaseYAMLLoader):

    # A pattern to match substitution variables in `!environ` nodes.
    environ_re = re.compile(r"""
        \$ \{
            (?P<name> [a-zA-Z_][0-9a-zA-Z_.-]*)
            (?: : (?P<default> [0-9A-Za-z~@#^&*_;:,./?=+-]*) )?
        \}
    """, re.X)

    def __init__(self, record_types, stream):
        super(TestLoader, self).__init__(stream)
        self.record_types = record_types

    def __call__(self):
        # That ensures the stream contains one document, parses it and
        # returns the corresponding object.
        return self.get_single_data()

    def construct_document(self, node):
        # We override this to ensure that any produced document is
        # a test record of expected type.
        data = super(TestLoader, self).construct_document(node)
        if not isinstance(data, TestRecord):
            raise yaml.constructor.ConstructorError(None, None,
                    "unexpected document type", node.start_mark)
        return data

    def construct_yaml_str(self, node):
        # Always convert a `!!str` scalar node to a byte string.
        # By default, PyYAML converts an `!!str`` node containing non-ASCII
        # characters to a Unicode string.
        value = self.construct_scalar(node)
        value = value.encode('utf-8')
        return value

    def construct_yaml_map(self, node):
        # Detect if a node represent test data and convert it to a test record.

        # We assume that the node represents a test record if it contains
        # all mandatory keys of the record class.  Otherwise, we assume it
        # is a regular dictionary.
        #
        # It would be preferable to perform this detection on the tag
        # resolution phase.  However this phase does not give us access
        # to the mapping keys, so we have no choice but do it during the
        # construction phase.

        # Check if we got a mapping node.
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None,
                    "expected a mapping node, but found %s" % node.id,
                    node.start_mark)

        # Convert the key and the value nodes.
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError, exc:
                raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        "found unacceptable key (%s)" % exc,
                        key_node.start_mark)
            value = self.construct_object(value_node, deep=True)
            mapping[key] = value

        # Find a record class such that the node contains all
        # the mandatory record fields.
        detected_record_type = None
        for record_type in self.record_types:
            if record_type.__detects__(mapping):
                detected_record_type = record_type
                break

        # If we can't find a suitable record class, it must be a regular
        # dictionary.
        if detected_record_type is None:
            return mapping

        # Check that the node does not contain any keys other than
        # the record fields.
        try:
            record = detected_record_type.__load__(mapping)
        except ValueError, exc:
            raise yaml.constructor.ConstructorError(None, None,
                    str(exc), node.start_mark)

        # Record where the node was found.
        location = Location(node.start_mark.name, node.start_mark.line+1)
        LocationRef.mark(record, location)

        return record

    def construct_environ(self, node):
        # Substitute environment variables in `!environ` scalars.

        def replace(match):
            # Substitute environment variables with values.
            name = match.group('name')
            default = match.group('default') or ''
            value = os.environ.get(name, default)
            if not self.environ_value_regexp.match(value):
                raise yaml.constructor.ConstructorError(None, None,
                        "invalid value of environment variable %s: %r"
                        % (name, value), node.start_mark)
            return value

        # Get the scalar value and replace all ${...} occurences with
        # values of respective environment variables.
        value = self.construct_scalar(node)
        value = value.encode('utf-8')
        value = self.environ_regexp.sub(replace, value)

        # Blank values are returned as `None`.
        if not value:
            return None
        return value


# Register custom constructors for `!!str``, `!!map`` and ``!environ``.
TestLoader.add_constructor(
        u'tag:yaml.org,2002:str',
        TestLoader.construct_yaml_str)
TestLoader.add_constructor(
        u'tag:yaml.org,2002:map',
        TestLoader.construct_yaml_map)
TestLoader.add_constructor(
        u'!environ',
        TestLoader.construct_environ)


# Register a resolver for ``!environ``.
TestLoader.add_implicit_resolver(
        u'!environ', TestLoader.environ_re, [u'$'])


class TestDumper(BaseYAMLDumper):

    def __init__(self, stream, **keywords):
        super(TestDumper, self).__init__(stream, **keywords)
        # Check if the PyYAML version is suitable for dumping.
        self.check_version()

    def check_version(self):
        # We require PyYAML >= 3.07 built with LibYAML >= 0.1.2 to dump
        # YAML data.  Other versions may produce slightly different output.
        # Since the YAML files may be kept in a VCS repository, we don't
        # want minor formatting changes generate unnecessarily large diffs.
        try:
            pyyaml_version = yaml.__version__
        except AttributeError:
            pyyaml_version = '3.05'
        try:
            import _yaml
            libyaml_version = _yaml.get_version_string()
        except ImportError:
            libyaml_version = None
        if pyyaml_version < '3.07':
            raise ScriptError("PyYAML >= 3.07 is required"
                              " to dump test output")
        if libyaml_version is None:
            raise ScriptError("PyYAML built with LibYAML bindings"
                              " is required to dump test output")
        if libyaml_version < '0.1.2':
            raise ScriptError("LibYAML >= 0.1.2 is required"
                              " to dump test output")

    def __call__(self, data):
        """
        Dumps the data to the YAML stream.
        """
        self.open()
        self.represent(data)
        self.close()

    def represent_str(self, data):
        # Serialize a string.  We override the default string serializer
        # to use the literal block style for multi-line strings.
        tag = None
        style = None
        if data.endswith('\n'):
            style = '|'
        try:
            data = data.decode('utf-8')
            tag = u'tag:yaml.org,2002:str'
        except UnicodeDecodeError:
            data = data.encode('base64')
            tag = u'tag:yaml.org,2002:binary'
            style = '|'
        return self.represent_scalar(tag, data, style=style)

    def represent_record(self, data):
        # Extract the fields skipping those with the default value.
        mapping = data.__dump__()
        # Generate a mapping node.
        return self.represent_mapping(u'tag:yaml.org,2002:map', mapping,
                                      flow_style=False)


TestDumper.add_representer(
        str, TestDumper.represent_str)
TestDumper.add_multi_representer(
        TestRecord, TestDumper.represent_record)


locate = LocationRef.locate


def load(filename, record_types):
    stream = open(filename, 'r')
    loader = TestLoader(record_types, stream)
    return loader()


def dump(filename, record):
    stream = open(filename, 'w')
    dumper = TestDumper(stream)
    return dumper(record)


