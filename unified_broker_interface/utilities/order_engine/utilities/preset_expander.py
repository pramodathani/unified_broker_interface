"""Turning a named preset and its settings into the slot values a plan order runs on."""

TRIGGER_ON_FIELDS = {
    'last': 'last',
    'bid': 'bid',
    'ask': 'ask',
    'mid': 'mid',
    'double_last': 'last',
    'held': 'last',
}
TRIGGER_ON_CONFIRMATIONS = {
    'last': 'none',
    'bid': 'none',
    'ask': 'none',
    'mid': 'none',
    'double_last': 'double_last',
    'held': 'held',
}
WATCH_FIELDS = {
    'last_price': 'last',
    'average_price': 'average_price',
    'previous_close': 'previous_close',
    'best_bid': 'bid',
    'best_offer': 'ask',
    'mid': 'mid',
}
DEFAULT_BUFFER_TICKS = 2
PRESET_NAMES = (
    'simple',
    'market_if_touched',
    'limit_if_touched',
    'scheduled',
    'indicator_triggered',
    'cross_instrument',
    'hidden_stop',
    'oto',
    'oco',
    'bracket',
    'cover',
)
JOIN_PRESET_NAMES = (
    'oto',
    'oco',
    'bracket',
    'cover',
)
BACKSTOP_SETTINGS = (
    'backstop_price',
    'backstop_limit_price',
)
OTO_SETTINGS = (
    'transaction_type',
    'order_type',
    'price',
    'trigger_price',
)
OTO_SIDES = {
    'BUY': 'buy',
    'SELL': 'sell',
}


