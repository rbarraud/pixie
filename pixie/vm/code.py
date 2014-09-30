import pixie.vm.object as object
from pixie.vm.primitives import nil, true, false
from rpython.rlib.rarithmetic import r_uint
from rpython.rlib.jit import elidable, elidable_promote, promote


BYTECODES = ["LOAD_CONST",
             "ADD",
             "EQ",
             "INVOKE",
             "TAIL_CALL",
             "DUP_NTH",
             "RETURN",
             "COND_BR",
             "JMP",
             "CLOSED_OVER",
             "MAKE_CLOSURE",
             "SET_VAR",
             "POP",
             "DEREF_VAR",
             "INSTALL",
             "RECUR",
             "ARG",
             "PUSH_SELF"]

for x in range(len(BYTECODES)):
    globals()[BYTECODES[x]] = r_uint(x)

# class TailCall(object.Object):
#     _type = object.Type("TailCall")
#     __immutable_fields_ = ["_f", "_args"]
#     def __init__(self, f, args):
#         self._f = f
#         self._args = args
#
#     def run(self):
#         return self._f._invoke(self._args)


class BaseCode(object.Object):
    def __init__(self):
        pass

    def _invoke(self, args):
        raise NotImplementedError()

    def get_consts(self):
        raise NotImplementedError()

    def get_bytecode(self):
        raise NotImplementedError()

    def invoke(self, args):
        result = self._invoke(args)
        return result




class NativeFn(BaseCode):
    """Wrapper for a native function"""
    _type = object.Type("NativeFn")

    def __init__(self):
        BaseCode.__init__(self)

    def type(self):
        return NativeFn._type

    def _invoke(self, args):
        return self.inner_invoke(args)

    def inner_invoke(self, args):
        raise NotImplementedError()


class Code(BaseCode):
    """Interpreted code block. Contains consts and """
    _type = object.Type("Code")
    __immutable_fields__ = ["_consts[*]", "_bytecode"]

    def type(self):
        return Code._type

    def __init__(self, name, bytecode, consts):
        BaseCode.__init__(self)
        self._bytecode = bytecode
        self._consts = consts
        self._name = name

    def _invoke(self, args):
        return interpret(self, args)

    def get_consts(self):
        return self._consts

    def get_bytecode(self):
        return self._bytecode

class Closure(Code):
    _type = object.Type("Closure")
    __immutable_fields__ = ["_closed_overs[*]", "_code"]
    def type(self):
        return Closure._type

    def __init__(self, code, closed_overs):
        BaseCode.__init__(self)
        self._code = code
        self._closed_overs = closed_overs

    def _invoke(self, args):
        return interpret(self, args)

    def get_closed_over(self, idx):
        return self._closed_overs[idx]

    def get_consts(self):
        return self._code.get_consts()

    def get_bytecode(self):
        return self._code.get_bytecode()

class Var(object.Object):
    _type = object.Type("Var")
    _immutable_fields_ = ["_rev?"]

    def type(self):
        return Var._type

    def __init__(self, name):
        self._name = name
        self._rev = 0

    def set_root(self, o):
        self._rev += 1
        self._root = o
        return self

    @elidable
    def get_root(self, rev):
        return self._root


    def deref(self):
        rev = promote(self._rev)
        return self.get_root(rev)


class Namespace(__builtins__.object):
    def __init__(self, name):
        self._registry = {}
        self._name = name

    def intern_or_make(self, name):
        assert isinstance(name, str)
        v = self._registry.get(name, None)
        if v is None:
            v = Var(name).set_root(nil)
            self._registry[name] = v
        return v

    def get(self, name, default):
        return self._registry.get(name, default)

class NamespaceRegistry(__builtins__.object):
    def __init__(self):
        self._registry = {}

    def find_or_make(self, name):
        assert isinstance(name, str)
        v = self._registry.get(name, None)
        if v is None:
            v = Namespace(name)
            self._registry[name] = v
        return v


    def get(self, name, default):
        return self._registry.get(name, default)

