"""Reading a caller's plan into the parts that run it, and every problem that stops it running."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.condition_group import (
    ConditionGroup,
)
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.marketable_pricing import (
    MarketablePricing,
)
from unified_broker_interface.utilities.order_engine.utilities.native_stop_pricing import (
    NativeStopPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)
from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PRESET_NAMES,
    PresetExpander,
)
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    CONFIRMATIONS,
    DIRECTIONS,
    FIELDS,
    PriceCrossesCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.time_condition import (
    KINDS,
    TimeCondition,
)

JOIN_NAMES = (
    'then',
    'either',
    'together',
    'using',
    'repeat',
    'sequence',
)
ORDER_SETTINGS = (
    'presets',
    'trigger',
    'side',
    'pricing',
)
SIDES = (
    'buy',
    'sell',
    'protect',
)
PRICE_CROSSES_SETTINGS = (
    'level',
    'direction',
    'field',
    'instrument_id',
    'confirm',
    'hold_seconds',
)
ORDER_TYPES = (
    'LIMIT',
    'MARKET',
)


class PlanReader:
    """Reads the `plan` object of a `plan` order into its parts, collecting every problem rather than stopping at the first.

    A plan is a tree. Each node is an object holding exactly one key: `order` for a leaf, or the name of a join for a branch. Each part gets a path from its place in the tree, starting at `root`, which is how its broker orders and its state are told apart from every other part's.

    An order takes `presets`, a list of named presets each standing for slot values, and may give slot values of its own: `trigger`, `side` and `pricing`. They are merged in order, presets first and the order's own values last. Triggers from several sources are joined with `all`. A later pricing setter replaces an earlier one, which is reported in `warnings` rather than refused, because naming a preset for its trigger and then choosing another price is a normal thing to want. Two different sides are refused, because there is no sensible way to join them.

    The joins are named in the design and recognised here, so a caller who writes one is told it is not built yet rather than that it is unknown.

    Attributes:
        problems (list): Every problem found by the last `read`, each a dictionary with `path`, `rule` and `message`.
        warnings (list): Every warning from the last `read`, in the same form.
    """

    def __init__(self):
        """Builds a reader that has found no problems.

        Returns:
            None: This method returns nothing.
        """
        self.problems = []
        self.warnings = []

    def read(self, plan):
        """Reads a whole plan.

        Args:
            plan (object): The `plan` object from the caller's `synthetic` object.

        Returns:
            OrderPart | None: The root part, or None when the plan has any problem, which are then in `problems`.
        """
        self.problems = []
        self.warnings = []
        root = self._read_node(plan, 'root')
        if self.problems:
            return None
        return root

    def _read_node(self, node, path):
        """Reads one node of the tree.

        Args:
            node (object): The node as the caller wrote it.
            path (str): Where the node sits in the plan.

        Returns:
            OrderPart | None: The part, or None when the node has a problem.
        """
        if not isinstance(node, dict) or len(node) != 1:
            self._add_problem(
                path,
                'node_shape',
                'a plan node is an object holding exactly one key, `order` or the name of a join',
            )
            return None
        for kind, content in node.items():
            if kind == 'order':
                return self._read_order(content, path)
            if kind in JOIN_NAMES:
                self._add_problem(
                    path,
                    'join_not_built',
                    f'the {kind} join is part of the design but is not built yet, so a plan can only be a single order for now',
                )
                return None
            self._add_problem(
                path,
                'unknown_node',
                f'{kind!r} is not a plan node; a node is `order` or one of the joins {", ".join(JOIN_NAMES)}',
            )
        return None

    def _read_order(self, order, path):
        """Reads one order, merging its presets and its own slot values.

        Args:
            order (object): The order's content as the caller wrote it.
            path (str): Where the order sits in the plan.

        Returns:
            OrderPart | None: The part, or None when the order has a problem.
        """
        if not isinstance(order, dict):
            self._add_problem(
                path,
                'order_shape',
                'an order is an object',
            )
            return None
        problems_before = len(self.problems)
        for setting in order:
            if setting not in ORDER_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'an order in a plan takes {", ".join(ORDER_SETTINGS)}, not {setting!r}',
                )
        sources = self._preset_sources(order.get('presets', []), path)
        own = {}
        for slot in ('trigger', 'side', 'pricing'):
            if slot in order:
                own[slot] = order[slot]
        sources.append((own, path))

        preset_names = []
        for preset in order.get('presets', []) or []:
            if isinstance(preset, dict):
                for name in preset:
                    preset_names.append(name)
        conditions = []
        side = None
        pricing = None
        pricing_path = None
        for slots, source_path in sources:
            if 'trigger' in slots:
                condition = self._read_condition(
                    slots['trigger'],
                    f'{source_path}.trigger',
                )
                if condition is not None:
                    conditions.append(condition)
            if 'side' in slots:
                side = self._merged_side(side, slots['side'], f'{source_path}.side')
            if 'pricing' in slots:
                read_pricing = self._read_pricing_list(
                    slots['pricing'],
                    f'{source_path}.pricing',
                )
                if read_pricing is not None:
                    if pricing is not None:
                        self._add_warning(
                            f'{source_path}.pricing',
                            'pricing_replaced',
                            f'this pricing replaces the pricing from {pricing_path}, because an order has one pricing rule at a time',
                        )
                    pricing = read_pricing
                    pricing_path = f'{source_path}.pricing'
        if len(self.problems) > problems_before:
            return None
        trigger = None
        if len(conditions) == 1:
            trigger = conditions[0]
        elif conditions:
            trigger = ConditionGroup('all', conditions)
        if pricing is None:
            pricing = FixedPricing(None, None)
        return OrderPart(path, preset_names, trigger, side, pricing)

    def _preset_sources(self, presets, path):
        """Expands each preset into its slot values.

        Args:
            presets (object): The list as the caller wrote it.
            path (str): Where the order sits in the plan.

        Returns:
            list: One `(slot values, preset path)` pair per preset that could be expanded.
        """
        if not isinstance(presets, list):
            self._add_problem(
                f'{path}.presets',
                'presets_shape',
                'presets is a list of objects, each holding one preset name and its settings',
            )
            return []
        sources = []
        expander = PresetExpander()
        for index, preset in enumerate(presets):
            preset_path = f'{path}.presets.{index}'
            if not isinstance(preset, dict) or len(preset) != 1:
                self._add_problem(
                    preset_path,
                    'preset_shape',
                    'a preset is an object holding exactly one preset name, whose value is that preset\'s settings',
                )
                continue
            for name, settings in preset.items():
                if name not in PRESET_NAMES:
                    self._add_problem(
                        preset_path,
                        'unknown_preset',
                        f'{name!r} is not a preset a plan can use yet; the presets available are {", ".join(PRESET_NAMES)}',
                    )
                    continue
                if not isinstance(settings, dict):
                    self._add_problem(
                        preset_path,
                        'preset_shape',
                        f'the {name} preset\'s settings must be an object',
                    )
                    continue
                slots = expander.expand(name, settings, preset_path)
                self.problems.extend(expander.problems)
                if not expander.problems:
                    sources.append((slots, preset_path))
        return sources

    def _merged_side(self, side, value, path):
        """The order's side once one more source has named one.

        Args:
            side (str | None): The side named so far, or None.
            value (object): The side this source names.
            path (str): Where it was named.

        Returns:
            str | None: The side.
        """
        if value not in SIDES:
            self._add_problem(
                path,
                'bad_setting',
                f'side must be one of {", ".join(SIDES)}, not {value!r}',
            )
            return side
        if side is not None and side != value:
            self._add_problem(
                path,
                'two_sides',
                f'this order is already {side}, so it cannot also be {value}',
            )
            return side
        return value

    def _read_condition(self, condition, path):
        """Reads one trigger condition, or a group of them.

        Args:
            condition (object): The condition as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            object | None: The condition, or None when it has a problem.
        """
        if not isinstance(condition, dict) or len(condition) != 1:
            self._add_problem(
                path,
                'trigger_shape',
                'a trigger is an object holding exactly one condition, or `all` or `any` with a list of them',
            )
            return None
        for kind, content in condition.items():
            if kind in ('all', 'any'):
                return self._read_condition_group(kind, content, path)
            if kind == 'price_crosses':
                return self._read_price_crosses(content, f'{path}.price_crosses')
            if kind in KINDS:
                if not isinstance(content, str):
                    self._add_problem(
                        f'{path}.{kind}',
                        'bad_setting',
                        f'{kind} is a time of day such as "10:00", not {content!r}',
                    )
                    return None
                return TimeCondition(kind, content)
            self._add_problem(
                path,
                'unknown_condition',
                f'{kind!r} is not a trigger condition; the conditions are price_crosses, {", ".join(KINDS)}, all and any',
            )
        return None

    def _read_condition_group(self, joiner, members, path):
        """Reads `all` or `any` and its list of conditions.

        Args:
            joiner (str): `all` or `any`.
            members (object): The list as the caller wrote it.
            path (str): Where the group sits in the plan.

        Returns:
            ConditionGroup | None: The group, or None when it has a problem.
        """
        if not isinstance(members, list) or not members:
            self._add_problem(
                f'{path}.{joiner}',
                'trigger_shape',
                f'{joiner} holds a list of one or more conditions',
            )
            return None
        read_members = []
        for index, member in enumerate(members):
            read_member = self._read_condition(member, f'{path}.{joiner}.{index}')
            if read_member is not None:
                read_members.append(read_member)
        if len(read_members) != len(members):
            return None
        return ConditionGroup(joiner, read_members)

    def _read_price_crosses(self, settings, path):
        """Reads a `price_crosses` condition.

        Args:
            settings (object): The condition's settings as the caller wrote them.
            path (str): Where it sits in the plan.

        Returns:
            PriceCrossesCondition | None: The condition, or None when it has a problem.
        """
        if not isinstance(settings, dict):
            self._add_problem(
                path,
                'trigger_shape',
                'price_crosses holds an object of settings',
            )
            return None
        problems_before = len(self.problems)
        for setting in settings:
            if setting not in PRICE_CROSSES_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'price_crosses takes {", ".join(PRICE_CROSSES_SETTINGS)}, not {setting!r}',
                )
        level = self._price(settings.get('level'), path, 'level')
        direction = settings.get('direction')
        if direction is not None and direction not in DIRECTIONS:
            self._add_problem(
                path,
                'bad_setting',
                f'direction must be one of {", ".join(DIRECTIONS)}, not {direction!r}',
            )
        field = settings.get('field', 'last')
        if field not in FIELDS:
            self._add_problem(
                path,
                'bad_setting',
                f'field must be one of {", ".join(FIELDS)}, not {field!r}',
            )
        confirm = settings.get('confirm', 'none')
        if confirm not in CONFIRMATIONS:
            self._add_problem(
                path,
                'bad_setting',
                f'confirm must be one of {", ".join(CONFIRMATIONS)}, not {confirm!r}',
            )
        hold_seconds = None
        if confirm == 'held':
            hold_seconds = self._price(
                settings.get('hold_seconds'),
                path,
                'hold_seconds',
            )
        instrument_id = settings.get('instrument_id')
        if instrument_id is not None and not isinstance(instrument_id, str):
            self._add_problem(
                path,
                'bad_setting',
                f'instrument_id must be an instrument id, not {instrument_id!r}',
            )
        if len(self.problems) > problems_before:
            return None
        return PriceCrossesCondition(
            level,
            direction,
            field,
            instrument_id,
            confirm,
            hold_seconds,
        )

    def _read_pricing_list(self, pricing, path):
        """Reads an order's pricing, which in this stage is exactly one setter.

        Args:
            pricing (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            object | None: The pricing, or None when it has a problem.
        """
        if not isinstance(pricing, list) or not pricing:
            self._add_problem(
                path,
                'pricing_shape',
                'pricing is a list of one or more pricing values',
            )
            return None
        if len(pricing) > 1:
            self._add_problem(
                path,
                'two_setters',
                'every pricing value so far sets the price from scratch, so an order can have only one',
            )
            return None
        entry = pricing[0]
        entry_path = f'{path}.0'
        if not isinstance(entry, dict) or len(entry) != 1:
            self._add_problem(
                entry_path,
                'pricing_shape',
                'a pricing value is an object holding exactly one pricing name and its settings',
            )
            return None
        for name, settings in entry.items():
            if not isinstance(settings, dict):
                self._add_problem(
                    entry_path,
                    'pricing_shape',
                    f'the {name} pricing\'s settings must be an object',
                )
                return None
            if name == 'fixed':
                return self._read_fixed(settings, f'{entry_path}.fixed')
            if name == 'marketable':
                return self._read_marketable(settings, f'{entry_path}.marketable')
            if name == 'native_stop':
                return self._read_native_stop(settings, f'{entry_path}.native_stop')
            self._add_problem(
                entry_path,
                'unknown_pricing',
                f'{name!r} is not a pricing a plan can use yet; the pricings available are fixed, marketable and native_stop',
            )
        return None

    def _read_fixed(self, settings, path):
        """Reads `fixed` pricing.

        Args:
            settings (dict): `price` and `order_type`, both optional.
            path (str): Where it sits in the plan.

        Returns:
            FixedPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('price', 'order_type'), path, 'fixed')
        price = None
        if 'price' in settings:
            price = self._price(settings['price'], path, 'price')
        order_type = settings.get('order_type')
        if order_type is not None and order_type not in ORDER_TYPES:
            self._add_problem(
                path,
                'bad_setting',
                f'order_type must be one of {", ".join(ORDER_TYPES)}, not {order_type!r}',
            )
        if len(self.problems) > problems_before:
            return None
        return FixedPricing(price, order_type)

    def _read_marketable(self, settings, path):
        """Reads `marketable` pricing.

        Args:
            settings (dict): `buffer_ticks`, optional.
            path (str): Where it sits in the plan.

        Returns:
            MarketablePricing | None: The pricing, or None when it has a problem.
        """
        self._refuse_unknown(settings, ('buffer_ticks',), path, 'marketable')
        value = settings.get('buffer_ticks', 2)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            self._add_problem(
                path,
                'bad_setting',
                f'buffer_ticks must be a whole number of ticks at or above zero, not {value!r}',
            )
            return None
        return MarketablePricing(value)

    def _read_native_stop(self, settings, path):
        """Reads `native_stop` pricing.

        Args:
            settings (dict): `trigger_price` and `limit_price`.
            path (str): Where it sits in the plan.

        Returns:
            NativeStopPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(
            settings,
            ('trigger_price', 'limit_price'),
            path,
            'native_stop',
        )
        trigger_price = self._price(settings.get('trigger_price'), path, 'trigger_price')
        limit_price = self._price(settings.get('limit_price'), path, 'limit_price')
        if len(self.problems) > problems_before:
            return None
        return NativeStopPricing(trigger_price, limit_price)

    def _price(self, value, path, name):
        """Reads a number that must be above zero.

        Args:
            value (object): The value as the caller wrote it.
            path (str): Where it sits in the plan.
            name (str): The setting's name, for the message.

        Returns:
            decimal.Decimal | None: The number, or None when it is missing or not above zero.
        """
        number = None
        if value is not None and not isinstance(value, bool):
            try:
                number = decimal.Decimal(str(value))
            except (decimal.InvalidOperation, TypeError, ValueError):
                number = None
        if number is None or not number.is_finite() or number <= 0:
            self._add_problem(
                path,
                'bad_setting',
                f'{name} must be a number above zero, not {value!r}',
            )
            return None
        return number

    def _refuse_unknown(self, settings, known, path, name):
        """Reports every setting a pricing value does not take.

        Args:
            settings (dict): The settings.
            known (tuple): The settings it takes.
            path (str): Where it sits in the plan.
            name (str): The pricing's name, for the message.

        Returns:
            None: This method returns nothing.
        """
        for setting in settings:
            if setting not in known:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'the {name} pricing takes {", ".join(known)}, not {setting!r}',
                )

    def _add_problem(self, path, rule, message):
        """Records one problem.

        Args:
            path (str): The path of the part the problem is in.
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

    def _add_warning(self, path, rule, message):
        """Records one warning.

        Args:
            path (str): The path the warning is about.
            rule (str): The name of the rule that produced it.
            message (str): What the caller should know.

        Returns:
            None: This method returns nothing.
        """
        self.warnings.append({
            'path': path,
            'rule': rule,
            'message': message,
        })