class PresetExpander:
    """Expands one preset, named after an existing synthetic type and taking that type's settings, into slot values.

    The slot values are written in the same form a caller would write them by hand, so the plan reader checks both the same way. Each preset has its own method, so what a preset means is read in one place. A setting a preset does not take is reported as a problem rather than ignored, and a preset's settings keep the names the existing type uses, so a caller moving from `market_if_touched` to a plan changes nothing but the wrapping.

    Attributes:
        problems (list): The problems found by the last `expand`, each a dictionary with `path`, `rule` and `message`.
    """

    def __init__(self):
        """Builds an expander that has found no problems.

        Returns:
            None: This method returns nothing.
        """
        self.problems = []

    def expand(self, name, settings, path):
        """The slot values one preset stands for.

        Args:
            name (str): The preset's name, one of `PRESET_NAMES`.
            settings (dict): The preset's settings.
            path (str): The preset's path in the plan, for problems.

        Returns:
            dict: Slot names to slot values, as a caller would write them; empty when there are problems.
        """
        self.problems = []
        if name == 'simple':
            return self._simple(settings, path)
        if name == 'market_if_touched':
            return self._market_if_touched(settings, path)
        if name == 'limit_if_touched':
            return self._limit_if_touched(settings, path)
        if name == 'scheduled':
            return self._scheduled(settings, path)
        if name == 'indicator_triggered':
            return self._indicator_triggered(settings, path)
        if name == 'cross_instrument':
            return self._cross_instrument(settings, path)
        return self._hidden_stop(settings, path)

    def is_join(self, name, settings):
        """Whether a preset stands for a join of several orders rather than for one order's slot values.

        Args:
            name (str): The preset's name.
            settings (dict): The preset's settings.

        Returns:
            bool: True for `oto`, `oco`, `bracket`, `cover`, and a `hidden_stop` with a backstop.
        """
        if name in JOIN_PRESET_NAMES:
            return True
        if name == 'hidden_stop':
            for setting in BACKSTOP_SETTINGS:
                if setting in settings:
                    return True
        return False

    def expand_join(self, name, settings, entry, path):
        """The plan tree a join preset stands for, built around the rest of the order it was named in.

        The rest of the order, its other presets and its own slot values, is the join's main order: the entry of a bracket, a cover or an OTO, and the engine-side stop of a hidden stop with a backstop. An OCO has no main order, so it cannot be named beside anything else.

        Args:
            name (str): The preset's name, for which `is_join` is True.
            settings (dict): The preset's settings.
            entry (dict): The order it was named in, without this preset.
            path (str): The preset's path in the plan, for problems.

        Returns:
            dict: The plan node, as a caller would write it; empty when there are problems.
        """
        self.problems = []
        if name == 'oto':
            return self._oto(settings, entry, path)
        if name == 'oco':
            return self._oco(settings, entry, path)
        if name == 'bracket':
            return self._bracket(settings, entry, path)
        if name == 'cover':
            return self._cover(settings, entry, path)
        return self._hidden_stop_with_backstop(settings, entry, path)

    def _oto(self, settings, entry, path):
        """Places the entry, and once it fills places the `then` order, sized to what filled and growing with it.

        Args:
            settings (dict): `then`, an order body without a quantity.
            entry (dict): The order it was named in.
            path (str): The preset's path.

        Returns:
            dict: A Then join.
        """
        self._refuse_unknown(settings, ('then',), path, 'oto')
        described = settings.get('then')
        if not isinstance(described, dict):
            self._add_problem(
                path,
                'missing_setting',
                'the oto preset needs then, the order to place once the first one fills',
            )
            return {}
        child = {}
        for setting in described:
            if setting not in OTO_SETTINGS:
                self._add_problem(
                    path,
                    'not_built',
                    f'an oto preset\'s then takes {", ".join(OTO_SETTINGS)} so far, not {setting!r}',
                )
        side = described.get('transaction_type')
        if side is not None:
            if side not in OTO_SIDES:
                self._add_problem(
                    path,
                    'bad_setting',
                    f'then.transaction_type must be BUY or SELL, not {side!r}',
                )
            else:
                child['side'] = OTO_SIDES[side]
        order_type = described.get('order_type')
        if order_type == 'SL':
            child['pricing'] = [
                {
                    'native_stop': {
                        'trigger_price': described.get('trigger_price'),
                        'limit_price': described.get('price'),
                    },
                },
            ]
        elif order_type == 'MARKET':
            child['pricing'] = [
                {
                    'fixed': {
                        'order_type': 'MARKET',
                    },
                },
            ]
        elif 'price' in described:
            child['pricing'] = [
                {
                    'fixed': {
                        'price': described['price'],
                    },
                },
            ]
        return {
            'then': {
                'first': {
                    'order': entry,
                },
                'each_fill': {
                    'order': child,
                },
            },
        }

    def _oco(self, settings, entry, path):
        """A stop and a target on a position already held, each shrinking as the other fills.

        Args:
            settings (dict): `stop_price` and `stop_limit_price`, `target_price`, or both.
            entry (dict): The order it was named in, which must hold nothing else.
            path (str): The preset's path.

        Returns:
            dict: The exits, as an Either join that reduces, or one order when only one exit is named.
        """
        self._refuse_unknown(settings, ('stop_price', 'stop_limit_price', 'target_price'), path, 'oco')
        if entry:
            self._add_problem(
                path,
                'nothing_to_merge_into',
                'the oco preset protects a position already held, so it has no order of its own for other presets or slot values to change',
            )
        return self._exits(settings, path, 'oco')

    def _bracket(self, settings, entry, path):
        """The entry, and once it fills, a stop and a target sized to what filled, each shrinking as the other fills.

        Args:
            settings (dict): `stop_price` and `stop_limit_price`, `target_price`, or both.
            entry (dict): The order it was named in.
            path (str): The preset's path.

        Returns:
            dict: A Then join whose child is the exits.
        """
        self._refuse_unknown(settings, ('stop_price', 'stop_limit_price', 'target_price'), path, 'bracket')
        exits = self._exits(settings, path, 'bracket')
        return {
            'then': {
                'first': {
                    'order': entry,
                },
                'each_fill': exits,
                'cancel_first_on_child_fill': True,
            },
        }

    def _cover(self, settings, entry, path):
        """The entry, and once it fills, a stop sized to what filled.

        Args:
            settings (dict): `stop_price` and `stop_limit_price`, both required.
            entry (dict): The order it was named in.
            path (str): The preset's path.

        Returns:
            dict: A Then join whose child is the stop.
        """
        self._refuse_unknown(settings, ('stop_price', 'stop_limit_price'), path, 'cover')
        if 'stop_price' not in settings:
            self._add_problem(
                path,
                'missing_setting',
                'the cover preset needs stop_price and stop_limit_price, because a cover order always carries a stop',
            )
        exits = self._exits(settings, path, 'cover')
        return {
            'then': {
                'first': {
                    'order': entry,
                },
                'each_fill': exits,
                'cancel_first_on_child_fill': True,
            },
        }

    def _hidden_stop_with_backstop(self, settings, entry, path):
        """The engine-side stop with a native backstop resting further away, where whichever acts first stops the other.

        Args:
            settings (dict): The hidden stop's settings with `backstop_price` and `backstop_limit_price`.
            entry (dict): The order it was named in.
            path (str): The preset's path.

        Returns:
            dict: An Either join that cancels, whose engine-side stop cancels the backstop before it is sent.
        """
        for setting in BACKSTOP_SETTINGS:
            if setting not in settings:
                self._add_problem(
                    path,
                    'missing_setting',
                    'a hidden stop\'s backstop needs both backstop_price and backstop_limit_price',
                )
                return {}
        stop_settings = {}
        for setting, value in settings.items():
            if setting not in BACKSTOP_SETTINGS:
                stop_settings[setting] = value
        stop = dict(entry)
        stop['presets'] = list(entry.get('presets') or []) + [
            {
                'hidden_stop': stop_settings,
            },
        ]
        return {
            'either': {
                'sibling_rule': 'cancel',
                'cancel_before_send': True,
                'children': [
                    {
                        'order': stop,
                    },
                    {
                        'order': {
                            'side': 'protect',
                            'pricing': [
                                {
                                    'native_stop': {
                                        'trigger_price': settings['backstop_price'],
                                        'limit_price': settings['backstop_limit_price'],
                                    },
                                },
                            ],
                        },
                    },
                ],
            },
        }

    def _exits(self, settings, path, name):
        """The stop and target a bracket, a cover or an OCO protects a position with.

        Args:
            settings (dict): `stop_price` and `stop_limit_price`, `target_price`, or both.
            path (str): The preset's path.
            name (str): The preset's name, for the message.

        Returns:
            dict: One order, or an Either join that reduces when there are two.
        """
        exits = []
        if 'stop_price' in settings:
            if 'stop_limit_price' not in settings:
                self._add_problem(
                    path,
                    'missing_setting',
                    'a stop needs stop_limit_price as well as stop_price: a stop-limit whose limit sits at its trigger will not fill when the price runs through it',
                )
            exits.append({
                'order': {
                    'side': 'protect',
                    'pricing': [
                        {
                            'native_stop': {
                                'trigger_price': settings['stop_price'],
                                'limit_price': settings.get('stop_limit_price'),
                            },
                        },
                    ],
                },
            })
        if 'target_price' in settings:
            exits.append({
                'order': {
                    'side': 'protect',
                    'pricing': [
                        {
                            'fixed': {
                                'price': settings['target_price'],
                            },
                        },
                    ],
                },
            })
        if not exits:
            self._add_problem(
                path,
                'missing_setting',
                f'the {name} preset needs a stop_price, a target_price, or both',
            )
            return {}
        if len(exits) == 1:
            return exits[0]
        return {
            'either': {
                'sibling_rule': 'reduce',
                'children': exits,
            },
        }

    def _simple(self, settings, path):
        """The simple preset, which has no slot values of its own.

        Args:
            settings (dict): The preset's settings, which must be empty.
            path (str): The preset's path.

        Returns:
            dict: No slot values.
        """
        self._refuse_unknown(settings, (), path, 'simple')
        return {}

    def _market_if_touched(self, settings, path):
        """Waits unseen for the price to touch a level, then sends a limit past the opposite touch.

        Args:
            settings (dict): `trigger_price`, and optionally `trigger_direction`, `trigger_on`, `hold_seconds` and `buffer_ticks`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger and `marketable` pricing.
        """
        self._refuse_unknown(
            settings,
            (
                'trigger_price',
                'trigger_direction',
                'trigger_on',
                'hold_seconds',
                'buffer_ticks',
            ),
            path,
            'market_if_touched',
        )
        return {
            'trigger': self._price_trigger(settings, path),
            'pricing': [
                {
                    'marketable': {
                        'buffer_ticks': settings.get('buffer_ticks', DEFAULT_BUFFER_TICKS),
                    },
                },
            ],
        }

    def _limit_if_touched(self, settings, path):
        """Waits for the price to touch a level, then rests a limit at another price.

        Args:
            settings (dict): `trigger_price` and `limit_price`, and optionally `trigger_direction`, `trigger_on` and `hold_seconds`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger and `fixed` pricing at the limit.
        """
        self._refuse_unknown(
            settings,
            (
                'trigger_price',
                'limit_price',
                'trigger_direction',
                'trigger_on',
                'hold_seconds',
            ),
            path,
            'limit_if_touched',
        )
        return {
            'trigger': self._price_trigger(settings, path),
            'pricing': [
                self._fixed_limit(settings, path, 'limit_if_touched'),
            ],
        }

    def _scheduled(self, settings, path):
        """Holds the order until a time of day.

        Args:
            settings (dict): `at_time`.
            path (str): The preset's path.

        Returns:
            dict: A `time_at` trigger.
        """
        self._refuse_unknown(settings, ('at_time',), path, 'scheduled')
        if 'at_time' not in settings:
            self._add_problem(
                path,
                'missing_setting',
                'the scheduled preset needs at_time, the time of day to place the order',
            )
            return {}
        return {
            'trigger': {
                'time_at': settings['at_time'],
            },
        }

    def _indicator_triggered(self, settings, path):
        """Sends a limit when a chosen field of the live quote crosses a level.

        Args:
            settings (dict): `watch_field`, `trigger_price` and `limit_price`, and optionally `trigger_direction`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger on that field and `fixed` pricing at the limit.
        """
        self._refuse_unknown(
            settings,
            (
                'watch_field',
                'trigger_price',
                'trigger_direction',
                'limit_price',
            ),
            path,
            'indicator_triggered',
        )
        watch_field = settings.get('watch_field')
        if watch_field not in WATCH_FIELDS:
            self._add_problem(
                path,
                'bad_setting',
                f'watch_field must be one of {", ".join(WATCH_FIELDS)}, not {watch_field!r}',
            )
            return {}
        trigger = {
            'level': settings.get('trigger_price'),
            'field': WATCH_FIELDS[watch_field],
        }
        if 'trigger_direction' in settings:
            trigger['direction'] = settings['trigger_direction']
        return {
            'trigger': {
                'price_crosses': trigger,
            },
            'pricing': [
                self._fixed_limit(settings, path, 'indicator_triggered'),
            ],
        }

    def _cross_instrument(self, settings, path):
        """Waits for another instrument's price to cross a level, then rests a limit on this one.

        Args:
            settings (dict): `watch_instrument_id`, `trigger_price` and `limit_price`, and optionally `trigger_direction`, `trigger_on` and `hold_seconds`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger on the watched instrument and `fixed` pricing at the limit.
        """
        self._refuse_unknown(
            settings,
            (
                'watch_instrument_id',
                'trigger_price',
                'limit_price',
                'trigger_direction',
                'trigger_on',
                'hold_seconds',
            ),
            path,
            'cross_instrument',
        )
        if not settings.get('watch_instrument_id'):
            self._add_problem(
                path,
                'missing_setting',
                'the cross_instrument preset needs watch_instrument_id, the instrument whose price is watched',
            )
            return {}
        trigger = self._price_trigger(settings, path)
        trigger['price_crosses']['instrument_id'] = settings['watch_instrument_id']
        return {
            'trigger': trigger,
            'pricing': [
                self._fixed_limit(settings, path, 'cross_instrument'),
            ],
        }

    def _hidden_stop(self, settings, path):
        """A stop kept in the engine, watching the touch the exit would trade against, which exits with a limit past it.

        Args:
            settings (dict): `trigger_price`, and optionally `trigger_direction` and `buffer_ticks`.
            path (str): The preset's path.

        Returns:
            dict: The `protect` side, a `price_crosses` trigger on the opposite touch and `marketable` pricing.
        """
        self._refuse_unknown(
            settings,
            (
                'trigger_price',
                'trigger_direction',
                'buffer_ticks',
            ),
            path,
            'hidden_stop',
        )
        trigger = {
            'level': settings.get('trigger_price'),
            'field': 'opposite_touch',
        }
        if 'trigger_direction' in settings:
            trigger['direction'] = settings['trigger_direction']
        return {
            'side': 'protect',
            'trigger': {
                'price_crosses': trigger,
            },
            'pricing': [
                {
                    'marketable': {
                        'buffer_ticks': settings.get('buffer_ticks', DEFAULT_BUFFER_TICKS),
                    },
                },
            ],
        }

    def _price_trigger(self, settings, path):
        """The `price_crosses` trigger the price-triggered presets share.

        Args:
            settings (dict): `trigger_price`, and optionally `trigger_direction`, `trigger_on` and `hold_seconds`.
            path (str): The preset's path.

        Returns:
            dict: The trigger, as a caller would write it.
        """
        trigger = {
            'level': settings.get('trigger_price'),
        }
        if 'trigger_direction' in settings:
            trigger['direction'] = settings['trigger_direction']
        trigger_on = settings.get('trigger_on', 'last')
        if trigger_on not in TRIGGER_ON_FIELDS:
            self._add_problem(
                path,
                'bad_setting',
                f'trigger_on must be one of {", ".join(TRIGGER_ON_FIELDS)}, not {trigger_on!r}',
            )
        else:
            trigger['field'] = TRIGGER_ON_FIELDS[trigger_on]
            trigger['confirm'] = TRIGGER_ON_CONFIRMATIONS[trigger_on]
        if 'hold_seconds' in settings:
            trigger['hold_seconds'] = settings['hold_seconds']
        return {
            'price_crosses': trigger,
        }

    def _fixed_limit(self, settings, path, name):
        """The `fixed` pricing at the preset's `limit_price`.

        Args:
            settings (dict): The preset's settings, holding `limit_price`.
            path (str): The preset's path.
            name (str): The preset's name, for the message.

        Returns:
            dict: The pricing value, as a caller would write it.
        """
        if 'limit_price' not in settings:
            self._add_problem(
                path,
                'missing_setting',
                f'the {name} preset needs limit_price, the limit it rests once triggered',
            )
        return {
            'fixed': {
                'price': settings.get('limit_price'),
            },
        }

    def _refuse_unknown(self, settings, known, path, name):
        """Reports every setting a preset does not take.

        Args:
            settings (dict): The preset's settings.
            known (tuple): The settings it takes.
            path (str): The preset's path.
            name (str): The preset's name, for the message.

        Returns:
            None: This method returns nothing.
        """
        for setting in settings:
            if setting not in known:
                if known:
                    takes = f'takes {", ".join(known)}'
                else:
                    takes = 'takes no settings'
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'the {name} preset {takes}, not {setting!r}',
                )

    def _add_problem(self, path, rule, message):
        """Records one problem.

        Args:
            path (str): The preset's path.
            rule (str): The name of the rule it breaks.
            message (str): What is wrong, for the caller.

        Returns:
            None: This method returns nothing.
        """
        self.problems.append({
            'path': path,
            'rule': rule,
            'message': message,
        })
