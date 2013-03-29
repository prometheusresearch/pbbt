#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


import itertools
import types


class registry:

    case_types = []
    input_types = []
    output_types = []


class TestRecord(object):
    """Base class for test input/output data."""

    __slots__ = ('__weakref__',)
    # Test type object which owns the record type.
    __owner__ = None
    # List of the record fields.
    __fields__ = ()

    @classmethod
    def __make__(cls, owner, name, bases, fields, members):
        """Generates a record type with the given fields."""
        name = "%s.%s" % (owner.__name__, name)
        bases = tuple(bases)+(cls,)
        members = members.copy()
        members['__slots__'] = tuple(field.attr for field in fields)
        members['__owner__'] = owner
        members['__fields__'] = fields
        return type(name, bases, members)

    @classmethod
    def __recognizes__(cls, keys):
        """Checks if the set of keys contains all required record fields."""
        if not any(field.required for field in cls.__fields__):
            return False
        return all(field.key in keys for field in cls.__fields__
                                     if field.required)

    @classmethod
    def __load__(cls, mapping):
        """Generates a record from a dictionary of field keys and values."""
        args = []
        for field in cls.__fields__:
            if field.key not in mapping:
                if field.required:
                    raise ValueError("missing field %r" % field.key)
                arg = field.default
            else:
                arg = mapping.pop(field.key)
                if field.check is not None and not isinstance(arg, field.check):
                    raise ValueError("invalid field %r: expected %s, got %r"
                                     % (field.key, field.check.__name__, arg))
            args.append(arg)
        if mapping:
            key = sorted(mapping)[0]
            raise ValueError("unknown field %r" % key)
        return cls(*args)

    def __dump__(self):
        """Generates a list of field keys and values."""
        mapping = []
        for field in self.__fields__:
            arg = getattr(self, field.attr)
            if arg == field.default and not field.required:
                continue
            mapping.append((field.key, arg))
        return mapping

    def __complements__(self, other):
        """
        Checks if two records are complementary input and output data
        for the same test case.
        """
        # Check if the records belong to the same test type and are of
        # complementary types (input and output or vice versa).
        if not (self.__owner__ is other.__owner__ and
                self.__class__ is not other.__class__):
            return False

        # Find a common mandatory field.
        match_field = None
        other_attrs = set(field.attr for field in other.__fields__
                                     if field.required)
        for field in self.__fields__:
            if field.required and field.attr in other_attrs:
                match_field = field
                break
        if match_field is None:
            return False
        # Check if the field values coincide.
        value = getattr(self, match_field.attr)
        other_value = getattr(other, match_field.attr)
        return (value == other_value)

    def __init__(self, *args, **kwds):
        if kwds:
            args_tail = []
            for field in self.__fields__[len(args):]:
                if field.attr not in kwds:
                    if field.required:
                        raise TypeError("missing field %r" % field.attr)
                    else:
                        args_tail.append(field.default)
                else:
                    args_tail.append(kwds.pop(field.attr))
            if kwds:
                attr = sorted(kwds)[0]
                if any(field.attr == attr for field in self.__fields__):
                    raise TypeError("duplicate field %r" % attr)
                else:
                    raise TypeError("unknown field %r" % attr)
            args = args + tuple(args_tail)
        if len(args) != len(self.__fields__):
            raise TypeError("expected %d arguments, got %d"
                            % (len(self.__fields__), len(args)))
        for arg, field in zip(args, self.__fields__):
            setattr(self, field.attr, arg)

    def __clone__(self, **kwds):
        # Makes a copy with new values for the given fields.
        if not kwds:
            return self
        args = []
        for field in self.__fields__:
            if field.attr not in kwds:
                arg = getattr(self, field.attr)
            else:
                arg = kwds.pop(field.attr)
            args.append(arg)
        if kwds:
            attr = sorted(kwds)[0]
            raise TypeError("unknown field %r" % attr)
        return self.__class__(*args)

    def __iter__(self):
        for field in self.__fields__:
            yield getattr(self, field.attr)

    def __hash__(self):
        return hash(tuple(self))

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                tuple(self) == tuple(other))

    def __ne__(self, other):
        return (self.__class__ is not other.__class__ or
                tuple(self) != tuple(other))

    def __str__(self):
        # Generates string representation from the first mandatory field.
        title_field = None
        for field in self.__fields__:
            if field.required:
                title_field = field
                break
        if title_field is None:
            return repr(self)
        value = str(getattr(self, title_field.attr))
        return "%s: %s" % (title_field.key.upper(), value)

    def __repr__(self):
        # `<name>(<field>=<value>, ...)`
        return ("%s(%s)" %
                (self.__class__.__name__,
                 ", ".join("%s=%r" % (field.attr, value)
                           for field, value in zip(self.__fields__, self)
                           if value != field.default)))


