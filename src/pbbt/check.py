#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


class check(object):

    def __instanceheck__(self, data):
        return False

    @property
    def __name__(self):
        return self.__class__.__name__

    def __repr__(self):
        return self.__name__


class maybe(check):

    def __init__(self, check):
        self.check = check

    def __instancecheck__(self, data):
        return (data is None or isinstance(data, self.check))

    @property
    def __name__(self):
        return "maybe(%s)" % self.check.__name__


class oneof(check):

    def __init__(self, *checks):
        self.checks = checks

    def __instancecheck__(self, data):
        return any(isinstance(data, check) for check in self.checks)

    @property
    def __name__(self):
        return "oneof(%s)" % \
                ", ".join(check.__name__ for check in self.checks)


class choiceof(check):

    def __init__(self, values):
        self.values = values

    def __instancecheck__(self, data):
        return (data in self.values)

    @property
    def __name__(self):
        return "choiceof(%s)" % ", ".join(repr(value) for value in self.values)


class listof(check):

    def __init__(self, item_check):
        self.item_check = item_check

    def __instancecheck__(self, data):
        return (isinstance(data, list) and
                all(isinstance(item, self.item_check) for item in data))

    @property
    def __name__(self):
        return "listof(%s)" % self.item_check.__name__


class dictof(check):

    def __init__(self, key_check, item_check):
        self.key_check = key_check
        self.item_check = item_check

    def __instancecheck__(self, data):
        return (isinstance(data, dict) and
                all(isinstance(key, self.key_type) and
                    isinstance(value[key], self.item_type)
                    for key in data))

    @property
    def __name__(self):
        return "dictof(%s, %s)" % (self.key_check.__name__,
                                   self.item_check.__name__)


class subclassof(check):

    def __init__(self, class_type):
        self.class_type = class_type

    def __instancecheck__(self, data):
        return (isinstance(data, type) and issubclass(data, self.class_type))

    @property
    def __name__(self):
        return "subclassof(%s)" % self.class_type.__name__


