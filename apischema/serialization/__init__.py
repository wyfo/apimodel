from enum import Enum
from functools import lru_cache, wraps
from typing import (
    Any,
    Callable,
    Collection,
    Mapping,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
    overload,
)

from apischema.aliases import Aliaser
from apischema.cache import cache
from apischema.conversions import identity
from apischema.conversions.conversions import Conversions, DefaultConversions
from apischema.conversions.utils import Converter
from apischema.conversions.visitor import (
    CachedConversionsVisitor,
    Serialization,
    SerializationVisitor,
    sub_conversions,
)
from apischema.fields import FIELDS_SET_ATTR, fields_set
from apischema.objects import AliasedStr, ObjectField
from apischema.objects.visitor import SerializationObjectVisitor
from apischema.serialization.serialized_methods import get_serialized_methods
from apischema.types import AnyType, NoneType, Undefined, UndefinedType
from apischema.typing import is_new_type, is_type_var, is_typed_dict
from apischema.utils import (
    Lazy,
    context_setter,
    get_origin_or_type,
    get_origin_or_type2,
    opt_or,
)

NEITHER_NONE_NOR_UNDEFINED = object()


SerializationMethod = Callable[[Any], Any]


def instance_checker(tp: AnyType) -> Callable[[Any], bool]:
    tp = get_origin_or_type2(tp)
    if isinstance(tp, type):
        return lambda obj: isinstance(obj, tp)
    elif is_new_type(tp):
        return instance_checker(tp.__supertype__)
    elif is_type_var(tp):
        return lambda obj: True
    else:
        raise TypeError(f"{tp} is not supported in union serialization")


