#!/usr/bin/env python3
import collections.abc
import dataclasses
import importlib
import inspect
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import FunctionType
from typing import (
    AbstractSet,
    Any,
    Callable,
    Iterable,
    List,
    Mapping,
    Match,
    NamedTuple,
    Optional,
    Pattern,
    TextIO,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_type_hints,
)

from Cython.Build import cythonize

try:
    from typing import Literal

    CythonDef = Literal["cdef", "cpdef", "cdef inline", "cpdef inline"]
except ImportError:
    CythonDef = str  # type: ignore


ROOT_DIR = Path(__file__).parent.parent
DISPATCH_FIELD = "_dispatch"
CYTHON_TYPES = {
    type: "type",
    bytes: "bytes",
    bytearray: "bytearray",
    bool: "bint",
    str: "str",
    tuple: "tuple",
    Tuple: "tuple",
    list: "list",
    int: "long",
    dict: "dict",
    Mapping: "dict",
    collections.abc.Mapping: "dict",
    set: "set",
    AbstractSet: "set",
    collections.abc.Set: "set",
}

Elt = TypeVar("Elt", type, FunctionType)


@lru_cache()
def module_elements(module: str, cls: Type[Elt]) -> Iterable[Elt]:
    return [
        obj
        for obj in importlib.import_module(module).__dict__.values()
        if isinstance(obj, cls) and obj.__module__ == module
    ]


@lru_cache()
def module_type_mapping(module: str) -> Mapping[type, str]:
    mapping = CYTHON_TYPES.copy()
    for cls in module_elements(module, type):
        mapping[cls] = cls.__name__
        mapping[Optional[cls]] = cls.__name__
        if sys.version_info >= (3, 10):
            mapping[cls | None] = cls.__name__  # type: ignore
    return mapping  # type: ignore


def method_name(cls: type, method: str) -> str:
    return f"{cls.__name__}_{method}"


def cython_type(tp: Any, module: str) -> str:
    return module_type_mapping(module).get(getattr(tp, "__origin__", tp), "object")


def cython_signature(
    def_type: CythonDef, func: FunctionType, self_type: Optional[type] = None
) -> str:
    parameters = list(inspect.signature(func).parameters.values())
    types = get_type_hints(func)
    param_with_types = []
    if parameters[0].name == "self":
        if self_type is not None:
            types["self"] = self_type
        else:
            param_with_types.append("self")
            parameters.pop(0)
    for param in parameters:
        param_type = cython_type(types[param.name], func.__module__)
        assert param.default is inspect.Parameter.empty or param.default is None
        param_with_types.append(
            f"{param_type} {param.name}" + (" = None" if param.default is None else "")
        )
    func_name = method_name(self_type, func.__name__) if self_type else func.__name__
    return f"{def_type} {func_name}(" + ", ".join(param_with_types) + "):"


class IndentedWriter:
    def __init__(self, file: TextIO):
        self.file = file
        self.indentation = ""

    def write(self, txt: str):
        self.file.write(txt)

    def writelines(self, lines: Iterable[str]):
        self.file.writelines(lines)

    def writeln(self, txt: str = ""):
        self.write((self.indentation + txt + "\n") if txt else "\n")

    @contextmanager
    def indent(self):
        self.indentation += 4 * " "
        yield
        self.indentation = self.indentation[:-4]

    @contextmanager
    def write_block(self, txt: str):
        self.writeln(txt)
        with self.indent():
            yield


def rec_subclasses(cls: type) -> Iterable[type]:
    for sub_cls in cls.__subclasses__():
        yield sub_cls
        yield from rec_subclasses(sub_cls)


@lru_cache()
def get_dispatch(base_class: type) -> Mapping[type, int]:
    return {cls: i for i, cls in enumerate(rec_subclasses(base_class))}


class Method(NamedTuple):
    base_class: type
    function: FunctionType

    @property
    def name(self) -> str:
        return self.function.__name__


