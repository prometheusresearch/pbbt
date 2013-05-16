#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


class check(object):
    """Pseudo-type for ``isinstance()`` checks."""

    def __instanceheck__(self, data):
        return False

    @property
    def __name__(self):
        return self.__class__.__name__

    def __repr__(self):
        return self.__name__


class maybe(check):
    """The given type or ``None``."""

    def __init__(self, check):
        self.check = check

    def __instancecheck__(self, data):
        return (data is None or isinstance(data, self.check))

    @property
    def __name__(self):
        return "maybe(%s)" % self.check.__name__


class oneof(check):
    """One of the given types."""

    def __init__(self, *checks):
        self.checks = checks

    def __instancecheck__(self, data):
        return any(isinstance(data, check) for check in self.checks)

    @property
    def __name__(self):
        return "oneof(%s)" % \
                ", ".join(check.__name__ for check in self.checks)


class choiceof(check):
    """A value from the given list of choices."""

    def __init__(self, values):
        self.values = values

    def __instancecheck__(self, data):
        return (data in self.values)

    @property
    def __name__(self):
        return "choiceof(%s)" % ", ".join(repr(value) for value in self.values)


class listof(check):
    """List of items of the given type."""

    def __init__(self, item_check, length=None):
        self.item_check = item_check
        self.length = length

    def __instancecheck__(self, data):
        return (isinstance(data, list) and
                all(isinstance(item, self.item_check) for item in data))

    @property
    def __name__(self):
        if self.length is not None:
            return "listof(%s, length=%s)" \
                    % (self.item_check.__name__, self.length)
        else:
            return "listof(%s)" % self.item_check.__name__


class tupleof(check):
    """Tuple with fields of the given types."""

    def __init__(self, *checks):
        self.checks = checks

    def __instancecheck__(self, data):
        return (isinstance(data, tuple) and
                len(data) == len(self.checks) and
                all(isinstance(item, check)
                    for item, check in zip(data, self.checks)))

    @property
    def __name__(self):
        return "tupleof(%s)" % ", ".join(check.__name__
                                         for check in self.checks)


class dictof(check):
    """Dictionary with keys and values of the given types."""

    def __init__(self, key_check, value_check):
        self.key_check = key_check
        self.value_check = value_check

    def __instancecheck__(self, data):
        return (isinstance(data, dict) and
                all(isinstance(key, self.key_check) and
                    isinstance(data[key], self.value_check)
                    for key in data))

    @property
    def __name__(self):
        return "dictof(%s, %s)" % (self.key_check.__name__,
                                   self.value_check.__name__)


class ExceptionInfo(object):
    """Information about a raised exception."""

    def __init__(self):
        self.type = None
        self.value = None
        self.traceback = None

    def update(self, type, value, traceback):
        self.type = type
        self.value = value
        self.traceback = traceback

    def __nonzero__(self):
        return (self.type is not None)

    def __str__(self):
        return "%s: %s" % (self.type.__name__, self.value)

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__,
                            self.type.__name__ if self.type else None)


class ExceptionCatcher(object):
    """Intersepts exceptions of the given type."""

    def __init__(self, exc_type):
        self.exc_type = exc_type
        self.exc_info = ExceptionInfo()

    def __enter__(self):
        return self.exc_info

    def __exit__(self, exc_type, exc_value, exc_traceback):
        assert exc_type is not None, \
                "expected exception %s" % self.exc_type.__name__
        if issubclass(exc_type, self.exc_type):
            self.exc_info.update(exc_type, exc_value, exc_traceback)
            return True


def raises(exc_type, callable=None, *args, **kwds):
    """Verifies that the code produces an exception of the given type."""
    if callable is not None:
        with raises(exc_type) as exc_info:
            callable(*args, **kwds)
        return exc_info
    else:
        return ExceptionCatcher(exc_type)