class SerializationMethodVisitor(
    CachedConversionsVisitor,
    SerializationVisitor[SerializationMethod],
    SerializationObjectVisitor[SerializationMethod],
):
    def __init__(
        self,
        aliaser: Aliaser,
        any_fallback: bool,
        check_type: bool,
        default_conversions: DefaultConversions,
        exclude_unset: bool,
    ):
        super().__init__(default_conversions)
        self.aliaser = aliaser
        self._any_fallback = any_fallback
        self._check_type = check_type
        self._exclude_unset = exclude_unset

    def _cache_result(self, lazy: Lazy[SerializationMethod]) -> SerializationMethod:
        rec_method = None

        def method(obj: Any) -> Any:
            nonlocal rec_method
            if rec_method is None:
                rec_method = lazy()
            return rec_method(obj)

        return method

    @property
    def _any_method(self) -> Callable[[type], SerializationMethod]:
        return serialization_method_factory(
            self.aliaser,
            self._any_fallback,
            self._check_type,
            self._conversions,
            self.default_conversions,
            self._exclude_unset,
        )

    def _wrap_type_check(
        self, cls: type, method: SerializationMethod
    ) -> SerializationMethod:
        if not self._check_type:
            return method
        any_fallback, any_method = self._any_fallback, self._any_method

        @wraps(method)
        def wrapper(obj: Any) -> Any:
            if isinstance(obj, cls):
                return method(obj)
            elif any_fallback:
                return any_method(obj.__class__)(obj)
            else:
                raise TypeError(f"Expected {cls}, found {obj.__class__}")

        return wrapper

    def any(self) -> SerializationMethod:
        any_method = self._any_method

        def method(obj: Any) -> Any:
            return any_method(obj.__class__)(obj)

        return method

    def collection(
        self, cls: Type[Collection], value_type: AnyType
    ) -> SerializationMethod:
        serialize_value = self.visit(value_type)

        def method(obj: Any) -> Any:
            return [serialize_value(elt) for elt in obj]

        return self._wrap_type_check(cls, method)

    def enum(self, cls: Type[Enum]) -> SerializationMethod:
        any_method = self._any_method

        def method(obj: Any) -> Any:
            return any_method(obj.value.__class__)(obj.value)

        return self._wrap_type_check(cls, method)

    def literal(self, values: Sequence[Any]) -> SerializationMethod:
        return self.any()

    def mapping(
        self, cls: Type[Mapping], key_type: AnyType, value_type: AnyType
    ) -> SerializationMethod:
        serialize_key, serialize_value = self.visit(key_type), self.visit(value_type)

        def method(obj: Any) -> Any:
            return {
                serialize_key(key): serialize_value(value) for key, value in obj.items()
            }

        return self._wrap_type_check(cls, method)

    def object(self, tp: Type, fields: Sequence[ObjectField]) -> SerializationMethod:
        normal_fields, aggregate_fields = [], []
        for field in fields:
            serialize_field = self.visit_with_conv(field.type, field.serialization)
            if field.is_aggregate:
                aggregate_fields.append((field.name, serialize_field))
            else:
                normal_fields.append(
                    (field.name, self.aliaser(field.alias), serialize_field)
                )
        serialized_methods = [
            (
                self.aliaser(name),
                method.func,
                self.visit_with_conv(types["return"], method.conversions),
            )
            for name, (method, types) in get_serialized_methods(tp).items()
        ]
        exclude_unset = self._exclude_unset

        def method(obj: Any) -> Any:
            normal_fields2, aggregate_fields2 = normal_fields, aggregate_fields
            if exclude_unset and hasattr(obj, FIELDS_SET_ATTR):
                fields_set_ = fields_set(obj)
                normal_fields2 = [
                    (name, alias, method)
                    for (name, alias, method) in normal_fields
                    if name in fields_set_
                ]
                aggregate_fields2 = [
                    (name, method)
                    for (name, method) in aggregate_fields
                    if name in fields_set_
                ]
            result = {}
            # aggregate before normal fields to avoid overloading
            for name, field_method in aggregate_fields2:
                attr = getattr(obj, name)
                result.update(field_method(attr))
            for name, alias, field_method in normal_fields2:
                attr = getattr(obj, name)
                if attr is not Undefined:
                    result[alias] = field_method(attr)
            for alias, func, method in serialized_methods:
                res = func(obj)
                if res is not Undefined:
                    result[alias] = method(res)
            return result

        cls = get_origin_or_type(tp)
        if is_typed_dict(cls):
            cls = Mapping
        return self._wrap_type_check(cls, method)

    def primitive(self, cls: Type) -> SerializationMethod:
        def method(obj: Any) -> Any:
            return obj

        return self._wrap_type_check(cls, method)

    def tuple(self, types: Sequence[AnyType]) -> SerializationMethod:
        elt_deserializers = list(map(self.visit, types))

        def method(obj: Any) -> Any:
            return [
                serialize_elt(elt) for serialize_elt, elt in zip(elt_deserializers, obj)
            ]

        if self._check_type:
            wrapped = method
            any_fallback, as_list = self._any_fallback, self._any_method(list)

            def method(obj: Any) -> Any:
                if len(obj) == len(elt_deserializers):
                    return wrapped(obj)
                elif any_fallback:
                    return as_list(obj)
                else:
                    raise TypeError(
                        f"Expected {len(elt_deserializers)}-tuple,"
                        f" found {len(obj)}-tuple"
                    )

        return self._wrap_type_check(tuple, method)

    def union(self, alternatives: Sequence[AnyType]) -> SerializationMethod:
        method_and_checks = [
            (self.visit(alt), instance_checker(alt))
            for alt in alternatives
            if alt not in (None, UndefinedType)
        ]
        optimized_check = (
            None if NoneType in alternatives else NEITHER_NONE_NOR_UNDEFINED,
            Undefined if UndefinedType in alternatives else NEITHER_NONE_NOR_UNDEFINED,
        )
        any_fallback, any_method = self._any_fallback, self._any_method

        def method(obj: Any) -> Any:
            # Optional/Undefined optimization
            if obj in optimized_check:
                return obj
            error = None
            for alt_method, instance_check in method_and_checks:
                if not instance_check(obj):
                    continue
                try:
                    return alt_method(obj)
                except Exception as err:
                    error = err
            if any_fallback:
                try:
                    return any_method(obj.__class__)(obj)
                except Exception as err:
                    error = err
            raise error or TypeError(
                f"Expected {Union[alternatives]}, found {obj.__class__}"
            )

        return method

    def _visit_conversion(
        self,
        tp: AnyType,
        conversion: Serialization,
        dynamic: bool,
        next_conversions: Optional[Conversions],
    ) -> SerializationMethod:
        with context_setter(self) as setter:
            if conversion.any_fallback is not None:
                setter._any_fallback = conversion.any_fallback
            if conversion.exclude_unset is not None:
                setter._exclude_unset = conversion.exclude_unset
            serialize_conv = self.visit_with_conv(
                conversion.target, sub_conversions(conversion, next_conversions)
            )

        converter = cast(Converter, conversion.converter)
        if converter is identity:
            method = serialize_conv
        else:

            def method(obj: Any) -> Any:
                return serialize_conv(converter(obj))

        return self._wrap_type_check(get_origin_or_type(tp), method)

    def visit(self, tp: AnyType) -> SerializationMethod:
        if tp == AliasedStr:
            return self._wrap_type_check(AliasedStr, self.aliaser)
        return super().visit(tp)


