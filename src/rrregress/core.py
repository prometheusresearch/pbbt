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

    __slots__ = ('__weakref__',)
    __owner__ = None
    __fields__ = ()

    @classmethod
    def __make__(cls, owner, name, fields, members):
        name = "%s.%s" % (owner.__name__, name)
        bases = (cls,)
        members = members.copy()
        members['__slots__'] = tuple(field.attr for field in fields)
        members['__owner__'] = owner
        members['__fields__'] = fields
        return type(name, bases, members)

    @classmethod
    def __detects__(cls, keys):
        if not any(field.required for field in cls.__fields__):
            return False
        return all(field.key in keys for field in cls.__fields__
                                     if field.required)

    @classmethod
    def __load__(cls, mapping):
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
        mapping = []
        for field in self.__fields__:
            arg = getattr(self, field.attr)
            if arg == field.default:
                continue
            mapping.append((field.key, arg))
        return mapping

    def __matches__(self, other):
        if not (self.__owner__ is other.__owner__ and
                self.__class__ is not other.__class__):
            return False
        match_field = None
        other_attrs = set(field.attr for field in other.__fields__
                                     if field.required)
        for field in self.__fields__:
            if field.required and field.attr in other_attrs:
                match_field = field
                break
        if match_field is None:
            return False
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

    def __repr__(self):
        return ("%s(%s)" %
                (self.__class__.__name__,
                 ", ".join("%s=%r" % (field.attr, value)
                           for field, value in zip(self.__fields__, self)
                           if value != field.default)))


class TestFieldSpec(object):

    def __init__(self, attr, key, check=None, default=None,
                 required=False, hint=None):
        self.attr = attr
        self.key = key
        self.check = check
        self.default = default
        self.required = required
        self.hint = hint


class test_field(object):

    CTR = itertools.count(1)
    REQ = object()

    def __init__(self, check=None, default=REQ, order=None, hint=None):
        self.check = check
        self.default = default
        self.order = order or next(self.CTR)
        self.hint = hint

    def __get__(self, instance, owner):
        if instance is None:
            return self
        raise AttributeError("unset test field")


def test_type(cls):
    assert isinstance(cls, (types.ClassType, types.TypeType)), \
            "a test type must be a class"

    orig_cls = cls
    if isinstance(cls, types.ClassType):
        cls_members = {}
        cls_members['__module__'] = cls.__module__
        cls_members['__doc__'] = cls.__doc__
        cls = type(cls.__name__, (cls, object), cls_members)

    input_members = {}
    output_members = {}
    for base in reversed(cls.__mro__):
        if 'Input' in base.__dict__:
            input_members.update(base.__dict__['Input'].__dict__)
        if 'Output' in base.__dict__:
            output_members.update(base.__dict__['Output'].__dict__)

    input_attrs = []
    output_attrs = []
    for members, attrs in [(input_members, input_attrs),
                           (output_members, output_attrs)]:
        for attr in sorted(members):
            value = members[attr]
            if isinstance(value, test_field):
                attrs.append((value.order, attr, value))
                del members[attr]
    input_attrs.sort()
    output_attrs.sort()

    input_fields = []
    output_fields = []
    for attrs, fields in [(input_attrs, input_fields),
                          (output_attrs, output_fields)]:
        keys = set()
        for order, attr, dsc in attrs:
            key = attr
            if key.endswith('_') and not key.startswith('_'):
                key = key[:-1]
            key = key.replace('_', '-')
            assert key not in keys, \
                    "duplicate field %r" % key
            keys.add(key)
            check = dsc.check
            default = dsc.default
            required = False
            if default is dsc.REQ:
                required = True
                default = None
            hint = dsc.hint
            field = TestFieldSpec(attr, key, check, default,
                                  required=required, hint=hint)
            fields.append(field)

    registry.case_types.append(cls)
    cls.Input = None
    cls.Output = None
    if input_fields:
        cls.Input = TestRecord.__make__(cls, 'Input',
                                        input_fields, input_members)
        registry.input_types.append(cls.Input)
    if output_fields:
        cls.Output = TestRecord.__make__(cls, 'Output',
                                         output_fields, output_members)
        registry.output_types.append(cls.Output)

    return orig_cls


