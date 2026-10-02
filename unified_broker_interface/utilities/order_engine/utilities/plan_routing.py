"""Sending orders of chosen synthetic types to the plan engine, as a plan of that type's preset, for the switch-over from the fixed types."""

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PRESET_NAMES,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

PRESET_NAMES_BY_TYPE = {
    'gtt': 'good_till_triggered',
}


class PlanRouting:
    """Which of the fixed synthetic types are run as plans, and the rewriting of their intents.

    Each fixed type has a preset, of the same name except for `gtt`, whose preset is `good_till_triggered`, built to send the same broker requests. The switch-over moves one type at a time, after its preset has traded live: a type named in `UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES` has its intents rewritten into a `plan` whose one order names that preset with the caller's settings, so the caller's request does not change. A type not named keeps its fixed class. The setting is empty by default, so nothing moves until it is filled in, and a name that is not both a fixed type and a preset stops the engine from starting rather than being ignored.

    Attributes:
        type_names (list): The fixed types run as plans.
    """

    def __init__(self, type_names):
        """Builds the routing, checking every name.

        Args:
            type_names (list): The fixed types to run as plans; empty strings are ignored.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When a name is not both a fixed synthetic type and a preset.
        """
        self.type_names = []
        for name in type_names:
            if not name:
                continue
            if name not in self.routable_names():
                routable = ', '.join(self.routable_names())
                raise ValueError(f'UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES names {name!r}, which is not a synthetic type with a plan preset; the types that can be run as plans are {routable}')
            self.type_names.append(name)

    @staticmethod
    def preset_name(type_name):
        """The preset a fixed type is run as.

        Args:
            type_name (str): The fixed type.

        Returns:
            str: The preset's name, the type's own except where `PRESET_NAMES_BY_TYPE` says otherwise.
        """
        return PRESET_NAMES_BY_TYPE.get(type_name, type_name)

    @staticmethod
    def routable_names():
        """Every fixed synthetic type that has a preset to run it as.

        Returns:
            list: The names, sorted.
        """
        names = []
        for name in SYNTHETIC_ORDER_CLASSES:
            if name in ('plan', 'simple'):
                continue
            if PlanRouting.preset_name(name) in PRESET_NAMES:
                names.append(name)
        return sorted(names)

    def routed(self, intent):
        """The intent to run: unchanged for a type not routed, and for a routed one a copy whose order is a plan of that type's preset.

        Args:
            intent (dict): The intent document.

        Returns:
            dict: The intent to run.
        """
        named_type = intent.get('synthetic_type')
        if named_type not in self.type_names:
            return intent
        body = dict(intent.get('body') or {})
        settings = dict(body.get('synthetic') or {})
        settings.pop('type', None)
        body['synthetic'] = {
            'type': 'plan',
            'plan': {
                'order': {
                    'presets': [
                        {
                            self.preset_name(named_type): settings,
                        },
                    ],
                },
            },
            'routed_from': named_type,
        }
        routed = dict(intent)
        routed['synthetic_type'] = 'plan'
        routed['body'] = body
        return routed