@cache
def serialization_method_factory(
    aliaser: Optional[Aliaser],
    any_fallback: Optional[bool],
    check_type: Optional[bool],
    conversions: Optional[Conversions],
    default_conversions: Optional[DefaultConversions],
    exclude_unset: Optional[bool],
) -> Callable[[AnyType], SerializationMethod]:
    @lru_cache
    def factory(tp: AnyType) -> SerializationMethod:
        from apischema import settings

        return SerializationMethodVisitor(
            opt_or(aliaser, settings.aliaser),
            opt_or(any_fallback, settings.serialization.any_fallback),
            opt_or(check_type, settings.serialization.check_type),
            opt_or(default_conversions, settings.serialization.default_conversions),
            opt_or(exclude_unset, settings.serialization.exclude_unset),
        ).visit_with_conv(tp, conversions)

    return factory


def serialization_method(
    type: AnyType,
    *,
    aliaser: Aliaser = None,
    any_fallback: bool = None,
    check_type: bool = None,
    conversions: Conversions = None,
    default_conversions: DefaultConversions = None,
    exclude_unset: bool = None,
) -> SerializationMethod:
    return serialization_method_factory(
        aliaser,
        any_fallback,
        check_type,
        conversions,
        default_conversions,
        exclude_unset,
    )(type)


NO_OBJ = object()


@overload
def serialize(
    type: AnyType,
    obj: Any,
    *,
    aliaser: Aliaser = None,
    any_fallback: bool = None,
    check_type: bool = None,
    conversions: Conversions = None,
    default_conversions: DefaultConversions = None,
    exclude_unset: bool = None,
) -> Any:
    ...


@overload
def serialize(
    obj: Any,
    *,
    aliaser: Aliaser = None,
    any_fallback: bool = True,
    check_type: bool = None,
    conversions: Conversions = None,
    default_conversions: DefaultConversions = None,
    exclude_unset: bool = None,
) -> Any:
    ...


def serialize(  # type: ignore
    type: AnyType = Any,
    obj: Any = NO_OBJ,
    *,
    aliaser: Aliaser = None,
    any_fallback: bool = None,
    check_type: bool = None,
    conversions: Conversions = None,
    default_conversions: DefaultConversions = None,
    exclude_unset: bool = None,
) -> Any:
    # Handle overloaded signature without type
    if obj is NO_OBJ:
        type, obj = Any, type
        if any_fallback is None:
            any_fallback = True
    return serialization_method_factory(
        aliaser=aliaser,
        any_fallback=any_fallback,
        check_type=check_type,
        conversions=conversions,
        default_conversions=default_conversions,
        exclude_unset=exclude_unset,
    )(type)(obj)
