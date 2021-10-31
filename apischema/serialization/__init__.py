import collections.abc
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from itertools import starmap
from typing import (
    Any,
    Callable,
    Collection,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from apischema.aliases import Aliaser
from apischema.cache import cache
from apischema.conversions.conversions import AnyConversion, DefaultConversion
from apischema.conversions.utils import Converter
from apischema.conversions.visitor import (
    Serialization,
    SerializationVisitor,
    sub_conversion,
)
from apischema.fields import support_fields_set
from apischema.objects import AliasedStr, ObjectField
from apischema.objects.visitor import SerializationObjectVisitor
from apischema.ordering import Ordering, sort_by_order
from apischema.recursion import RecursiveConversionsVisitor
from apischema.serialization.methods import (
    AnyFallback,
    AnyMethod,
    BaseField,
    BoolMethod,
    CheckedTupleMethod,
    ClassMethod,
    ClassWithFieldsSetMethod,
    CollectionMethod,
    ComplexField,
    ConversionMethod,
    DictMethod,
    EnumMethod,
    Fallback,
    FloatMethod,
    IdentityField,
    IdentityMethod,
    IntMethod,
    ListMethod,
    MappingMethod,
    NoFallback,
    NoneMethod,
    OptionalMethod,
    RecMethod,
    SerializationMethod,
    SerializedField,
    SimpleField,
    StrMethod,
    TupleMethod,
    TypeCheckIdentityMethod,
    TypeCheckMethod,
    TypedDictMethod,
    TypedDictWithAdditionalMethod,
    UnionAlternative,
    UnionMethod,
    ValueMethod,
    WrapperMethod,
)
from apischema.serialization.serialized_methods import get_serialized_methods
from apischema.types import AnyType, NoneType, Undefined, UndefinedType
from apischema.typing import is_new_type, is_type, is_type_var, is_typed_dict
from apischema.utils import (
    Lazy,
    as_predicate,
    deprecate_kwargs,
    get_origin_or_type,
    get_origin_or_type2,
    identity,
    is_union_of,
    opt_or,
)
from apischema.visitor import Unsupported

IDENTITY_METHOD = IdentityMethod()

METHODS = {
    identity: IDENTITY_METHOD,
    list: ListMethod(),
    dict: DictMethod(),
    str: StrMethod(),
    int: IntMethod(),
    bool: BoolMethod(),
    float: FloatMethod(),
    NoneType: NoneMethod(),
}

SerializationMethodFactory = Callable[[AnyType], SerializationMethod]

T = TypeVar("T")


def expected_class(tp: AnyType) -> type:
    origin = get_origin_or_type2(tp)
    if origin is NoneType:
        return NoneType
    elif is_typed_dict(origin):
        return collections.abc.Mapping
    elif is_type(origin):
        return origin
    elif is_new_type(origin):
        return expected_class(origin.__supertype__)
    elif is_type_var(origin) or origin is Any:
        return object
    else:
        raise TypeError(f"{tp} is not supported in union serialization")


@dataclass(frozen=True)
class PassThroughOptions:
    any: bool = False
    collections: bool = False
    enums: bool = False
    types: Union[Collection[AnyType], Callable[[AnyType], bool]] = ()

    def __post_init__(self):
        object.__setattr__(self, "types", as_predicate(self.types))


@dataclass
class FieldToOrder:
    name: str
    ordering: Optional[Ordering]
    field: BaseField


class SerializationMethodVisitor(
    RecursiveConversionsVisitor[Serialization, SerializationMethod],
    SerializationVisitor[SerializationMethod],
    SerializationObjectVisitor[SerializationMethod],
):
    use_cache: bool = True

    def __init__(
        self,
        additional_properties: bool,
        aliaser: Aliaser,
        check_type: bool,
        default_conversion: DefaultConversion,
        exclude_defaults: bool,
        exclude_none: bool,
        exclude_unset: bool,
        fall_back_on_any: bool,
        pass_through_options: PassThroughOptions,
    ):
        super().__init__(default_conversion)
        self.additional_properties = additional_properties
        self.aliaser = aliaser
        self.check_type = check_type
        self.exclude_defaults = exclude_defaults
        self.exclude_none = exclude_none
        self.exclude_unset = exclude_unset
        self.fall_back_on_any = fall_back_on_any
        self.pass_through_options = pass_through_options
        self.pass_through_type = as_predicate(self.pass_through_options.types)

    @property
    def _factory(self) -> SerializationMethodFactory:
        return serialization_method_factory(
            self.additional_properties,
            self.aliaser,
            self.check_type,
            self._conversion,
            self.default_conversion,
            self.exclude_defaults,
            self.exclude_none,
            self.exclude_unset,
            self.fall_back_on_any,
            self.pass_through_options,
        )

    def visit_not_recursive(self, tp: AnyType):
        return self._factory(tp) if self.use_cache else super().visit_not_recursive(tp)

    def _recursive_result(self, lazy: Lazy[SerializationMethod]) -> SerializationMethod:
        return RecMethod(lazy)

    def any(self) -> SerializationMethod:
        if self.pass_through_options.any:
            return IDENTITY_METHOD
        return AnyMethod(self._factory)

    def _any_fallback(self, tp: AnyType) -> Fallback:
        return AnyFallback(self.any()) if self.fall_back_on_any else NoFallback(tp)

    def _wrap(self, tp: AnyType, method: SerializationMethod) -> SerializationMethod:
        if not self.check_type:
            return method
        elif method is IDENTITY_METHOD:
            return TypeCheckIdentityMethod(expected_class(tp), self._any_fallback(tp))
        else:
            return TypeCheckMethod(expected_class(tp), self._any_fallback(tp), method)

    def collection(
        self, cls: Type[Collection], value_type: AnyType
    ) -> SerializationMethod:
        value_method = self.visit(value_type)

        method: SerializationMethod
        if value_method is not IDENTITY_METHOD:
            return CollectionMethod(value_method)
        elif issubclass(cls, (list, tuple)) or (
            self.pass_through_options.collections
            and not issubclass(cls, collections.abc.Set)
        ):
            method = IDENTITY_METHOD
        else:
            method = METHODS[list]

        return self._wrap(cls, method)

    def enum(self, cls: Type[Enum]) -> SerializationMethod:
        method: SerializationMethod
        if self.pass_through_options.enums or issubclass(cls, (int, str)):
            method = IDENTITY_METHOD
        else:
            any_method = self.any()
            if any_method is IDENTITY_METHOD or all(
                m is IDENTITY_METHOD
                for m in map(self.visit, {elt.value.__class__ for elt in cls})
            ):
                method = ValueMethod()
            else:
                assert isinstance(any_method, AnyMethod)
                method = EnumMethod(any_method)
        return self._wrap(cls, method)

    def literal(self, values: Sequence[Any]) -> SerializationMethod:
        if self.pass_through_options.enums or all(
            isinstance(v, (int, str)) for v in values
        ):
            return IDENTITY_METHOD
        else:
            return self.any()

    def mapping(
        self, cls: Type[Mapping], key_type: AnyType, value_type: AnyType
    ) -> SerializationMethod:
        key_method, value_method = self.visit(key_type), self.visit(value_type)
        method: SerializationMethod
        if key_method is not IDENTITY_METHOD or value_method is not IDENTITY_METHOD:
            method = MappingMethod(key_method, value_method)
        elif self.pass_through_options.collections or issubclass(cls, dict):
            method = IDENTITY_METHOD
        else:
            method = METHODS[dict]

        return self._wrap(cls, method)

    def object(self, tp: AnyType, fields: Sequence[ObjectField]) -> SerializationMethod:
        cls = get_origin_or_type(tp)
        fields_to_order = []
        for field in fields:
            field_alias = self.aliaser(field.alias) if not field.is_aggregate else None
            field_method = self.visit_with_conv(field.type, field.serialization)
            field_default = ... if field.required else field.get_default()
            base_field: BaseField
            if field_alias is None or field.skippable(
                self.exclude_defaults, self.exclude_none
            ):
                base_field = ComplexField(
                    field.name,
                    field_alias,  # type: ignore
                    field.required,
                    field_method,
                    field.skip.serialization_if,
                    is_union_of(field.type, UndefinedType)
                    or field_default is Undefined,
                    (is_union_of(field.type, NoneType) and self.exclude_none)
                    or field.none_as_undefined
                    or (field_default is None and self.exclude_defaults),
                    (field.skip.serialization_default or self.exclude_defaults)
                    and field_default not in (None, Undefined),
                    field_default,
                )
            elif field_method is IDENTITY_METHOD:
                base_field = IdentityField(field.name, field_alias, field.required)
            else:
                base_field = SimpleField(
                    field.name, field_alias, field.required, field_method
                )
            fields_to_order.append(FieldToOrder(field.name, field.ordering, base_field))
        for serialized, types in get_serialized_methods(tp):
            ret_type = types["return"]
            fields_to_order.append(
                FieldToOrder(
                    serialized.func.__name__,
                    serialized.ordering,
                    SerializedField(
                        self.aliaser(serialized.alias),
                        serialized.func,
                        is_union_of(ret_type, UndefinedType),
                        is_union_of(ret_type, NoneType) and self.exclude_none,
                        self.visit_with_conv(ret_type, serialized.conversion),
                    ),
                )
            )

        fields_to_order = sort_by_order(  # type: ignore
            cls, fields_to_order, lambda f: f.name, lambda f: f.ordering
        )
        base_fields = tuple(f.field for f in fields_to_order)
        method: SerializationMethod
        if is_typed_dict(cls):
            if self.additional_properties:
                method = TypedDictWithAdditionalMethod(
                    base_fields, {f.name for f in fields}, self.any()
                )
            else:
                method = TypedDictMethod(base_fields)
        elif self.exclude_unset and support_fields_set(cls):
            method = ClassWithFieldsSetMethod(base_fields)
        else:
            method = ClassMethod(base_fields)
        return self._wrap(cls, method)

    def primitive(self, cls: Type) -> SerializationMethod:
        return self._wrap(cls, IDENTITY_METHOD)

    def subprimitive(self, cls: Type, superclass: Type) -> SerializationMethod:
        if cls is AliasedStr:
            return WrapperMethod(self.aliaser)
        else:
            return super().subprimitive(cls, superclass)

    def tuple(self, types: Sequence[AnyType]) -> SerializationMethod:
        elt_methods = tuple(map(self.visit, types))
        method: SerializationMethod
        if all(method is IDENTITY_METHOD for method in elt_methods):
            method = IDENTITY_METHOD
        else:
            method = TupleMethod(elt_methods)
        if self.check_type:
            method = CheckedTupleMethod(len(types), method)
        return self._wrap(tuple, method)

    def union(self, types: Sequence[AnyType]) -> SerializationMethod:
        alternatives = []
        for tp in types:
            with suppress(Unsupported):
                # Do NOT use UnionAlternative here because it would erase type checking
                # (forward and optional cases would then loose their type checking)
                alternatives.append((expected_class(tp), self.visit(tp)))
        if not alternatives:
            raise Unsupported(Union[tuple(types)])  # type: ignore
        elif len(alternatives) == 1:
            return alternatives[0][1]
        elif all(alt[1] is IDENTITY_METHOD for alt in alternatives):
            return IDENTITY_METHOD
        elif len(alternatives) == 2 and NoneType in types:
            return OptionalMethod(
                next(meth for cls, meth in alternatives if cls is not NoneType)
            )
        else:
            fallback = self._any_fallback(Union[types])
            return UnionMethod(tuple(starmap(UnionAlternative, alternatives)), fallback)

    def unsupported(self, tp: AnyType) -> SerializationMethod:
        try:
            return super().unsupported(tp)
        except Unsupported:
            if self.fall_back_on_any and is_type(tp):
                if issubclass(tp, Mapping):
                    return self.visit(Mapping[Any, Any])
                elif issubclass(tp, Collection):
                    return self.visit(Collection[Any])
            raise

    def _visit_conversion(
        self,
        tp: AnyType,
        conversion: Serialization,
        dynamic: bool,
        next_conversion: Optional[AnyConversion],
    ) -> SerializationMethod:
        conv_method = self.visit_with_conv(
            conversion.target, sub_conversion(conversion, next_conversion)
        )
        converter = cast(Converter, conversion.converter)
        if converter is identity:
            method = conv_method
        elif conv_method is identity:
            method = METHODS.get(converter, WrapperMethod(converter))
        else:
            method = ConversionMethod(converter, conv_method)
        return self._wrap(tp, method)

    def visit_conversion(
        self,
        tp: AnyType,
        conversion: Optional[Serialization],
        dynamic: bool,
        next_conversion: Optional[AnyConversion] = None,
    ) -> SerializationMethod:
        if not dynamic and self.pass_through_type(tp):
            return self._wrap(tp, IDENTITY_METHOD)
        else:
            return super().visit_conversion(tp, conversion, dynamic, next_conversion)


@cache
def serialization_method_factory(
    additional_properties: bool,
    aliaser: Aliaser,
    check_type: bool,
    conversion: Optional[AnyConversion],
    default_conversion: DefaultConversion,
    exclude_defaults: bool,
    exclude_none: bool,
    exclude_unset: bool,
    fall_back_on_any: bool,
    pass_through: PassThroughOptions,
) -> SerializationMethodFactory:
    @lru_cache()
    def factory(tp: AnyType) -> SerializationMethod:
        return SerializationMethodVisitor(
            additional_properties,
            aliaser,
            check_type,
            default_conversion,
            exclude_defaults,
            exclude_none,
            exclude_unset,
            fall_back_on_any,
            pass_through,
        ).visit_with_conv(tp, conversion)

    return factory


def serialization_method(
    type: AnyType,
    *,
    additional_properties: bool = None,
    aliaser: Aliaser = None,
    check_type: bool = None,
    conversion: AnyConversion = None,
    default_conversion: DefaultConversion = None,
    exclude_defaults: bool = None,
    exclude_none: bool = None,
    exclude_unset: bool = None,
    fall_back_on_any: bool = None,
    pass_through: PassThroughOptions = None,
) -> Callable[[Any], Any]:
    from apischema import settings

    return serialization_method_factory(
        opt_or(additional_properties, settings.additional_properties),
        opt_or(aliaser, settings.aliaser),
        opt_or(check_type, settings.serialization.check_type),
        conversion,
        opt_or(default_conversion, settings.serialization.default_conversion),
        opt_or(exclude_defaults, settings.serialization.exclude_defaults),
        opt_or(exclude_none, settings.serialization.exclude_none),
        opt_or(exclude_unset, settings.serialization.exclude_unset),
        opt_or(fall_back_on_any, settings.serialization.fall_back_on_any),
        opt_or(pass_through, settings.serialization.pass_through),
    )(type).serialize


NO_OBJ = object()


@overload
def serialize(
    type: AnyType,
    obj: Any,
    *,
    additional_properties: bool = None,
    aliaser: Aliaser = None,
    check_type: bool = None,
    conversion: AnyConversion = None,
    default_conversion: DefaultConversion = None,
    exclude_defaults: bool = None,
    exclude_none: bool = None,
    exclude_unset: bool = None,
    fall_back_on_any: bool = None,
    pass_through: PassThroughOptions = None,
) -> Any:
    ...


@overload
def serialize(
    obj: Any,
    *,
    additional_properties: bool = None,
    aliaser: Aliaser = None,
    check_type: bool = None,
    conversion: AnyConversion = None,
    default_conversion: DefaultConversion = None,
    exclude_defaults: bool = None,
    exclude_none: bool = None,
    exclude_unset: bool = None,
    fall_back_on_any: bool = True,
    pass_through: PassThroughOptions = None,
) -> Any:
    ...


@deprecate_kwargs({"conversions": "conversion"})  # type: ignore
def serialize(
    type: AnyType = Any,
    obj: Any = NO_OBJ,
    *,
    additional_properties: bool = None,
    aliaser: Aliaser = None,
    check_type: bool = None,
    conversion: AnyConversion = None,
    default_conversion: DefaultConversion = None,
    exclude_defaults: bool = None,
    exclude_none: bool = None,
    exclude_unset: bool = None,
    fall_back_on_any: bool = None,
    pass_through: PassThroughOptions = None,
) -> Any:
    # Handle overloaded signature without type
    if obj is NO_OBJ:
        type, obj = Any, type
        if fall_back_on_any is None:
            fall_back_on_any = True
    return serialization_method(
        type,
        additional_properties=additional_properties,
        aliaser=aliaser,
        check_type=check_type,
        conversion=conversion,
        default_conversion=default_conversion,
        exclude_defaults=exclude_defaults,
        exclude_none=exclude_none,
        exclude_unset=exclude_unset,
        fall_back_on_any=fall_back_on_any,
        pass_through=pass_through,
    )(obj)


def serialization_default(
    *,
    additional_properties: bool = None,
    aliaser: Aliaser = None,
    default_conversion: DefaultConversion = None,
    exclude_defaults: bool = None,
    exclude_none: bool = None,
    exclude_unset: bool = None,
) -> Callable[[Any], Any]:
    from apischema import settings

    factory = serialization_method_factory(
        opt_or(additional_properties, settings.additional_properties),
        opt_or(aliaser, settings.aliaser),
        False,
        None,
        opt_or(default_conversion, settings.serialization.default_conversion),
        opt_or(exclude_defaults, settings.serialization.exclude_defaults),
        opt_or(exclude_none, settings.serialization.exclude_none),
        opt_or(exclude_unset, settings.serialization.exclude_unset),
        False,
        PassThroughOptions(any=True),
    )

    def method(obj: Any) -> Any:
        return factory(obj.__class__).serialize(obj)

    return method
