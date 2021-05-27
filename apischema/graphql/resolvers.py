from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from inspect import Parameter, signature
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    overload,
)

import graphql

from apischema.aliases import Aliaser
from apischema.conversions.conversions import (
    Conversions,
    HashableConversions,
    to_hashable_conversions,
)
from apischema.deserialization import deserialize
from apischema.json_schema.schemas import Schema
from apischema.objects import ObjectField
from apischema.serialization import serialization_method_factory, serialize
from apischema.serialization.serialized_methods import (
    ErrorHandler,
    SerializedMethod,
    _get_methods,
    serialized as register_serialized,
)
from apischema.types import AnyType, NoneType, Undefined
from apischema.utils import (
    awaitable_origin,
    empty_dict,
    get_args2,
    get_origin_or_type2,
    is_async,
    is_union_of,
    keep_annotations,
    method_registerer,
)
from apischema.validation.errors import ValidationError

T = TypeVar("T")


partial_serialization_method = serialization_method_factory(
    lambda cls, aliaser: lambda obj, exc_unset: obj,  # type: ignore
    lambda obj, exc_unset: None,  # type: ignore
)


def partial_serialize(
    obj: Any, *, conversions: HashableConversions = None, aliaser: Aliaser
) -> Any:
    return partial_serialization_method(obj.__class__, conversions, aliaser)(obj, False)


def unwrap_awaitable(tp: AnyType) -> AnyType:
    if get_origin_or_type2(tp) == awaitable_origin:
        return keep_annotations(get_args2(tp)[0] if get_args2(tp) else Any, tp)
    else:
        return tp


@dataclass(frozen=True)
class Resolver(SerializedMethod):
    parameters: Sequence[Parameter]
    parameters_metadata: Mapping[str, Mapping]

    def error_type(self) -> AnyType:
        return unwrap_awaitable(super().error_type())

    def return_type(self, return_type: AnyType) -> AnyType:
        return super().return_type(unwrap_awaitable(return_type))


_resolvers: Dict[Type, Dict[str, Resolver]] = defaultdict(dict)


def get_resolvers(tp: AnyType) -> Mapping[str, Tuple[Resolver, Mapping[str, AnyType]]]:
    return _get_methods(tp, _resolvers)


def none_error_handler(
    __error: Exception, __obj: Any, __info: graphql.GraphQLResolveInfo, **kwargs
) -> None:
    return None


def resolver_parameters(
    resolver: Callable, *, check_first: bool
) -> Iterator[Parameter]:
    first = True
    for param in signature(resolver).parameters.values():
        if param.kind is Parameter.POSITIONAL_ONLY:
            raise TypeError("Resolver can not have positional only parameters")
        if param.kind in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}:
            if param.annotation is Parameter.empty and (check_first or not first):
                raise TypeError("Resolver parameters must be typed")
            yield param
        first = False


MethodOrProp = TypeVar("MethodOrProp", Callable, property)


@overload
def resolver(__method_or_property: MethodOrProp) -> MethodOrProp:
    ...


@overload
def resolver(
    alias: str = None,
    *,
    conversions: Conversions = None,
    schema: Schema = None,
    error_handler: ErrorHandler = Undefined,
    parameters_metadata: Mapping[str, Mapping] = None,
    serialized: bool = False,
    owner: Type = None,
) -> Callable[[MethodOrProp], MethodOrProp]:
    ...


def resolver(
    __arg=None,
    *,
    alias: str = None,
    conversions: Conversions = None,
    schema: Schema = None,
    error_handler: ErrorHandler = Undefined,
    parameters_metadata: Mapping[str, Mapping] = None,
    serialized: bool = False,
    owner: Type = None,
):
    def register(func: Callable, owner: Type, alias2: str):
        alias2 = alias or alias2
        _, *parameters = resolver_parameters(func, check_first=owner is None)
        error_handler2 = error_handler
        if error_handler2 is None:
            error_handler2 = none_error_handler
        elif error_handler2 is Undefined:
            error_handler2 = None
        resolver = Resolver(
            func,
            conversions,
            schema,
            error_handler2,
            parameters,
            parameters_metadata or {},
        )
        _resolvers[owner][alias2] = resolver
        if serialized:
            if is_async(func):
                raise TypeError("Async resolver cannot be used as a serialized method")
            try:
                register_serialized(
                    alias=alias2,
                    conversions=conversions,
                    schema=schema,
                    error_handler=error_handler,
                    owner=owner,
                )(func)
            except Exception:
                raise TypeError("Resolver cannot be used as a serialized method")

    if isinstance(__arg, str):
        alias = __arg
        __arg = None
    return method_registerer(__arg, owner, register)


def resolver_resolve(
    resolver: Resolver,
    types: Mapping[str, AnyType],
    aliaser: Aliaser,
    serialized: bool = True,
) -> Callable:
    parameters, info_parameter = [], None
    for param in resolver.parameters:
        param_type = types[param.name]
        if is_union_of(param_type, graphql.GraphQLResolveInfo):
            info_parameter = param.name
        else:
            param_field = ObjectField(
                param.name,
                param_type,
                param.default is Parameter.empty,
                resolver.parameters_metadata.get(param.name, empty_dict),
                default=param.default,
            )
            deserializer = partial(
                deserialize,
                param_type,
                conversions=param_field.deserialization,
                aliaser=aliaser,
                default_fallback=param_field.default_fallback or None,
            )
            opt_param = is_union_of(param_type, NoneType) or param.default is None
            parameters.append(
                (
                    aliaser(param_field.alias),
                    param.name,
                    deserializer,
                    opt_param,
                    param_field.required,
                )
            )
    func, error_handler = resolver.func, resolver.error_handler
    conversions = to_hashable_conversions(resolver.conversions)

    def no_serialize(result):
        return result

    async def async_serialize(result: Awaitable):
        awaited = await result
        return partial_serialization_method(awaited.__class__, conversions, aliaser)(
            awaited, False
        )

    def sync_serialize(result):
        return partial_serialization_method(result.__class__, conversions, aliaser)(
            result, False
        )

    serialize_result: Callable[[Any], Any]
    if not serialized:
        serialize_result = no_serialize
    elif is_async(resolver.func):
        serialize_result = async_serialize
    else:
        serialize_result = sync_serialize
    serialize_error: Optional[Callable[[Any], Any]]
    if error_handler is None:
        serialize_error = None
    elif is_async(error_handler):
        serialize_error = async_serialize
    else:
        serialize_error = sync_serialize

    def resolve(__self, __info, **kwargs):
        values = {}
        errors: Dict[str, ValidationError] = {}
        for alias, param_name, deserializer, opt_param, required in parameters:
            if alias in kwargs:
                # It is possible for the parameter to be non-optional in Python
                # type hints but optional in the generated schema. In this case
                # we should ignore it.
                # See: https://github.com/wyfo/apischema/pull/130#issuecomment-845497392
                if not opt_param and kwargs[alias] is None:
                    assert not required
                    continue
                try:
                    values[param_name] = deserializer(kwargs[alias])
                except ValidationError as err:
                    errors[aliaser(param_name)] = err
            elif opt_param and required:
                values[param_name] = None

        if errors:
            raise TypeError(serialize(ValidationError(children=errors)))
        if info_parameter:
            values[info_parameter] = __info
        try:
            return serialize_result(func(__self, **values))
        except Exception as error:
            if error_handler is None:
                raise
            assert serialize_error is not None
            return serialize_error(error_handler(error, __self, __info, **kwargs))

    return resolve