_ns_registry = NamespaceRegistry()

def intern_var(ns, name=None):
    if name is None:
        name = ns
        ns = ""

    return _ns_registry.find_or_make(ns).intern_or_make(name)

def get_var_if_defined(ns, name):
    w_ns = _ns_registry.get(ns, None)
    if w_ns is None:
        return None
    return w_ns.get(name, None)






class Protocol(object.Object):
    _type = object.Type("Protocol")

    def __init__(self, name):
        self._name = name
        self._polyfns = {}
        self._satisfies = {}

    def add_method(self, pfn):
        self._polyfns[pfn] = pfn

    def add_satisfies(self, tp):
        self._satisfies[tp] = tp

    def satisfies(self, tp):
        return tp in self._satisfies


class PolymorphicFn(BaseCode):
    _type = object.Type("PolymorphicFn")

    __immutable_fields__ = ["_rev?"]
    def __init__(self, name, protocol):
        self._name = name
        self._dict = {}
        self._rev = 0
        self._protocol = protocol
        protocol.add_method(self)

    def extend(self, tp, fn):
        self._dict[tp] = fn
        self._rev += 1
        self._protocol.add_satisfies(tp)

    def _invoke(self, args):
        a = args[0].type()
        return self._dict[a].invoke(args)

class DoublePolymorphicFn(BaseCode):
    _type = object.Type("DoublePolymorphicFn")

    __immutable_fields__ = ["_rev?"]
    def __init__(self, name, protocol):
        BaseCode.__init__(self)
        self._name = name
        self._dict = {}
        self._rev = 0
        self._protocol = protocol
        protocol.add_method(self)

    def extend2(self, tp1, tp2, fn):
        d1 = self._dict.get(tp1, None)
        if d1 is None:
            d1 = {}
            self._dict[tp1] = d1
        d1[tp2] = fn
        self._rev += 1
        self._protocol.add_satisfies(tp1)


    @elidable
    def get_fn(self, tp1, tp2, _rev):
        d1 = self._dict.get(tp1, None)
        assert d1
        fn = d1.get(tp2, None)
        return promote(fn)

    def _invoke(self, args):
        assert len(args) >= 2
        a = args[0].type()
        b = args[1].type()
        fn = self.get_fn(a, b, self._rev)
        return fn.invoke(args)

def munge(s):
    return s.replace("-", "_")

import inspect
def defprotocol(ns, name, methods):
    gbls = inspect.currentframe().f_back.f_globals
    proto =  Protocol(name)
    intern_var(ns, name).set_root(proto)
    gbls[munge(name)] = proto
    for method in methods:
        poly = PolymorphicFn(method,  proto)
        intern_var(ns, method).set_root(poly)
        gbls[munge(method)] = poly


## PYTHON FLAGS
CO_VARARGS = 0x4
def wrap_fn(fn):
    def as_native_fn(f):
        return type("W"+fn.__name__, (NativeFn,), {"inner_invoke": f})()

    code = fn.func_code
    if code.co_flags & CO_VARARGS:
        pass
    else:
        argc = code.co_argcount
        if argc == 0:
            return as_native_fn(lambda self, args: fn())
        if argc == 1:
            return as_native_fn(lambda self, args: fn(args[0]))
        if argc == 2:
            return as_native_fn(lambda self, args: fn(args[0], args[1]))
        if argc == 3:
            return as_native_fn(lambda self, args: fn(args[0], args[1]))


def extend(pfn, tp1, tp2=None):
    def extend_inner(fn):
        if tp2 is None:
            pfn.extend(tp1, wrap_fn(fn))
        else:
            pfn.extend2(tp1, tp2, wrap_fn(fn))

        return pfn

    return extend_inner



def as_var(ns, name=None):
    if name is None:
        name = ns
        ns = "pixie.stdlib"
    var = intern_var(ns, name)
    def with_fn(fn):
        if not isinstance(fn, BaseCode):
            fn = wrap_fn(fn)
        var.set_root(fn)
        return fn
    return with_fn