class TestFieldSpec(object):
    """Record field specification."""

    def __init__(self, attr, key, check=None, default=None,
                 order=0, required=False, hint=None):
        # Attribute name (for use in Python code).
        self.attr = attr
        # Key name (for use in YAML).
        self.key = key
        # Expected type.
        self.check = check
        # Default value.
        self.default = default
        # Relative order.
        self.order = order
        # Mandatory or not.
        self.required = required
        # One line description.
        self.hint = hint


class test_field(object):
    """Record field descriptor."""

    CTR = itertools.count(1)
    REQ = object()

    def __init__(self, check=None, default=REQ, order=None, hint=None):
        # Expected type.
        self.check = check
        # Default value or mandatory.
        self.default = default
        # Relative position.
        self.order = order or next(self.CTR)
        # One line description.
        self.hint = hint

    def __get__(self, instance, owner):
        if instance is None:
            return self
        raise AttributeError("unset test field")


def test_type(cls):
    """Registers a test type."""
    assert isinstance(cls, types.TypeType), "a test type must be a class"

    # Definitions from `Input` and `Output` declarations.
    input_members = {}
    output_members = {}
    input_bases = []
    output_bases = []
    for base in reversed(cls.__mro__):
        base_input = base.__dict__.get('Input')
        base_output = base.__dict__.get('Output')
        if base_input:
            if isinstance(base_input, type) \
                    and issubclass(base_input, TestRecord):
                input_bases.insert(0, base_input)
            input_members.update(base_input.__dict__)
        if base_output:
            if isinstance(base_output, type) \
                    and issubclass(base_output, TestRecord):
                output_bases.insert(0, base_output)
            output_members.update(base_output.__dict__)

    # Field names and definitions.
    input_attrs = []
    output_attrs = []
    for members, attrs in [(input_members, input_attrs),
                           (output_members, output_attrs)]:
        for attr in sorted(members):
            value = members[attr]
            if isinstance(value, test_field):
                attrs.append((attr, value))
                del members[attr]
    input_attrs.sort()
    output_attrs.sort()

    # Field specifications.
    input_fields = []
    output_fields = []
    for bases, attrs, fields in [(input_bases, input_attrs, input_fields),
                                 (output_bases, output_attrs, output_fields)]:
        for base in bases:
            for field in base.__fields__:
                if field not in fields:
                    fields.append(field)
        keys = set()
        for attr, dsc in attrs:
            key = attr
            if (key.endswith('_') and
                    not (key.startswith('_') or key.endswith('__'))):
                key = key[:-1]
            key = key.replace('_', '-')
            assert key not in keys, \
                    "duplicate field %r" % key
            keys.add(key)
            check = dsc.check
            default = dsc.default
            order = dsc.order
            required = False
            if default is dsc.REQ:
                required = True
                default = None
            hint = dsc.hint
            field = TestFieldSpec(attr, key, check, default,
                                  order=order, required=required, hint=hint)
            fields.append(field)
        fields.sort(key=(lambda f: f.order))

    # Register the test and generate record types.
    cls.Input = None
    cls.Output = None
    if input_fields:
        cls.Input = TestRecord.__make__(cls, 'Input', input_bases,
                                        input_fields, input_members)
        registry.input_types.append(cls.Input)
    if output_fields:
        cls.Output = TestRecord.__make__(cls, 'Output', output_bases,
                                         output_fields, output_members)
        registry.output_types.append(cls.Output)
    registry.case_types.append(cls)

    return cls


