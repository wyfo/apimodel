from collections.abc import Collection as Collection_
from dataclasses import is_dataclass
from enum import Enum
from typing import Any, Callable, Collection, Mapping, Optional, Sequence, Type, TypeVar

from apischema import settings
from apischema.aliases import Aliaser
from apischema.cache import cache
from apischema.conversions.conversions import (
    Conversions,
    HashableConversions,
    handle_container_conversions,
    resolve_conversions,
    to_hashable_conversions,
)
from apischema.conversions.dataclass_models import DataclassModel
from apischema.conversions.visitor import SerializationVisitor
from apischema.fields import FIELDS_SET_ATTR, fields_set
from apischema.objects import AliasedStr, ObjectField, ObjectWrapper, object_fields
from apischema.serialization.serialized_methods import get_serialized_methods
from apischema.types import PRIMITIVE_TYPES
from apischema.utils import Undefined, UndefinedType, get_origin_or_type
from apischema.visitor import Unsupported

T = TypeVar("T")

SerializationMethod = Callable[[T, bool], Any]


def serialize_object(cls: Type[T], aliaser: Aliaser) -> SerializationMethod[T]:
    fields: Sequence[ObjectField]
    if issubclass(cls, ObjectWrapper):
        cls, fields = cls.type, cls.fields  # type: ignore
    else:
        fields = list(object_fields(cls, serialization=True).values())
    normal_fields, aggregate_fields = [], []
    for field in fields:
        conversions = to_hashable_conversions(field.serialization)
        if field.is_aggregate:
            aggregate_fields.append((field.name, conversions))
        else:
            normal_fields.append((field.name, aliaser(field.alias), conversions))

    serialized_fields = [
        (aliaser(name), method.func, to_hashable_conversions(method.conversions))
        for name, (method, _) in get_serialized_methods(cls).items()
    ]

    def method(obj: T, exc_unset: bool) -> Any:
        normal_fields2, aggregate_fields2 = normal_fields, aggregate_fields
        if exc_unset and hasattr(obj, FIELDS_SET_ATTR):
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
        # aggregate before normal fields to avoid overloading a field with an aggregate
        for name, conv in aggregate_fields2:
            attr = getattr(obj, name)
            result.update(
                serialization_method(attr.__class__, conv, aliaser)(attr, exc_unset)
            )
        for name, alias, conv in normal_fields2:
            attr = getattr(obj, name)
            if attr is not Undefined:
                result[alias] = serialization_method(attr.__class__, conv, aliaser)(
                    attr, exc_unset
                )
        for alias, func, conv in serialized_fields:
            res = func(obj)
            if res is not Undefined:
                result[alias] = serialization_method(res.__class__, conv, aliaser)(
                    res, exc_unset
                )
        return result

    return method


def serialize_undefined(obj: Any, exc_unset: bool) -> Any:
    raise Unsupported(UndefinedType)


def serialization_method_factory(
    object_method: Callable[[Type[T], Aliaser], SerializationMethod[T]],
    undefined_method: SerializationMethod,
) -> Callable[
    [Type[T], Optional[HashableConversions], Aliaser], SerializationMethod[T]
]:
    @cache
    def get_method(
        cls: Type[T],
        conversions: Optional[HashableConversions],
        aliaser: Aliaser,
    ):
        if cls is UndefinedType:
            return undefined_method
        conversion, dynamic = SerializationVisitor.get_conversions(
            cls, resolve_conversions(conversions)
        )
        if conversion is not None:
            if isinstance(conversion.target, DataclassModel):
                return get_method(conversion.target.dataclass, None, aliaser)
            target_orig = get_origin_or_type(conversion.target)
            if isinstance(target_orig, type) and issubclass(target_orig, ObjectWrapper):
                return object_method(target_orig, aliaser)  # type: ignore
            else:
                converter = conversion.converter
                sub_conversions = handle_container_conversions(
                    conversion.target, conversion.sub_conversions, conversions, dynamic
                )
                exclude_unset = conversion.exclude_unset

                def method(obj: T, exc_unset: bool) -> Any:
                    if exclude_unset is not None:
                        exc_unset = exclude_unset
                    converted = converter(obj)  # type: ignore
                    return get_method(converted.__class__, sub_conversions, aliaser)(
                        converted, exc_unset
                    )

                return method
        if issubclass(cls, ObjectWrapper):  # must be before dataclass
            method = object_method(cls, aliaser)  # type: ignore
            return lambda obj, exc_unset: method(obj.wrapped, exc_unset)
        if is_dataclass(cls):
            return object_method(cls, aliaser)
        if issubclass(cls, Enum):
            return lambda obj, exc_unset: get_method(
                obj.value.__class__, None, aliaser
            )(obj.value, exc_unset)
        if issubclass(cls, AliasedStr):
            return lambda obj, _: aliaser(obj)
        if issubclass(cls, PRIMITIVE_TYPES):
            return lambda obj, _: obj
        if issubclass(cls, Mapping):
            return lambda obj, exc_unset: {
                get_method(key.__class__, conversions, aliaser)(
                    key, exc_unset
                ): get_method(value.__class__, conversions, aliaser)(value, exc_unset)
                for key, value in obj.items()
            }
        if issubclass(cls, tuple) and hasattr(cls, "_fields"):
            return object_method(cls, aliaser)  # type: ignore
        if issubclass(cls, Collection):
            return lambda obj, exc_unset: [
                get_method(elt.__class__, conversions, aliaser)(elt, exc_unset)
                for elt in obj
            ]
        raise Unsupported(cls)

    return get_method


serialization_method = serialization_method_factory(
    serialize_object, serialize_undefined
)


def serialize(
    obj: Any,
    *,
    conversions: Conversions = None,
    aliaser: Aliaser = None,
    exclude_unset: bool = None,
) -> Any:
    if aliaser is None:
        aliaser = settings.aliaser()
    if exclude_unset is None:
        exclude_unset = settings.exclude_unset
    if conversions is not None and isinstance(conversions, Collection_):
        conversions = tuple(conversions)
    return serialization_method(obj.__class__, conversions, aliaser)(obj, exclude_unset)
