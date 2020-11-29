from typing import Optional, Union

from graphql import graphql_sync

from apischema import Undefined, UndefinedType, graphql_schema


def arg_is_absent(arg: Optional[Union[int, UndefinedType]] = Undefined) -> bool:
    return arg is Undefined


schema = graphql_schema(query=[arg_is_absent])
assert graphql_sync(schema, "{argIsAbsent}").data == {"argIsAbsent": True}
assert graphql_sync(schema, "{argIsAbsent(arg: null)}").data == {"argIsAbsent": False}
