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
    'trailing_stop',
    'trailing_entry',
    'iceberg',
    'twap',
    'vwap',
    'implementation_shortfall',
    'participation',
    'liquidity_seeking',
    'peg',
    'chaser',
    'post_only',
    'underlying_peg',
    'volatility',
    'discretionary',
    'atr_trail',
    'stepped_stop',
    'good_till_time',
    'time_stop',
    'basket',
    'oca',
    'close_on_trigger',
    'square_off',
    'stop_and_reverse',
    'accumulation',
    'oto',
    'oco',
    'bracket',
    'cover',
)
TRAILING_SETTINGS = (
    'trail_points',
    'trail_percent',
    'stop_limit_offset',
    'step_ticks',
    'activate_at',
)
ATR_TRAIL_SETTINGS = (
    'trail_points',
    'stop_limit_offset',
    'step_ticks',
    'activate_at',
    'bar_minutes',
    'periods',
    'atr_multiple',
)
STEPPED_STOP_SETTINGS = (
    'entry_price',
    'stop_price',
    'stop_limit_offset',
    'step_ticks',
    'rules',
)
MOST_CANDIDATES = 25
CANDIDATE_SETTINGS = (
    'instrument_id',
    'transaction_type',
    'product',
    'order_type',
    'validity',
    'quantity',
    'price',
    'trigger_price',
    'tag',
)
CANDIDATE_OVERRIDES = (
    'instrument_id',
    'transaction_type',
    'product',
    'validity',
    'quantity',
    'tag',
)
JOIN_PRESET_NAMES = (
    'accumulation',
    'basket',
    'oca',
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
        opening_side (str | None): BUY or SELL, the side of the caller's body, which a trailing stop's activation needs; None when it is not known.
        problems (list): The problems found by the last `expand`, each a dictionary with `path`, `rule` and `message`.
    """

    def __init__(self, opening_side=None):
        """Builds an expander that has found no problems.

        Args:
            opening_side (str | None): BUY or SELL, the side of the caller's body, or None when it is not known.

        Returns:
            None: This method returns nothing.
        """
        self.opening_side = opening_side
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
        if name == 'trailing_stop':
            return self._trailing(settings, path, 'trailing_stop')
        if name == 'trailing_entry':
            return self._trailing(settings, path, 'trailing_entry')
        if name == 'iceberg':
            return self._iceberg(settings, path)
        if name in ('twap', 'vwap', 'implementation_shortfall'):
            return self._timed(name, settings, path)
        if name == 'participation':
            return self._participation(settings, path)
        if name == 'liquidity_seeking':
            return self._liquidity_seeking(settings, path)
        if name == 'peg':
            return self._peg(settings, path)
        if name == 'chaser':
            return self._chaser(settings, path)
        if name == 'post_only':
            return self._post_only(settings, path)
        if name == 'underlying_peg':
            return self._underlying_peg(settings, path)
        if name == 'volatility':
            return self._volatility(settings, path)
        if name == 'discretionary':
            return self._discretionary(settings, path)
        if name == 'atr_trail':
            return self._atr_trail(settings, path)
        if name == 'stepped_stop':
            return self._stepped_stop(settings, path)
        if name == 'good_till_time':
            return self._good_till_time(settings, path)
        if name == 'time_stop':
            return self._time_stop(settings, path)
        if name == 'close_on_trigger':
            return self._close_on_trigger(settings, path)
        if name == 'square_off':
            return self._square_off(settings, path)
        if name == 'stop_and_reverse':
            return self._stop_and_reverse(settings, path)
        return self._hidden_stop(settings, path)

    def is_join(self, name, settings):
        """Whether a preset stands for a join of several orders rather than for one order's slot values.

        Args:
            name (str): The preset's name.
            settings (dict): The preset's settings.

        Returns:
            bool: True for `accumulation`, `basket`, `oca`, `oto`, `oco`, `bracket`, `cover`, a `hidden_stop` with a backstop, and a `stop_and_reverse` that closes before it reverses.
        """
        if name in JOIN_PRESET_NAMES:
            return True
        if name == 'stop_and_reverse' and settings.get('method', 'sequential') == 'sequential':
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
        if name == 'accumulation':
            return self._accumulation(settings, entry, path)
        if name == 'basket':
            return self._basket(settings, entry, path)
        if name == 'oca':
            return self._oca(settings, entry, path)
        if name == 'oto':
            return self._oto(settings, entry, path)
        if name == 'oco':
            return self._oco(settings, entry, path)
        if name == 'bracket':
            return self._bracket(settings, entry, path)
        if name == 'cover':
            return self._cover(settings, entry, path)
        if name == 'stop_and_reverse':
            return self._sequential_reverse(settings, entry, path)
        return self._hidden_stop_with_backstop(settings, entry, path)

    def _candidate_orders(self, settings, entry, path, name):
        """One order per candidate, each the rest of the order it was named in with the candidate's own instrument, side, quantity and prices.

        A candidate's `price` and `order_type` become `fixed` pricing, and with a `trigger_price` a `native_stop` at that trigger and limit, replacing whatever pricing the rest of the order gave.

        Args:
            settings (dict): The preset's settings, holding `candidates`.
            entry (dict): The order it was named in.
            path (str): The preset's path.
            name (str): The preset's name, for the messages.

        Returns:
            list: The plan nodes, one per candidate; empty when there are problems.
        """
        candidates = settings.get('candidates')
        if not isinstance(candidates, list) or not candidates or len(candidates) > MOST_CANDIDATES:
            self._add_problem(
                path,
                'missing_setting',
                f'the {name} preset needs candidates, a list of 1 to {MOST_CANDIDATES} orders, each naming its instrument_id',
            )
            return []
        nodes = []
        for index, candidate in enumerate(candidates):
            candidate_path = f'{path}.candidates.{index}'
            if not isinstance(candidate, dict) or not candidate.get('instrument_id'):
                self._add_problem(candidate_path, 'bad_setting', 'a candidate is an object naming its instrument_id')
                continue
            self._refuse_unknown(candidate, CANDIDATE_SETTINGS, candidate_path, 'candidate')
            order = dict(entry)
            for setting in CANDIDATE_OVERRIDES:
                if setting in candidate:
                    order[setting] = candidate[setting]
            if candidate.get('trigger_price') is not None:
                order['pricing'] = [
                    {
                        'native_stop': {
                            'trigger_price': candidate['trigger_price'],
                            'limit_price': candidate.get('price'),
                        },
                    },
                ]
            elif 'price' in candidate or 'order_type' in candidate:
                fixed = {}
                if 'price' in candidate:
                    fixed['price'] = candidate['price']
                if 'order_type' in candidate:
                    fixed['order_type'] = candidate['order_type']
                order['pricing'] = [
                    {
                        'fixed': fixed,
                    },
                ]
            nodes.append(
                {
                    'order': order,
                }
            )
        return nodes

    def _accumulation(self, settings, entry, path):
        """The order's quantity bought again and again, every `every_minutes`, `purchases` times, each purchase resting on its own side of the book no worse than the body's limit.

        Args:
            settings (dict): `every_minutes` and `purchases`.
            entry (dict): The order it was named in, which each purchase copies.
            path (str): The preset's path.

        Returns:
            dict: A Repeat join of a peg to the own touch that does not follow.
        """
        self._refuse_unknown(settings, ('every_minutes', 'purchases'), path, 'accumulation')
        purchase = dict(entry)
        purchase['pricing'] = [
            {
                'peg': {
                    'reference': 'own_touch',
                    'follows': False,
                    'within_body_price': True,
                },
            },
        ]
        return {
            'repeat': {
                'child': {
                    'order': purchase,
                },
                'times': settings.get('purchases'),
                'every_minutes': settings.get('every_minutes'),
            },
        }

    def _basket(self, settings, entry, path):
        """Several orders, usually on different instruments, placed at once at one broker that can afford them all.

        Args:
            settings (dict): `candidates`, and optionally `hedge_benefit`.
            entry (dict): The order it was named in, whose other presets and slot values every candidate shares.
            path (str): The preset's path.

        Returns:
            dict: A Together join that checks the group's margin.
        """
        self._refuse_unknown(settings, ('candidates', 'hedge_benefit'), path, 'basket')
        nodes = self._candidate_orders(settings, entry, path, 'basket')
        if self.problems:
            return {}
        return {
            'together': {
                'children': nodes,
                'group_margin': True,
                'hedge_benefit': settings.get('hedge_benefit') is True,
            },
        }

    def _oca(self, settings, entry, path):
        """Several candidate entries where the first to fill is the trade, and the others are cancelled.

        Args:
            settings (dict): `candidates`.
            entry (dict): The order it was named in, whose other presets and slot values every candidate shares.
            path (str): The preset's path.

        Returns:
            dict: An Either join that cancels.
        """
        self._refuse_unknown(settings, ('candidates',), path, 'oca')
        nodes = self._candidate_orders(settings, entry, path, 'oca')
        if self.problems:
            return {}
        if len(nodes) < 2:
            self._add_problem(path, 'bad_setting', 'the oca preset needs at least two candidates, since one cancels the others')
            return {}
        return {
            'either': {
                'children': nodes,
                'sibling_rule': 'cancel',
            },
        }

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

    def _trailing(self, settings, path, name):
        """A native stop-limit that trails the market: a trailing stop protecting a position, or a trailing entry opening one.

        With `activate_at`, nothing rests until the price reaches that level, usually the target, and the stop trails from there. A trailing stop's stop sits on the side that closes the position, so it activates when the price rises to the level for a long and falls to it for a short, which needs the side of the caller's order. A trailing entry's stop sits on the caller's own side, so it activates the other way, which is the default direction.

        Args:
            settings (dict): `trail_points` or `trail_percent`, `stop_limit_offset`, and optionally `step_ticks` and `activate_at`.
            path (str): The preset's path.
            name (str): `trailing_stop` or `trailing_entry`.

        Returns:
            dict: `trail` pricing, the `protect` side for a trailing stop, and a `price_crosses` trigger when it activates at a level.
        """
        self._refuse_unknown(settings, TRAILING_SETTINGS, path, name)
        return self._trailing_slots(settings, path, name == 'trailing_stop')

    def _trailing_slots(self, settings, path, protects):
        """The slot values of a trailing stop or a trailing entry, once its settings have been checked.

        Args:
            settings (dict): `trail_points` or `trail_percent`, `stop_limit_offset`, and optionally `step_ticks` and `activate_at`.
            path (str): The preset's path.
            protects (bool): True for a stop protecting a position, False for a trailing entry.

        Returns:
            dict: `trail` pricing, the `protect` side when it protects, and a `price_crosses` trigger when it activates at a level.
        """
        trail = {
            'limit_offset': settings.get('stop_limit_offset'),
            'step_ticks': settings.get('step_ticks', 1),
        }
        if 'trail_points' in settings:
            trail['points'] = settings['trail_points']
        if 'trail_percent' in settings:
            trail['percent'] = settings['trail_percent']
        slots = {
            'pricing': [
                {
                    'trail': trail,
                },
            ],
        }
        if protects:
            slots['side'] = 'protect'
        if 'activate_at' not in settings:
            return slots
        activation = {
            'level': settings['activate_at'],
        }
        if protects:
            if self.opening_side == 'BUY':
                activation['direction'] = 'at_or_above'
            elif self.opening_side == 'SELL':
                activation['direction'] = 'at_or_below'
            else:
                self._add_problem(
                    path,
                    'needs_side',
                    'a trailing stop that activates at a level needs to know the side of the order it protects',
                )
        slots['trigger'] = {
            'price_crosses': activation,
        }
        return slots

    def _atr_trail(self, settings, path):
        """A trailing stop that sits a multiple of the recent average range behind the market, and `trail_points` behind until enough bars have closed.

        Args:
            settings (dict): `trail_points` and `stop_limit_offset`, and optionally `step_ticks`, `activate_at`, `bar_minutes`, `periods` and `atr_multiple`.
            path (str): The preset's path.

        Returns:
            dict: `trail` pricing with `atr`, the `protect` side, and a trigger when it activates at a level.
        """
        self._refuse_unknown(settings, ATR_TRAIL_SETTINGS, path, 'atr_trail')
        slots = self._trailing_slots(settings, path, True)
        atr = {}
        if 'bar_minutes' in settings:
            atr['bar_minutes'] = settings['bar_minutes']
        if 'periods' in settings:
            atr['periods'] = settings['periods']
        if 'atr_multiple' in settings:
            atr['multiple'] = settings['atr_multiple']
        slots['pricing'][0]['trail']['atr'] = atr
        return slots

    def _stepped_stop(self, settings, path):
        """A stop protecting a position, moved by a table of profit milestones.

        Args:
            settings (dict): `entry_price`, `stop_price`, `stop_limit_offset` and `rules`, and optionally `step_ticks`.
            path (str): The preset's path.

        Returns:
            dict: The `protect` side and `stages` pricing.
        """
        self._refuse_unknown(settings, STEPPED_STOP_SETTINGS, path, 'stepped_stop')
        stages = {
            'entry_price': settings.get('entry_price'),
            'stop_price': settings.get('stop_price'),
            'limit_offset': settings.get('stop_limit_offset'),
            'rules': settings.get('rules'),
        }
        if 'step_ticks' in settings:
            stages['step_ticks'] = settings['step_ticks']
        return {
            'side': 'protect',
            'pricing': [
                {
                    'stages': stages,
                },
            ],
        }

    def _good_till_time(self, settings, path):
        """Works until a time of day, then cancels what rests, or with `at_expiry: market` makes it marketable.

        Args:
            settings (dict): `until_time`, and optionally `at_expiry`, `cancel` or `market`.
            path (str): The preset's path.

        Returns:
            dict: A lifetime ending `at_time`.
        """
        self._refuse_unknown(settings, ('until_time', 'at_expiry'), path, 'good_till_time')
        on_end = 'cancel'
        if settings.get('at_expiry') == 'market':
            on_end = 'marketable'
        elif settings.get('at_expiry') not in (None, 'cancel'):
            self._add_problem(path, 'bad_setting', f'at_expiry must be one of cancel, market, not {settings.get("at_expiry")!r}')
        return {
            'lifetime': [
                {
                    'at_time': settings.get('until_time'),
                    'on_end': on_end,
                },
            ],
        }

    def _time_stop(self, settings, path):
        """Closes what the order filled at a time of day, or a number of minutes after it was placed, cancelling what still rests first.

        Args:
            settings (dict): `until_time` or `minutes`.
            path (str): The preset's path.

        Returns:
            dict: A lifetime ending with `close_filled`.
        """
        self._refuse_unknown(settings, ('until_time', 'minutes'), path, 'time_stop')
        ending = {
            'on_end': 'close_filled',
        }
        if 'until_time' in settings:
            ending['at_time'] = settings['until_time']
        if 'minutes' in settings:
            ending['after_minutes'] = settings['minutes']
        return {
            'lifetime': [
                ending,
            ],
        }

    def _close_on_trigger(self, settings, path):
        """Waits for a price, then cancels what rests on the instrument and closes the whole position held then.

        Args:
            settings (dict): `trigger_price`, and optionally `trigger_direction`, `trigger_on` and `hold_seconds`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger, the `close` side and a quantity read from the position.
        """
        self._refuse_unknown(settings, ('trigger_price', 'trigger_direction', 'trigger_on', 'hold_seconds'), path, 'close_on_trigger')
        return {
            'trigger': self._price_trigger(settings, path),
            'side': 'close',
            'quantity': {
                'position': {},
            },
        }

    def _square_off(self, settings, path):
        """Closes every position on a product at a time of day, cancelling what rests on those instruments first.

        Args:
            settings (dict): `at_time`, and optionally `product`, default `intraday`, and `instrument_ids`.
            path (str): The preset's path.

        Returns:
            dict: A `time_at` trigger, the `close` side and a quantity read from every position held.
        """
        self._refuse_unknown(settings, ('at_time', 'product', 'instrument_ids'), path, 'square_off')
        position = {
            'product': str(settings.get('product') or 'intraday').lower(),
        }
        if settings.get('instrument_ids'):
            position['instrument_ids'] = settings['instrument_ids']
        else:
            position['every_instrument'] = True
        return {
            'trigger': {
                'time_at': settings.get('at_time'),
            },
            'side': 'close',
            'quantity': {
                'position': position,
            },
        }

    def _stop_and_reverse(self, settings, path):
        """Waits for a price, then sends one order for twice the position held, closing it and opening the reverse together.

        This is the `double` method; the default, `sequential`, is a join built by `expand_join`.

        Args:
            settings (dict): The price trigger's settings and `method: double`.
            path (str): The preset's path.

        Returns:
            dict: A `price_crosses` trigger, the `close` side and twice the position.
        """
        self._refuse_unknown(settings, ('trigger_price', 'trigger_direction', 'trigger_on', 'hold_seconds', 'method'), path, 'stop_and_reverse')
        if settings.get('method') != 'double':
            self._add_problem(path, 'bad_setting', f'method must be one of sequential, double, not {settings.get("method")!r}')
            return {}
        return {
            'trigger': self._price_trigger(settings, path),
            'side': 'close',
            'quantity': {
                'position': {
                    'ratio': 2,
                },
            },
        }

    def _sequential_reverse(self, settings, entry, path):
        """Waits for a price, closes the position held, and once the close is done opens the reverse for what it closed.

        Args:
            settings (dict): The price trigger's settings, and optionally `method: sequential`.
            entry (dict): The order it was named in, which becomes the close.
            path (str): The preset's path.

        Returns:
            dict: A Then join: the close, then on completion an order the other way sized to what closed.
        """
        self._refuse_unknown(settings, ('trigger_price', 'trigger_direction', 'trigger_on', 'hold_seconds', 'method'), path, 'stop_and_reverse')
        if self.opening_side not in OTO_SIDES:
            self._add_problem(path, 'needs_side', 'a stop and reverse opens the side opposite to the position, so it needs to know the side of the order that opened it')
            return {}
        if self.opening_side == 'BUY':
            reverse_side = 'sell'
        else:
            reverse_side = 'buy'
        close = dict(entry)
        presets = list(close.get('presets') or [])
        presets.append(
            {
                'close_on_trigger': self._without(settings, 'method'),
            }
        )
        close['presets'] = presets
        return {
            'then': {
                'first': {
                    'order': close,
                },
                'on_complete': {
                    'order': {
                        'side': reverse_side,
                        'pricing': [
                            {
                                'marketable': {
                                    'buffer_ticks': DEFAULT_BUFFER_TICKS,
                                },
                            },
                        ],
                    },
                },
            },
        }

    def _without(self, settings, name):
        """A copy of settings without one of them.

        Args:
            settings (dict): The settings.
            name (str): The setting to leave out.

        Returns:
            dict: The copy.
        """
        copied = dict(settings)
        copied.pop(name, None)
        return copied

    def _iceberg(self, settings, path):
        """Shows only part of the order at a time.

        Args:
            settings (dict): `slice_quantity`, and optionally `randomise_percent`.
            path (str): The preset's path.

        Returns:
            dict: `iceberg` execution.
        """
        self._refuse_unknown(settings, ('slice_quantity', 'randomise_percent'), path, 'iceberg')
        iceberg = {
            'visible_quantity': settings.get('slice_quantity'),
        }
        if 'randomise_percent' in settings:
            iceberg['randomise_percent'] = settings['randomise_percent']
        return {
            'execution': [
                {
                    'iceberg': iceberg,
                },
            ],
        }

    def _timed(self, name, settings, path):
        """Sends the order as slices on a clock: even for TWAP, by volume profile for VWAP, front-loaded for implementation shortfall.

        Args:
            name (str): `twap`, `vwap` or `implementation_shortfall`.
            settings (dict): `slices` and `over_minutes`, with `volume_profile` for VWAP and `urgency` for implementation shortfall.
            path (str): The preset's path.

        Returns:
            dict: The timed execution.
        """
        known = ['slices', 'over_minutes']
        execution_name = name
        if name == 'vwap':
            known.append('volume_profile')
        if name == 'implementation_shortfall':
            known.append('urgency')
            execution_name = 'front_loaded'
        self._refuse_unknown(settings, tuple(known), path, name)
        timed = {}
        for setting in known:
            if setting in settings:
                timed[setting] = settings[setting]
        return {
            'execution': [
                {
                    execution_name: timed,
                },
            ],
        }

    def _participation(self, settings, path):
        """Trades a share of the market's own volume, each slice a limit past the opposite touch.

        Args:
            settings (dict): `participation_percent`, and optionally `most_slices`.
            path (str): The preset's path.

        Returns:
            dict: `participation` execution and `marketable` pricing.
        """
        self._refuse_unknown(settings, ('participation_percent', 'most_slices'), path, 'participation')
        participation = {
            'percent': settings.get('participation_percent'),
        }
        if 'most_slices' in settings:
            participation['most_slices'] = settings['most_slices']
        return {
            'execution': [
                {
                    'participation': participation,
                },
            ],
            'pricing': [
                {
                    'marketable': {
                        'buffer_ticks': DEFAULT_BUFFER_TICKS,
                    },
                },
            ],
        }

    def _peg(self, settings, path):
        """Keeps a limit at a place in the book, held at a cap when one is given.

        Args:
            settings (dict): `reference`, `offset_ticks` and `cap_price`, all optional.
            path (str): The preset's path.

        Returns:
            dict: `peg` pricing, and a `cap` when `cap_price` is given.
        """
        self._refuse_unknown(settings, ('reference', 'offset_ticks', 'cap_price'), path, 'peg')
        peg = {}
        if 'reference' in settings:
            peg['reference'] = settings['reference']
        if 'offset_ticks' in settings:
            peg['offset_ticks'] = settings['offset_ticks']
        pricing = [
            {
                'peg': peg,
            },
        ]
        if 'cap_price' in settings:
            pricing.append(
                {
                    'cap': {
                        'worst_price': settings['cap_price'],
                    },
                }
            )
        return {
            'pricing': pricing,
        }

    def _chaser(self, settings, path):
        """Starts a limit on its own side of the book and walks it towards the other, held at a cap when one is given.

        Args:
            settings (dict): `step_ticks`, `step_seconds`, `cross_after_seconds` and `cap_price`, all optional.
            path (str): The preset's path.

        Returns:
            dict: `chase` pricing, and a `cap` when `cap_price` is given.
        """
        self._refuse_unknown(settings, ('step_ticks', 'step_seconds', 'cross_after_seconds', 'cap_price'), path, 'chaser')
        chase = {}
        for setting in ('step_ticks', 'step_seconds', 'cross_after_seconds'):
            if setting in settings:
                chase[setting] = settings[setting]
        pricing = [
            {
                'chase': chase,
            },
        ]
        if 'cap_price' in settings:
            pricing.append(
                {
                    'cap': {
                        'worst_price': settings['cap_price'],
                    },
                }
            )
        return {
            'pricing': pricing,
        }

    def _post_only(self, settings, path):
        """Sends a limit only when it would rest rather than trade.

        Args:
            settings (dict): `on_crossing`, optional.
            path (str): The preset's path.

        Returns:
            dict: The `post_only` guard.
        """
        self._refuse_unknown(settings, ('on_crossing',), path, 'post_only')
        post_only = {}
        if 'on_crossing' in settings:
            post_only['on_crossing'] = settings['on_crossing']
        return {
            'guards': [
                {
                    'post_only': post_only,
                },
            ],
        }

    def _followed_bounds(self, settings, followed):
        """Copies the bounds and step that the underlying peg and volatility types share into a pricing's settings.

        Args:
            settings (dict): The preset's settings.
            followed (dict): The pricing's settings, changed in place.

        Returns:
            None: This method returns nothing.
        """
        if 'lowest_price' in settings:
            followed['lowest'] = settings['lowest_price']
        if 'highest_price' in settings:
            followed['highest'] = settings['highest_price']
        if 'step_ticks' in settings:
            followed['step_ticks'] = settings['step_ticks']

    def _underlying_peg(self, settings, path):
        """Moves a resting limit by a delta times another instrument's move.

        Args:
            settings (dict): `watch_instrument_id` and `delta`, and optionally `lowest_price`, `highest_price` and `step_ticks`.
            path (str): The preset's path.

        Returns:
            dict: `follow_instrument` pricing.
        """
        self._refuse_unknown(settings, ('watch_instrument_id', 'delta', 'lowest_price', 'highest_price', 'step_ticks'), path, 'underlying_peg')
        followed = {
            'instrument_id': settings.get('watch_instrument_id'),
            'delta': settings.get('delta'),
        }
        self._followed_bounds(settings, followed)
        return {
            'pricing': [
                {
                    'follow_instrument': followed,
                },
            ],
        }

    def _volatility(self, settings, path):
        """Prices an option from an implied volatility, kept current as the underlying moves.

        Args:
            settings (dict): `watch_instrument_id` and `volatility`, and optionally `interest_rate`, `lowest_price`, `highest_price` and `step_ticks`.
            path (str): The preset's path.

        Returns:
            dict: `option_model` pricing.
        """
        self._refuse_unknown(settings, ('watch_instrument_id', 'volatility', 'interest_rate', 'lowest_price', 'highest_price', 'step_ticks'), path, 'volatility')
        modelled = {
            'instrument_id': settings.get('watch_instrument_id'),
            'volatility': settings.get('volatility'),
        }
        if 'interest_rate' in settings:
            modelled['interest_rate'] = settings['interest_rate']
        self._followed_bounds(settings, modelled)
        return {
            'pricing': [
                {
                    'option_model': modelled,
                },
            ],
        }

    def _discretionary(self, settings, path):
        """Shows the body's price and quietly takes a better one within a distance.

        Args:
            settings (dict): `discretion_points`, and optionally `discretion_quantity`.
            path (str): The preset's path.

        Returns:
            dict: The `discretion` modifier, beside the body's own price.
        """
        self._refuse_unknown(settings, ('discretion_points', 'discretion_quantity'), path, 'discretionary')
        discretion = {
            'points': settings.get('discretion_points'),
        }
        if 'discretion_quantity' in settings:
            discretion['quantity'] = settings['discretion_quantity']
        return {
            'pricing': [
                {
                    'discretion': discretion,
                },
            ],
        }

    def _liquidity_seeking(self, settings, path):
        """Shows nothing, and strikes at its limit when enough size appears there.

        Args:
            settings (dict): `limit_price` and `minimum_quantity`.
            path (str): The preset's path.

        Returns:
            dict: `book_depth` execution and `fixed` pricing at the limit.
        """
        self._refuse_unknown(settings, ('limit_price', 'minimum_quantity'), path, 'liquidity_seeking')
        return {
            'execution': [
                {
                    'book_depth': {
                        'limit_price': settings.get('limit_price'),
                        'minimum_quantity': settings.get('minimum_quantity'),
                    },
                },
            ],
            'pricing': [
                {
                    'fixed': {
                        'price': settings.get('limit_price'),
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
