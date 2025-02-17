from collections import namedtuple
from typing import Any, Dict, Iterable, List, Tuple, Union

from starkware.cairo.lang.compiler.ast.cairo_types import CairoType, TypeFelt, TypePointer
from starkware.cairo.lang.compiler.identifier_definition import StructDefinition
from starkware.cairo.lang.compiler.parser import parse_type
from starkware.cairo.lang.compiler.type_system import mark_type_resolved
from starkware.starknet.public.abi import get_selector_from_name
from starkware.starknet.public.abi_structs import struct_definition_from_abi_entry

EventIdentifier = Union[str, int]


class StructManager:
    def __init__(self, abi: List[Any]):
        self._struct_definition_mapping = {
            abi_entry["name"]: struct_definition_from_abi_entry(abi_entry=abi_entry)
            for abi_entry in abi
            if abi_entry["type"] == "struct"
        }

        # Cached contract structs.
        self._contract_structs: Dict[str, type] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._struct_definition_mapping

    def get_struct_definition(self, name: str) -> StructDefinition:
        return self._struct_definition_mapping[name]

    def get_contract_struct(self, name: str) -> type:
        """
        Returns a named tuple representing the Cairo struct whose name is given.
        """
        if name not in self._contract_structs:
            # Cache contract struct.
            self._contract_structs[name] = self._build_contract_struct(name=name)

        return self._contract_structs[name]

    def _build_contract_struct(self, name: str) -> type:
        """
        Builds and returns a named tuple representing the Cairo struct whose name is given.
        """
        struct_def = self._struct_definition_mapping[name]
        return namedtuple(typename=name, field_names=struct_def.members.keys())


class EventManager:
    def __init__(self, abi: List[Any]):
        self._abi_event_mapping = {
            abi_entry["name"]: abi_entry for abi_entry in abi if abi_entry["type"] == "event"
        }

        # A mapping from event selector to event name.
        self._selector_to_name: Dict[int, str] = {
            get_selector_from_name(name): name for name in self._abi_event_mapping.keys()
        }

        # Cached contract events and argument types.
        self._contract_events: Dict[str, type] = {}
        self._event_name_to_argument_types: Dict[str, List[CairoType]] = {}

    def __contains__(self, identifier: EventIdentifier) -> bool:
        if isinstance(identifier, str):
            return identifier in self._abi_event_mapping

        return identifier in self._selector_to_name

    def get_contract_event(self, identifier: EventIdentifier) -> type:
        """
        Returns a named tuple representing the event whose name is given.
        """
        name = self._get_event_name(identifier=identifier)
        if name not in self._contract_events:
            # Cache event.
            self._process_event(name=name)

        return self._contract_events[name]

    def get_event_argument_types(self, identifier: EventIdentifier) -> List[CairoType]:
        """
        Returns the argument Cairo types of the given event.
        """
        name = self._get_event_name(identifier=identifier)
        if name not in self._event_name_to_argument_types:
            # Cache argument types.
            self._process_event(name=name)

        return self._event_name_to_argument_types[name]

    def _process_event(self, name: str):
        """
        Processes the given event and caches its argument types and its representative named tuple.
        """
        event_abi = self._abi_event_mapping[name]
        names, types = parse_arguments(arguments_abi=event_abi["keys"] + event_abi["data"])

        self._event_name_to_argument_types[name] = types
        self._contract_events[name] = namedtuple(typename=name, field_names=names)

    def _get_event_name(self, identifier: EventIdentifier) -> str:
        return identifier if isinstance(identifier, str) else self._selector_to_name[identifier]


def parse_arguments(arguments_abi: dict) -> Tuple[List[str], List[CairoType]]:
    """
    Given the input or output field of a StarkNet contract function ABI,
    computes the arguments that the python proxy function should accept.
    In particular, an array input that has two inputs in the
    original ABI (foo_len: felt, foo: felt*) will be converted to a single argument foo.

    Returns the argument names and their Cairo types in two separate lists.
    """
    arg_names: List[str] = []
    arg_types: List[CairoType] = []
    for arg_entry in arguments_abi:
        name = arg_entry["name"]
        arg_type = mark_type_resolved(parse_type(code=arg_entry["type"]))
        if isinstance(arg_type, TypePointer):
            size_arg_actual_name = arg_names.pop()
            actual_type = arg_types.pop()
            # Make sure the last argument was {name}_len, and remove it.
            size_arg_name = f"{name}_len"
            assert (
                size_arg_actual_name == size_arg_name
            ), f"Array size argument {size_arg_name} must appear right before {name}."

            assert isinstance(actual_type, TypeFelt), (
                f"Array size entry {size_arg_name} expected to be type felt. Got: "
                f"{actual_type.format()}."
            )

        arg_names.append(name)
        arg_types.append(arg_type)

    return arg_names, arg_types


def flatten(name: str, value: Union[Any, Iterable], max_depth: int = 30) -> List[Any]:
    # Use max_depth to avoid, for example, a list that points to itself.
    assert max_depth > 0, f"Exceeded maximun depth while parsing argument {name}."
    if not isinstance(value, Iterable):
        return [value]

    res = []
    for elm in value:
        res.extend(flatten(name=name, value=elm, max_depth=max_depth - 1))

    return res
