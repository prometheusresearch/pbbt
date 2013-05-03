#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


import itertools
import types


class registry:
    # Stores registered test types and respective record types.

    case_types = []
    input_types = []
    output_types = []


class FieldSpec(object):
    # Record field specification.

    def __init__(self, attr, key, check=None, default=None,
                 order=0, required=False, hint=None):
        self.attr = attr            # attribute name (for Python code)
        self.key = key              # key name (for YAML documents)
        self.check = check          # expected type
        self.default = default      # default value
        self.order = order          # relative order
        self.required = required    # mandatory or not
        self.hint = hint            # one line description

    def __repr__(self):
        return "%s(attr=%r, key=%r, check=%r, default=%r," \
               " order=%r, required=%r, hint=%r)" \
                % (self.__class__.__name__,
                   self.attr, self.key, self.check, self.default,
                   self.order, self.required, self.hint)


class Field(object):
    """Record field descriptor."""

    CTR = itertools.count(1)
    REQ = object()

    def __init__(self, check=None, default=REQ, order=None, hint=None):
        self.check = check          # expected type
        self.default = default      # default value or mandatory field
        self.order = order or next(self.CTR)    # relative order
        self.hint = hint            # one line description

    def __get__(self, instance, owner):
        if instance is None:
            return self
        raise AttributeError("unset test field")


class RecordMetaclass(type):

    def __new__(mcls, name, bases, members):
        # Nothing to do if fields are processed already.
        if '__fields__' in members:
            return type.__new__(mcls, name, bases, members)

        # Gather fields from base classes.
        fields = set()
        for base in bases:
            if '__fields__' in base.__dict__:
                fields.update(base.__fields__)

        # Find and process field descriptors in the class dictionary.
        keys = set(field.key for field in fields)
        for attr in sorted(members):
            dsc = members[attr]
            if not isinstance(dsc, Field):
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
            field = FieldSpec(attr, key, check, default,
                              order=order, required=required, hint=hint)
            fields.add(field)

        # Store field metadata and generate the class.
        fields = sorted(fields, key=(lambda f: f.order))
        members['__fields__'] = tuple(fields)
        members['__slots__'] = tuple(field.attr for field in fields)
        return type.__new__(mcls, name, bases, members)


class Record(object):
    """Base class for test input/output data."""

    __metaclass__ = RecordMetaclass
    __slots__ = ('__weakref__',)
    __owner__ = None                # test type which owns the record type
    __fields__ = ()                 # list of record fields

    @classmethod
    def __recognizes__(cls, keys):
        """Checks if the set of keys compatible with the record type."""
        # Check if the key set contains all required record fields.
        if not any(field.required for field in cls.__fields__):
            return False
        return all(field.key in keys for field in cls.__fields__
                                     if field.required)

    @classmethod
    def __load__(cls, mapping):
        """Generates a record from a mapping of field keys and values."""
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
        Checks if two records are complementary input and output records for
        the same test case.
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
        # Convert any keywords to positional arguments.
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
            args = args + tuple(args_tail)
        # Complain if there are any keywords left.
        if kwds:
            attr = sorted(kwds)[0]
            if any(field.attr == attr for field in self.__fields__):
                raise TypeError("duplicate field %r" % attr)
            else:
                raise TypeError("unknown field %r" % attr)
        # Assign field values.
        if len(args) != len(self.__fields__):
            raise TypeError("expected %d arguments, got %d"
                            % (len(self.__fields__), len(args)))
        for arg, field in zip(args, self.__fields__):
            setattr(self, field.attr, arg)

    def __clone__(self, **kwds):
        """Makes a copy with new values for the given fields."""
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
        # Provided so that ``tuple(self)`` works.
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
        # Generates printable representation from the first mandatory field.
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


def Test(cls):
    """Registers a test type."""
    assert isinstance(cls, types.TypeType), "a test type must be a class"

    # Convert `Input` and `Output` definitions to `Record` subclasses.
    for name in ['Input', 'Output']:
        record_bases = [Record]
        for base in reversed(cls.__mro__):
            if name not in base.__dict__:
                continue
            record_def = base.__dict__[name]
            if isinstance(record_def, type) and issubclass(record_def, Record):
                record_bases.insert(0, record_def)
                continue
            record_name = "%s.%s" % (base.__name__, name)
            record_members = record_def.__dict__.copy()
            record_members['__owner__'] = base
            record_type = type(record_name, tuple(record_bases), record_members)
            setattr(base, name, record_type)
            record_bases.insert(0, record_type)

    # Register test and record types.
    registry.case_types.append(cls)
    if 'Input' in cls.__dict__:
        registry.input_types.append(cls.Input)
    if 'Output' in cls.__dict__:
        registry.output_types.append(cls.Output)

    return cls


