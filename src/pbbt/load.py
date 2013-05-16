#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from .core import Record
from .check import listof
import re
import os
import weakref
import yaml


class Location(object):
    """Position of a record in the YAML document."""

    def __init__(self, filename, line):
        self.filename = filename
        self.line = line

    def __str__(self):
        return "\"%s\", line %s" % (self.filename, self.line)


class LocationRef(weakref.ref):
    # Weak reference from a record to its location.

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
        super(LocationRef, self).__init__(record, self.cleanup)

    @classmethod
    def locate(cls, record):
        """Finds the record location."""
        ref = cls.oid_to_ref.get(id(record))
        if ref is not None:
            return ref.location

    @classmethod
    def set_location(cls, record, location):
        # Associates a record with its location.
        cls(record, location)
        return record


set_location = LocationRef.set_location
locate = LocationRef.locate


# Use fast LibYAML-based loader and serializer when available.
try:
    BaseYAMLLoader = yaml.CSafeLoader
    BaseYAMLDumper = yaml.CSafeDumper
except AttributeError:
    BaseYAMLLoader = yaml.SafeLoader
    BaseYAMLDumper = yaml.SafeDumper


class TestLoader(BaseYAMLLoader):
    # Reads test input/output data from a file.

    # A pattern to match `!substitute` nodes.
    substitute_re = re.compile(r"""
        \$ \{
            (?P<name> [a-zA-Z_][0-9a-zA-Z_.-]*)
            (?: : (?P<default> [0-9A-Za-z~@#^&*_;:,./?=+-]*) )?
        \}
    """, re.X)

    def __init__(self, record_types, substitutes, stream):
        super(TestLoader, self).__init__(stream)
        # List of supported record types.
        self.record_types = record_types
        # Maps names to substitution values.
        self.substitutes = substitutes
        # Indicates that the next node is a test record.
        self.expect_record = None
        # Indicates that the next node is a sequence of test records.
        self.expect_record_list = None

    def __call__(self):
        # Make sure the YAML stream contains one test record and returns it.
        self.expect_record = True
        self.expect_record_list = False
        return self.get_single_data()

    def construct_object(self, node, deep=False):
        # Generate a nicer error message when a test record could not be found.
        if self.expect_record:
            if not (isinstance(node, yaml.MappingNode) and
                    node.tag == u"tag:yaml.org,2002:map"):
                raise yaml.constructor.ConstructorError(None, None,
                        "expected a test record", node.start_mark)
        if self.expect_record_list:
            if not (isinstance(node, yaml.SequenceNode) and
                    node.tag == u"tag:yaml.org,2002:seq"):
                raise yaml.constructor.ConstructorError(None, None,
                        "expected a sequence of test records", node.start_mark)

        data = super(TestLoader, self).construct_object(node, deep=deep)

        if self.expect_record:
            if not isinstance(data, Record):
                raise yaml.constructor.ConstructorError(None, None,
                        "expected a test record", node.start_mark)

        return data

    def construct_yaml_str(self, node):
        # Always return a `!!str`` node as a native string.
        value = self.construct_scalar(node)
        try:
            return str(value)
        except UnicodeEncodeError:
            return value.encode('utf-8')

    def construct_yaml_seq(self, node):
        if not self.expect_record_list:
            return super(TestLoader, self).construct_yaml_seq(node)

        # Construct a list of test records.
        if not (isinstance(node, yaml.SequenceNode) and
                node.tag == u"tag:yaml.org,2002:seq"):
            raise yaml.constructor.ConstructorError(None, None,
                    "expected a sequence of test records", node.start_mark)
        self.expect_record = True
        self.expect_record_list = False
        data = []
        for item in node.value:
            data.append(self.construct_object(item, deep=True))
        self.expect_record = False
        self.expect_record_list = True
        return data

    def construct_yaml_map(self, node):
        if not self.expect_record:
            return super(TestLoader, self).construct_yaml_map(node)

        # Construct a test record.

        # Check if we got a correct node type.
        if not (isinstance(node, yaml.MappingNode) and
                node.tag == u"tag:yaml.org,2002:map"):
            raise yaml.constructor.ConstructorError(None, None,
                    "expected a test record", node.start_mark)

        # Construct mapping keys.
        keys = []
        current_expect_record = self.expect_record
        self.expect_record = False
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                        "while constructing a test record", node.start_mark,
                        "found invalid field name", key_node.start_mark)
            keys.append(key)
        self.expect_record = current_expect_record

        # Find a record class matching the set of keys.
        detected_record_type = None
        for record_type in self.record_types:
            if record_type.__recognizes__(set(keys)):
                detected_record_type = record_type
                break
        if detected_record_type is None:
            if not keys:
                raise yaml.constructor.ConstructorError(None, None,
                        "expected a test record", node.start_mark)
            field_list = ", ".join(repr(key) for key in keys)
            if len(keys) == 1:
                raise yaml.constructor.ConstructorError(None, None,
                        "cannot find a test type with field %s" % field_list,
                        node.start_mark)
            else:
                raise yaml.constructor.ConstructorError(None, None,
                        "cannot find a test type with fields %s" % field_list,
                        node.start_mark)

        # Construct the record values; a hack to parse nested records.
        mapping = {}
        current_expect_record = self.expect_record
        for key, (key_node, value_node) in zip(keys, node.value):
            self.expect_record = False
            self.expect_record_list = False
            field = next((field for field in detected_record_type.__fields__
                                if field.key == key), None)
            if field is not None:
                if field.check == Record:
                    self.expect_record = True
                elif (isinstance(field.check, listof) and
                        field.check.item_check == Record):
                    self.expect_record_list = True
            value = self.construct_object(value_node, deep=True)
            mapping[key] = value
        self.expect_record = current_expect_record
        self.expect_record_list = False

        # Generate a record object.
        try:
            record = detected_record_type.__load__(mapping)
        except ValueError, exc:
            raise yaml.constructor.ConstructorError(None, None,
                    str(exc), node.start_mark)

        # Associate the record object with its position in the YAML stream.
        location = Location(node.start_mark.name, node.start_mark.line+1)
        set_location(record, location)

        return record

    def construct_substitute(self, node):
        # Process `${...}` scalars.
        value = self.construct_scalar(node)
        try:
            value = str(value)
        except UnicodeEncodeError:
            value = value.encode('utf-8')
        match = self.substitute_re.match(value)
        if match is None:
            raise yaml.constructor.ConstructorError(None, None,
                    "invalid substitution", node.start_mark)
        name = match.group('name')
        default = match.group('default')
        return self.substitutes.get(name, default)