@lru_cache()
def module_methods(module: str) -> Mapping[str, Method]:
    all_methods = [
        Method(cls, func)  # type: ignore
        for cls in module_elements(module, type)
        if cls.__bases__ == (object,) and cls.__subclasses__()
        for func in cls.__dict__.values()
        if isinstance(func, FunctionType) and not func.__name__.startswith("_")
    ]
    methods_by_name = {method.name: method for method in all_methods}
    assert len(methods_by_name) == len(
        all_methods
    ), "method substitution requires unique method names"
    return methods_by_name


ReRepl = Callable[[Match], str]


@dataclass
class LineSubstitutor:
    lines: Iterable[str]

    def __call__(self, pattern: Pattern) -> Callable[[ReRepl], ReRepl]:
        def decorator(repl: ReRepl) -> ReRepl:
            self.lines = (re.sub(pattern, repl, l) for l in self.lines)
            return repl

        return decorator


def get_body(func: FunctionType, cls: Optional[type] = None) -> Iterable[str]:
    lines, _ = inspect.getsourcelines(func)
    line_iter = iter(lines)
    for line in line_iter:
        if line.split("#")[0].rstrip().endswith(":"):
            break
    else:
        raise NotImplementedError
    substitutor = LineSubstitutor(line_iter)
    if cls is not None:

        @substitutor(re.compile(r"super\(\)\.(\w+)\("))
        def replace_super(match: Match) -> str:
            assert cls is not None
            super_cls = cls.__bases__[0].__name__
            return f"{super_cls}_{match.group(1)}(<{super_cls}>self, "

        @substitutor(
            re.compile(
                r"(\s+)for ((\w+) in self\.(\w+)|(\w+), (\w+) in enumerate\(self\.(\w+)\)):"
            )
        )
        def replace_for_loop(match: Match) -> str:
            assert cls is not None
            tab = match.group(1)
            index = match.group(5) or "__i"
            elt = match.group(3) or match.group(6)
            field = match.group(4) or match.group(7)
            field_type = get_type_hints(cls)[field]
            assert (
                field_type.__origin__ in (Tuple, tuple)
                and field_type.__args__[1] is ...
            )
            elt_type = cython_type(field_type.__args__[0], func.__module__)
            return f"{tab}for {index} in range(len(self.{field})):\n{tab}    {elt}: {elt_type} = self.{field}[{index}]"

    @substitutor(re.compile(r"^(\s+\w+:)([^#=]*)(?==)"))
    def replace_variable_annotations(match: Match) -> str:
        tp = eval(match.group(2), func.__globals__)
        return match.group(1) + cython_type(tp, func.__module__)

    methods = module_methods(func.__module__)
    method_names = "|".join(methods)

    @substitutor(re.compile(rf"([\w.]+)\.({method_names})\("))
    def replace_method(match: Match) -> str:
        self, name = match.groups()
        cls, _ = methods[name]
        return f"{cls.__name__}_{name}({self}, "

    return substitutor.lines


def import_lines(path: Union[str, Path]) -> Iterable[str]:
    # could also be retrieved with ast
    with open(path) as field:
        for line in field:
            if not line.strip() or any(
                # " " and ")" because of multiline imports
                map(line.startswith, ("from ", "import ", " ", ")"))
            ):
                yield line
            else:
                break


