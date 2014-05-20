#!/usr/bin/env python
# coding=utf-8
from __future__ import division, print_function, unicode_literals
import ast
from copy import copy
from functools import update_wrapper
import inspect
import json
import re


def dogmatize(x):
    if isinstance(x, dict):
        return DogmaticDict({k: dogmatize(v) for k, v in x.items()})
    elif isinstance(x, list):
        return DogmaticList([dogmatize(v) for v in x])
    elif isinstance(x, tuple):
        return tuple(dogmatize(v) for v in x)
    else:
        return x


def undogmatize(x):
    if isinstance(x, DogmaticDict):
        return dict({k: undogmatize(v) for k, v in x.items()})
    elif isinstance(x, DogmaticList):
        return list([undogmatize(v) for v in x])
    elif isinstance(x, tuple):
        return tuple(undogmatize(v) for v in x)
    else:
        return x


def type_changed(a, b):
    if isinstance(a, DogmaticDict) or isinstance(b, DogmaticDict):
        return not (isinstance(a, dict) and isinstance(b, dict))
    if isinstance(a, DogmaticList) or isinstance(b, DogmaticList):
        return not (isinstance(a, list) and isinstance(b, list))
    return type(a) != type(b)


class DogmaticDict(dict):
    def __init__(self, fixed=None):
        super(DogmaticDict, self).__init__()
        self._typechanges = {}
        if fixed is not None:
            self._fixed = fixed
        else:
            self._fixed = ()

    def __setitem__(self, key, value):
        if key not in self._fixed:
            dict.__setitem__(self, key, value)
        else:
            fixed_val = self._fixed[key]
            dict.__setitem__(self, key, fixed_val)
            # log typechanges
            if type_changed(value, fixed_val):
                self._typechanges[key] = (type(value), type(fixed_val))

            if isinstance(fixed_val, DogmaticDict) and isinstance(value, dict):
                #recursive update
                bd = self[key]
                for k, v in value.items():
                    bd[k] = v

                for k, v in bd._typechanges.items():
                    self._typechanges[key + '.' + k] = v

    def __delitem__(self, key):
        if key not in self._fixed:
            dict.__delitem__(self, key)

    def update(self, iterable=None, **kwargs):
        if iterable is not None:
            if hasattr(iterable, 'keys'):
                for k in iterable:
                    self[k] = iterable[k]
            else:
                for (k, v) in iterable:
                    self[k] = v
        for k in kwargs:
            self[k] = kwargs[k]

    def revelation(self):
        missing = set()
        for key in self._fixed:
            if not key in self:
                self[key] = self._fixed[key]
                missing.add(key)

            if isinstance(self[key], DogmaticDict):
                missing |= {key + "." + k for k in self[key].revelation()}
        return missing


class DogmaticList(list):
    def append(self, p_object):
        pass

    def extend(self, iterable):
        pass

    def insert(self, index, p_object):
        pass

    def reverse(self):
        pass

    def sort(self, cmp=None, key=None, reverse=False):
        pass

    def __iadd__(self, other):
        return self

    def __imul__(self, other):
        return self

    def __setitem__(self, key, value):
        pass

    def __setslice__(self, i, j, sequence):
        pass

    def __delitem__(self, key):
        pass

    def __delslice__(self, i, j):
        pass

    def pop(self, index=None):
        raise TypeError('Cannot pop from DogmaticList')

    def remove(self, value):
        pass


def is_zero_argument_function(func):
    arg_spec = inspect.getargspec(func)
    return (arg_spec.args == [] and
            arg_spec.varargs is None and
            arg_spec.keywords is None)


def get_function_body_code(func):
    func_code_lines, start_idx = inspect.getsourcelines(func)
    filename = inspect.getfile(func)
    func_code = ''.join(func_code_lines)
    func_def = re.compile(
        r"^[ \t]*def[ \t]*{}[ \t]*\(\s*\)[ \t]*:[ \t]*\n\s*".format(func.__name__),
        flags=re.MULTILINE)
    defs = list(re.finditer(func_def, func_code))
    assert defs
    line_offset = func_code[:defs[0].end()].count('\n')
    func_body = func_code[defs[0].end():]
    body_code = compile(inspect.cleandoc(func_body), filename, "exec", ast.PyCF_ONLY_AST)
    body_code = ast.increment_lineno(body_code, n=start_idx+line_offset-1)
    body_code = compile(body_code, filename, "exec")
    return body_code


class ConfigScope(dict):
    def __init__(self, func):
        super(ConfigScope, self).__init__()
        assert is_zero_argument_function(func), \
            "only zero-argument function can be ConfigScopes"
        self._func = func
        update_wrapper(self, func)
        self._body_code = get_function_body_code(func)
        self._initialized = False
        self.added_values = set()
        self.typechanges = {}

    def __call__(self, fixed=None, preset=None):
        self._initialized = True
        self.clear()
        cfg_locals = dogmatize(fixed or {})
        if preset is not None:
            cfg_locals.update(preset)
        eval(self._body_code, copy(self._func.__globals__), cfg_locals)
        self.added_values = cfg_locals.revelation()
        self.typechanges = undogmatize(cfg_locals._typechanges)
        for k, v in cfg_locals.items():
            if k.startswith('_'):
                continue
            try:
                json.dumps(v)
                self[k] = undogmatize(v)
            except TypeError:
                pass
        return self

    def __getattr__(self, k):
        """
        Gets key if it exists, otherwise throws AttributeError.
        """
        try:
            # Throws exception if not in prototype chain
            return object.__getattribute__(self, k)
        except AttributeError:
            try:
                return self[k]
            except KeyError:
                raise AttributeError(k)

    def __getitem__(self, item):
        assert self._initialized, "ConfigScope has to be executed before access"
        return dict.__getitem__(self, item)