# Register custom constructors.
TestLoader.add_constructor(
        u'tag:yaml.org,2002:str', TestLoader.construct_yaml_str)
TestLoader.add_constructor(
        u'tag:yaml.org,2002:seq', TestLoader.construct_yaml_seq)
TestLoader.add_constructor(
        u'tag:yaml.org,2002:map', TestLoader.construct_yaml_map)
TestLoader.add_constructor(
        u'!substitute', TestLoader.construct_substitute)
# Register a resolver for ``!substitute``.
TestLoader.add_implicit_resolver(
        u'!substitute', TestLoader.substitute_re, [u'$'])


class TestDumper(BaseYAMLDumper):
    # Saves test input/output data to a file.

    def __init__(self, stream, **keywords):
        if 'explicit_start' not in keywords:
            keywords['explicit_start'] = True
        super(TestDumper, self).__init__(stream, **keywords)
        self.check_version()

    def check_version(self):
        # Different versions of PyYAML may produce slightly different output.
        # Since it causes spurious diffs when test output is stored in VCS,
        # we require a specific version of PyYAML/LibYAML.
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
            raise ImportError("PyYAML >= 3.07 is required"
                              " to dump test output")
        if libyaml_version is None:
            raise ImportError("PyYAML built with LibYAML bindings"
                              " is required to dump test output")
        if libyaml_version < '0.1.2':
            raise ImportError("LibYAML >= 0.1.2 is required"
                              " to dump test output")

    def __call__(self, data):
        self.open()
        self.represent(data)
        self.close()

    def represent_str(self, data):
        # Overriden to force literal block style for multi-line strings.
        style = None
        if data.endswith('\n'):
            style = '|'
        tag = u'tag:yaml.org,2002:str'
        if not isinstance(data, unicode):
            try:
                data = data.decode('utf-8')
            except UnicodeDecodeError:
                data = data.encode('base64')
                tag = u'tag:yaml.org,2002:binary'
                style = '|'
        return self.represent_scalar(tag, data, style=style)

    def represent_record(self, data):
        mapping = data.__dump__()
        return self.represent_mapping(u'tag:yaml.org,2002:map', mapping,
                                      flow_style=False)


# Register custom serializers.
TestDumper.add_representer(
        str, TestDumper.represent_str)
TestDumper.add_multi_representer(
        Record, TestDumper.represent_record)
# Register a resolver for ``!substitute``.
TestDumper.add_implicit_resolver(
        u'!substitute', TestLoader.substitute_re, [u'$'])


def load(filename, record_types, substitutes={}):
    # Loads test input/output data from a file.
    stream = open(filename, 'r')
    loader = TestLoader(record_types, substitutes, stream)
    return loader()


def dump(filename, record):
    # Saves test output data to a file.
    stream = open(filename, 'w')
    stream.write("#\n")
    stream.write("# This file contains expected test output data"
                 " generated by PBBT.\n")
    stream.write("#\n")
    dumper = TestDumper(stream)
    return dumper(record)