def write_class(pyx: IndentedWriter, cls: type):
    bases = ", ".join(b.__name__ for b in cls.__bases__ if b is not object)
    with pyx.write_block(f"cdef class {cls.__name__}({bases}):"):
        annotations = cls.__dict__.get("__annotations__", {})
        for name, tp in get_type_hints(cls).items():
            if name in annotations:
                pyx.writeln(f"cdef readonly {cython_type(tp, cls.__module__)} {name}")
        dispatch = None
        if cls.__bases__ == (object,):
            if cls.__subclasses__():
                pyx.writeln(f"cdef int {DISPATCH_FIELD}")
        else:
            base_class = cls.__mro__[-2]
            dispatch = get_dispatch(base_class)[cls]
            for name, obj in cls.__dict__.items():
                if (
                    not name.startswith("_")
                    and name not in annotations
                    and isinstance(obj, FunctionType)
                ):
                    pyx.writeln()
                    base_method = getattr(base_class, name)
                    with pyx.write_block(cython_signature("cpdef", base_method)):
                        args = ", ".join(inspect.signature(base_method).parameters)
                        pyx.writeln(f"return {cls.__name__}_{name}({args})")
        if annotations or dispatch is not None:
            pyx.writeln()
            init_fields: List[str] = []
            if dataclasses.is_dataclass(cls):
                init_fields.extend(
                    field.name for field in dataclasses.fields(cls) if field.init
                )
            with pyx.write_block(
                "def __init__(" + ", ".join(["self"] + init_fields) + "):"
            ):
                for name in init_fields:
                    pyx.writeln(f"self.{name} = {name}")
                if hasattr(cls, "__post_init__"):
                    lines, _ = inspect.getsourcelines(cls.__post_init__)
                    pyx.writelines(lines[1:])
                if dispatch is not None:
                    pyx.writeln(f"self.{DISPATCH_FIELD} = {dispatch}")


def write_function(pyx: IndentedWriter, func: FunctionType):
    pyx.writeln(cython_signature("cpdef inline", func))
    pyx.writelines(get_body(func))


def write_methods(pyx: IndentedWriter, method: Method):
    for cls, dispatch in get_dispatch(method.base_class).items():
        if method.name in cls.__dict__:
            sub_method = cls.__dict__[method.name]
            with pyx.write_block(cython_signature("cdef inline", sub_method, cls)):
                pyx.writelines(get_body(sub_method, cls))
            pyx.writeln()


def write_dispatch(pyx: IndentedWriter, method: Method):
    with pyx.write_block(cython_signature("cdef inline", method.function, method.base_class)):  # type: ignore
        pyx.writeln(f"cdef int {DISPATCH_FIELD} = self.{DISPATCH_FIELD}")
        for cls, dispatch in get_dispatch(method.base_class).items():
            if method.name in cls.__dict__:
                if_ = "if" if dispatch == 0 else "elif"
                with pyx.write_block(f"{if_} {DISPATCH_FIELD} == {dispatch}:"):
                    self, *params = inspect.signature(method.function).parameters
                    args = ", ".join([f"<{cls.__name__}>{self}", *params])
                    pyx.writeln(f"return {method_name(cls, method.name)}({args})")


def generate(package: str) -> str:
    module = f"apischema.{package}.methods"
    pyx_file_name = ROOT_DIR / "apischema" / package / "methods.pyx"
    with open(pyx_file_name, "w") as pyx_file:
        pyx = IndentedWriter(pyx_file)
        pyx.writeln("cimport cython")
        pyx.writeln("from cpython cimport *")
        pyx.writelines(import_lines(ROOT_DIR / "apischema" / package / "methods.py"))
        for cls in module_elements(module, type):
            write_class(pyx, cls)  # type: ignore
            pyx.writeln()
        for func in module_elements(module, FunctionType):
            if not func.__name__.startswith("Py"):
                write_function(pyx, func)  # type: ignore
                pyx.writeln()
        methods = module_methods(module)
        for method in methods.values():
            write_methods(pyx, method)
        for method in methods.values():
            write_dispatch(pyx, method)
            pyx.writeln()
    return str(pyx_file_name)


packages = ["deserialization", "serialization"]


def main():
    # remove compiled before generate, because .so would be imported otherwise
    for ext in ["so", "pyd"]:
        for file in (ROOT_DIR / "apischema").glob(f"**/*.{ext}"):
            file.unlink()
    sys.path.append(str(ROOT_DIR))
    cythonize(list(map(generate, packages)), language_level=3)


if __name__ == "__main__":
    main()
