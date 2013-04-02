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


class TestRecord(object):
    """Base class for test input/output data."""

    __slots__ = ('__weakref__',)
    # Test type object which owns the record type.
    __owner__ = None
    # List of the record fields.
    __fields__ = ()

    class __metaclass__(type):

        def __new__(mcls, name, bases, members):
            if '__fields__' not in members:
                fields = set()
                for base in bases:
                    if '__fields__' in base.__dict__:
                        fields.update(base.__fields__)
                keys = set(field.key for field in fields)
                for attr in sorted(members):
                    dsc = members[attr]
                    if not isinstance(dsc, test_field):
                        continue
                    del members[attr]
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
                    fields.add(field)
                fields = sorted(fields, key=(lambda f: f.order))
                members['__fields__'] = fields
                members['__slots__'] = tuple(field.attr for field in fields)
            return type.__new__(mcls, name, bases, members)

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


def test_type(cls):
    """Registers a test type."""
    assert isinstance(cls, types.TypeType), "a test type must be a class"

    for name in ['Input', 'Output']:
        record_bases = [TestRecord]
        for base in reversed(cls.__mro__):
            if name not in base.__dict__:
                continue
            record_def = base.__dict__[name]
            if isinstance(record_def, type) and issubclass(record_def, TestRecord):
                record_bases.insert(0, record_def)
                continue
            record_name = "%s.%s" % (base.__name__, name)
            record_members = record_def.__dict__.copy()
            record_members['__owner__'] = base
            record_type = type(record_name, tuple(record_bases), record_members)
            setattr(base, name, record_type)
            record_bases.insert(0, record_type)
    registry.case_types.append(cls)
    if 'Input' in cls.__dict__:
        registry.input_types.append(cls.Input)
    if 'Output' in cls.__dict__:
        registry.output_types.append(cls.Output)

    return cls


