"""Running every named synthetic order type as a plan of that type's preset."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

ROUTED_TYPES = (
    'account_conditional',
    'accumulation',
    'atr_trail',
    'attached_hedge',
    'basket',
    'bracket',
    'candle_close_stop',
    'chaser',
    'close_on_trigger',
    'closing_price',
    'cover',
    'cross_instrument',
    'daily_stop',
    'discretionary',
    'exposure_hedge',
    'freeze_slicer',
    'good_till_time',
    'grid',
    'gtt',
    'hidden_stop',
    'iceberg',
    'implementation_shortfall',
    'indicator_triggered',
    'ladder',
    'legged_spread',
    'limit_if_touched',
    'liquidity_seeking',
    'market_if_touched',
    'marketable_limit',
    'oca',
    'oco',
    'opening_auction',
    'oto',
    'participation',
    'peg',
    'post_only',
    'scale_out',
    'scale_with_profit_taker',
    'scheduled',
    'square_off',
    'stepped_stop',
    'stop_and_reverse',
    'strategy_stop',
    'time_stop',
    'trailing_entry',
    'trailing_stop',
    'twap',
    'two_sided_breakout',
    'two_sided_quote',
    'underlying_peg',
    'virtual_limit',
    'volatility',
    'vwap',
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
    """The rewriting of an intent for a named synthetic type into a plan of that type's preset.

    A caller names an order type, such as `bracket`, and the engine runs it as a `plan` whose one order names the type's preset with the caller's settings, so the caller's request is the same whichever way the engine runs it. Every type in `ROUTED_TYPES` has a preset of its own name, except `gtt`, whose preset is `good_till_triggered`. `simple` and `plan` are the only types the engine runs with classes of their own. The parent keeps the type's name as `routed_from`.

    `closes_position` and `reduce_only` are not settings of a type but flags the plan reads from the top of its parameters, so they stay beside the plan rather than going into the preset, which would refuse them as unknown settings.

    `hold_limits` is taken out of the caller's settings and put beside the plan too, where the plan reader reads it for the whole request. An intent that does not say is given a value when it arrives: for a named type, true when it is in `HOLDING_TYPES` and `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` is on; for a plan the caller wrote, the switch's own value. Writing the value into the order means the plan read again after a restart holds the same orders, even if the setting or `HOLDING_TYPES` has changed since. A `simple` order cannot be held, so `check_unrouted` refuses `hold_limits: true` for it rather than ignoring it.

    Attributes:
        hold_limits (bool): Whether orders may be held in the virtual order book, from `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS`.
    """

    def __init__(self, hold_limits=True):
        """Builds the routing.

        Args:
            hold_limits (bool): Whether orders may be held in the virtual order book.

        Returns:
            None: This method returns nothing.
        """
        self.hold_limits = hold_limits

    @staticmethod
    def preset_name(type_name):
        """The preset a named type is run as.

        Args:
            type_name (str): The type.

        Returns:
            str: The preset's name, the type's own except where `PRESET_NAMES_BY_TYPE` says otherwise.
        """
        return PRESET_NAMES_BY_TYPE.get(type_name, type_name)

    def routed(self, intent):
        """The intent to run: a copy whose order is a plan of the type's preset for a routed type, a plan with its `hold_limits` written in for a plan, and otherwise the intent unchanged.

        Args:
            intent (dict): The intent document.

        Returns:
            dict: The intent to run, with `closes_position`, `reduce_only` and `hold_limits` at the top of the plan's `synthetic` object, `hold_limits` given its default when the caller did not say.
        """
        named_type = intent.get('synthetic_type')
        if named_type == 'plan':
            return self.with_hold_limits(intent)
        if named_type not in ROUTED_TYPES:
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
        """Refuses `hold_limits: true` for a `simple` order, which is sent at once by definition.

        `hold_limits: false` asks for what a simple order does anyway.

        Args:
            intent (dict): The intent document, after `routed`.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when `hold_limits` is true for a simple order, or is not true or false.
        """
        named_type = intent.get('synthetic_type') or 'simple'
        if named_type != 'simple':
            return
        synthetic = (intent.get('body') or {}).get('synthetic')
        if not isinstance(synthetic, dict) or 'hold_limits' not in synthetic:
            return
        hold_limits = synthetic.get('hold_limits')
        if hold_limits is False:
            return
        if hold_limits is True:
            raise RefusedRequestError.refusal(
                'hold_limits asks for the order to be held until the market reaches it, but a simple order is sent at once; send it as a plain limit order or a plan to hold it',
                400,
                intent_id=intent.get('intent_id'),
            )
        raise RefusedRequestError.refusal(
            f'hold_limits is true or false, not {hold_limits!r}',
            400,
            intent_id=intent.get('intent_id'),
        )
