"""Sending orders of chosen synthetic types to the plan engine, as a plan of that type's preset, for the switch-over from the fixed types."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PRESET_NAMES,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

PRESET_NAMES_BY_TYPE = {
    'gtt': 'good_till_triggered',
}
ORDER_FLAGS = (
    'closes_position',
    'reduce_only',
)
HOLDING_TYPES = (
    'ladder',
    'scheduled',
    'good_till_time',
    'time_stop',
    'account_conditional',
    'limit_if_touched',
    'indicator_triggered',
    'cross_instrument',
    'gtt',
    'bracket',
    'cover',
    'scale_out',
    'oto',
    'oca',
    'scale_with_profit_taker',
    'freeze_slicer',
    'twap',
    'implementation_shortfall',
)


class PlanRouting:
    """Which of the fixed synthetic types are run as plans, and the rewriting of their intents.

    Each fixed type has a preset, of the same name except for `gtt`, whose preset is `good_till_triggered`, built to send the same broker requests. The switch-over moves one type at a time, after its preset has traded live: a type named in `UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES` has its intents rewritten into a `plan` whose one order names that preset with the caller's settings, so the caller's request does not change. A type not named keeps its fixed class. The setting is empty by default, so nothing moves until it is filled in, and a name that is not both a fixed type and a preset stops the engine from starting rather than being ignored.

    `closes_position` and `reduce_only` are not settings of a type but flags every type reads from the top of its parameters, so they stay there beside the plan rather than going into the preset, which would refuse them as unknown settings.

    A plan the caller wrote is given `hold_limits` too, by `with_hold_limits`: the master switch's value when the caller did not say.

    `hold_limits` is also taken out of the caller's settings and put beside the plan, where the plan reader reads it for the whole request. A routed order that does not say is given a value when it arrives: true for a type in `HOLDING_TYPES` while `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` is on, and false otherwise. Writing the value into the order means the plan read again after a restart holds the same orders, even if the setting or `HOLDING_TYPES` has changed since. A type that is not run as a plan cannot hold its orders, so `check_unrouted` refuses `hold_limits: true` for it rather than ignoring it.

    Attributes:
        type_names (list): The fixed types run as plans.
        hold_limits (bool): Whether routed types may hold their limit orders, from `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS`.
    """

    def __init__(self, type_names, hold_limits=True):
        """Builds the routing, checking every name.

        Args:
            type_names (list): The fixed types to run as plans; empty strings are ignored.
            hold_limits (bool): Whether routed types may hold their limit orders in the virtual order book.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When a name is not both a fixed synthetic type and a preset.
        """
        self.hold_limits = hold_limits
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
            dict: The intent to run, with `closes_position`, `reduce_only` and `hold_limits` at the top of the plan's `synthetic` object, `hold_limits` given its default when the caller did not say.
        """
        named_type = intent.get('synthetic_type')
        if named_type == 'plan':
            return self.with_hold_limits(intent)
        if named_type not in self.type_names:
            return intent
        body = dict(intent.get('body') or {})
        settings = dict(body.get('synthetic') or {})
        settings.pop('type', None)
        flags = {}
        for name in ORDER_FLAGS:
            if name in settings:
                flags[name] = settings.pop(name)
        if 'hold_limits' in settings:
            flags['hold_limits'] = settings.pop('hold_limits')
        else:
            flags['hold_limits'] = self.hold_limits and named_type in HOLDING_TYPES
        preset_name = self.preset_name(named_type)
        synthetic = {
            'type': 'plan',
            'plan': {
                'order': {
                    'presets': [
                        {
                            preset_name: settings,
                        },
                    ],
                },
            },
            'routed_from': named_type,
        }
        synthetic.update(flags)
        body['synthetic'] = synthetic
        routed = dict(intent)
        routed['synthetic_type'] = 'plan'
        routed['body'] = body
        return routed

    def with_hold_limits(self, intent):
        """A plan written by the caller, with `hold_limits` given its default when the caller did not say.

        A plan that does not say holds what it can while `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` is on. Writing the value in when the plan arrives means a plan recorded before plans were held by default, which has none, is still read as not held.

        Args:
            intent (dict): A `plan` intent.

        Returns:
            dict: The intent, or a copy with `hold_limits` beside the plan.
        """
        body = dict(intent.get('body') or {})
        synthetic = body.get('synthetic')
        if not isinstance(synthetic, dict) or 'hold_limits' in synthetic:
            return intent
        synthetic = dict(synthetic)
        synthetic['hold_limits'] = self.hold_limits
        body['synthetic'] = synthetic
        stamped = dict(intent)
        stamped['body'] = body
        return stamped

    def check_unrouted(self, intent):
        """Refuses `hold_limits: true` for an order the engine runs with a fixed type rather than as a plan.

        Only a plan can hold its orders in the virtual order book, so a fixed type asked to hold would otherwise send them at once without saying so. `hold_limits: false` asks for what a fixed type does anyway, and a plain limit order held as a `virtual_limit` is held whatever it says.

        Args:
            intent (dict): The intent document, after `routed`.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when `hold_limits` is true for a fixed type, or is not true or false.
        """
        named_type = intent.get('synthetic_type') or 'simple'
        if named_type in ('plan', 'virtual_limit'):
            return
        synthetic = (intent.get('body') or {}).get('synthetic')
        if not isinstance(synthetic, dict) or 'hold_limits' not in synthetic:
            return
        hold_limits = synthetic.get('hold_limits')
        if hold_limits is False:
            return
        if hold_limits is True:
            raise RefusedRequestError.refusal(
                f'hold_limits asks for the orders to be held until the market reaches them, which only an order run as a plan can do; {named_type} is not, so name it in UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES or send it without hold_limits',
                400,
                intent_id=intent.get('intent_id'),
            )
        raise RefusedRequestError.refusal(
            f'hold_limits is true or false, not {hold_limits!r}',
            400,
            intent_id=intent.get('intent_id'),
        )
