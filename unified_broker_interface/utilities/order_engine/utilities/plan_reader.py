"""Reading a caller's plan into the parts that run it, and every problem that stops it running."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.all_at_once_execution import (
    AllAtOnceExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.atr_trail_pricing import (
    AtrTrailPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.book_depth_execution import (
    BookDepthExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.candle_closes_condition import (
    CandleClosesCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.cap_modifier import (
    CapModifier,
)
from unified_broker_interface.utilities.order_engine.utilities.chase_pricing import (
    ChasePricing,
)
from unified_broker_interface.utilities.order_engine.utilities.condition_group import (
    ConditionGroup,
)
from unified_broker_interface.utilities.order_engine.utilities.discretion_modifier import (
    DiscretionModifier,
)
from unified_broker_interface.utilities.order_engine.utilities.elapsed_condition import (
    ElapsedCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.either_part import (
    SIBLING_RULES,
    EitherPart,
)
from unified_broker_interface.utilities.order_engine.utilities.fill_ratio import (
    FillRatio,
)
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.follow_instrument_pricing import (
    FollowInstrumentPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.from_parent_fill_pricing import (
    FromParentFillPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.front_loaded_execution import (
    FrontLoadedExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.iceberg_execution import (
    IcebergExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.lifetime import (
    APPLIES_TO,
    ON_END,
    Lifetime,
)
from unified_broker_interface.utilities.order_engine.utilities.marketable_pricing import (
    MarketablePricing,
)
from unified_broker_interface.utilities.order_engine.utilities.native_stop_pricing import (
    NativeStopPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.option_model_pricing import (
    OptionModelPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)
from unified_broker_interface.utilities.order_engine.utilities.participation_execution import (
    ParticipationExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.peg_pricing import (
    REFERENCES,
    PegPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.position_quantity import (
    PRODUCTS,
    PositionQuantity,
)
from unified_broker_interface.utilities.order_engine.utilities.post_only_guard import (
    ON_CROSSING,
    PostOnlyGuard,
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
from unified_broker_interface.utilities.order_engine.utilities.repeat_part import (
    RepeatPart,
)
from unified_broker_interface.utilities.order_engine.utilities.sequence_part import (
    SequencePart,
)
from unified_broker_interface.utilities.order_engine.utilities.stages_pricing import (
    StagesPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.then_part import (
    ThenPart,
)
from unified_broker_interface.utilities.order_engine.utilities.together_part import (
    DONE_WHEN,
    TogetherPart,
)
from unified_broker_interface.utilities.order_engine.utilities.time_condition import (
    KINDS,
    TimeCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.top_up_execution import (
    TopUpExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.trail_pricing import (
    TrailPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.trails_condition import (
    TrailsCondition,
)
from unified_broker_interface.utilities.order_engine.utilities.twap_execution import (
    TwapExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.vwap_execution import (
    VwapExecution,
)

JOIN_NAMES = (
    'then',
    'either',
    'together',
    'using',
    'repeat',
    'sequence',
)
BUILT_JOIN_NAMES = (
    'then',
    'either',
    'together',
    'sequence',
    'repeat',
)
REPEAT_SETTINGS = (
    'child',
    'times',
    'every_minutes',
    'every_trading_day_at',
    'until',
)
MOST_REPEATS = 100
TOGETHER_SETTINGS = (
    'children',
    'group_margin',
    'hedge_benefit',
    'done_when',
)
SEQUENCE_SETTINGS = (
    'children',
)
MOST_CHILDREN = 25
OVERRIDE_SETTINGS = (
    'instrument_id',
    'quantity',
    'transaction_type',
    'product',
    'validity',
    'tag',
)
THEN_SETTINGS = (
    'first',
    'each_fill',
    'on_complete',
    'cancel_first_on_child_fill',
)
EITHER_SETTINGS = (
    'children',
    'sibling_rule',
    'cancel_before_send',
)
ORDER_SETTINGS = (
    'presets',
    'trigger',
    'side',
    'pricing',
    'execution',
    'guards',
    'lifetime',
    'instrument_id',
    'quantity',
    'transaction_type',
    'product',
    'validity',
    'tag',
)
MOST_SLICES = 60
HIGHEST_VOLATILITY_PERCENT = 500
MOST_RULES = 20
STOP_PRICINGS = (
    NativeStopPricing,
    TrailPricing,
    AtrTrailPricing,
    StagesPricing,
)
SIDES = (
    'buy',
    'sell',
    'protect',
    'close',
)
POSITION_SETTINGS = (
    'product',
    'instrument_ids',
    'every_instrument',
    'ratio',
    'cancel_resting_first',
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

    An order takes `presets`, a list of named presets each standing for slot values, and may give slot values of its own: `trigger`, `side`, `pricing`, `execution` and `guards`. They are merged in order, presets first and the order's own values last. Triggers from several sources are joined with `all`. A later pricing setter, cap, execution or guard replaces an earlier one of the same kind, which is reported in `warnings` rather than refused, because naming a preset for its trigger and then choosing another price is a normal thing to want. Two different sides are refused, because there is no sensible way to join them, and so is a post-only guard on an order whose pricing means to trade at once.

    The joins are named in the design and recognised here, so a caller who writes one is told it is not built yet rather than that it is unknown.

    Attributes:
        opening_side (str | None): BUY or SELL, the side of the caller's body, which some presets need; None when it is not known.
        problems (list): Every problem found by the last `read`, each a dictionary with `path`, `rule` and `message`.
        warnings (list): Every warning from the last `read`, in the same form.
    """

    def __init__(self, opening_side=None):
        """Builds a reader that has found no problems.

        Args:
            opening_side (str | None): BUY or SELL, the side of the caller's body, or None when it is not known.

        Returns:
            None: This method returns nothing.
        """
        self.opening_side = opening_side
        self.problems = []
        self.warnings = []

    def read(self, plan):
        """Reads a whole plan.

        Args:
            plan (object): The `plan` object from the caller's `synthetic` object.

        Returns:
            object | None: The root part, an `OrderPart`, `ThenPart` or `EitherPart`, or None when the plan has any problem, which are then in `problems`.
        """
        self.problems = []
        self.warnings = []
        root = self._read_node(plan, 'root', True)
        if root is not None:
            self._check_fill_sizing(root)
        if self.problems:
            return None
        return root

    def _check_fill_sizing(self, root):
        """Reports every order sized or priced from a first plan's fills that is not the child of a Then join.

        Args:
            root (object): The root part.

        Returns:
            None: This method returns nothing.
        """
        for part in root.order_parts():
            if isinstance(part.pricing, FromParentFillPricing) and part.pricing.first_path is None:
                self._add_problem(part.path, 'from_parent_fill_needs_then', 'from_parent_fill prices this order from the fills of a Then join\'s first order, so it must be that join\'s child, and the first plan a single order')
            if part.fill_ratio is not None and not part.sized_by_fills:
                self._add_problem(part.path, 'parent_fill_needs_then', 'a quantity of parent_fill scales what a Then join\'s first plan filled, so the order must be that join\'s child')

    def _read_node(self, node, path, keeps_tag):
        """Reads one node of the tree.

        Args:
            node (object): The node as the caller wrote it.
            path (str): Where the node sits in the plan.
            keeps_tag (bool): Whether the orders the node places first carry the caller's tag, which only the plan's main order does.

        Returns:
            object | None: The part, or None when the node has a problem.
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
                return self._read_order(content, path, keeps_tag)
            if kind == 'then':
                return self._read_then(content, path, keeps_tag)
            if kind == 'either':
                return self._read_either(content, path, keeps_tag)
            if kind == 'together':
                return self._read_together(content, path, keeps_tag)
            if kind == 'sequence':
                return self._read_sequence(content, path, keeps_tag)
            if kind == 'repeat':
                return self._read_repeat(content, path, keeps_tag)
            if kind in JOIN_NAMES:
                self._add_problem(
                    path,
                    'join_not_built',
                    f'the {kind} join is part of the design but is not built yet; the joins built so far are {", ".join(BUILT_JOIN_NAMES)}',
                )
                return None
            self._add_problem(
                path,
                'unknown_node',
                f'{kind!r} is not a plan node; a node is `order` or one of the joins {", ".join(JOIN_NAMES)}',
            )
        return None

    def _read_then(self, then, path, keeps_tag):
        """Reads a Then join.

        Args:
            then (object): The join's content as the caller wrote it.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first plan's main order carries the caller's tag.

        Returns:
            ThenPart | None: The join, or None when it has a problem.
        """
        if not isinstance(then, dict):
            self._add_problem(path, 'join_shape', 'then holds an object with first and each_fill or on_complete')
            return None
        problems_before = len(self.problems)
        for setting in then:
            if setting not in THEN_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'then takes {", ".join(THEN_SETTINGS)}, not {setting!r}',
                )
        child_keys = []
        for key in ('each_fill', 'on_complete'):
            if key in then:
                child_keys.append(key)
        if 'first' not in then or len(child_keys) != 1:
            self._add_problem(
                path,
                'join_shape',
                'then needs first and exactly one of each_fill or on_complete',
            )
            return None
        cancel_first = then.get('cancel_first_on_child_fill', False)
        if not isinstance(cancel_first, bool):
            self._add_problem(
                path,
                'bad_setting',
                f'cancel_first_on_child_fill must be true or false, not {cancel_first!r}',
            )
        child_key = child_keys[0]
        first = self._read_node(then['first'], f'{path}.first', keeps_tag)
        child = self._read_node(then[child_key], f'{path}.{child_key}', False)
        if child is not None and first is not None:
            opened_by = []
            for part in first.order_parts():
                opened_by.append(part.path)
            for part in child.order_parts():
                part.opened_by = opened_by
        if isinstance(child, OrderPart):
            child.sized_by_fills = True
            if isinstance(child.pricing, FromParentFillPricing) and isinstance(first, OrderPart):
                child.pricing.first_path = first.path
        if isinstance(child, (TogetherPart, SequencePart, RepeatPart)):
            self._add_problem(
                child.path,
                'join_not_sized',
                'a Then join sizes its child to what the first plan filled, and the plans of a together or sequence join each trade their own quantity',
            )
        if len(self.problems) > problems_before:
            return None
        return ThenPart(path, first, child, child_key, cancel_first)

    def _read_children(self, content, path, keeps_tag, name, smallest):
        """Reads the `children` list a join holds.

        Args:
            content (dict): The join's content.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first child's main order carries the caller's tag.
            name (str): The join's name, for the message.
            smallest (int): The fewest children it takes.

        Returns:
            list | None: The children read, or None when the list itself has a problem.
        """
        children = content.get('children')
        if not isinstance(children, list) or len(children) < smallest or len(children) > MOST_CHILDREN:
            self._add_problem(
                path,
                'join_shape',
                f'{name} holds children, a list of {smallest} to {MOST_CHILDREN} plans',
            )
            return None
        read_children = []
        for index, child in enumerate(children):
            read_child = self._read_node(child, f'{path}.children.{index}', keeps_tag and index == 0)
            if read_child is not None:
                read_children.append(read_child)
        return read_children

    def _read_together(self, together, path, keeps_tag):
        """Reads a Together join.

        Args:
            together (object): The join's content as the caller wrote it.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first child's main order carries the caller's tag.

        Returns:
            TogetherPart | None: The join, or None when it has a problem.
        """
        if not isinstance(together, dict):
            self._add_problem(path, 'join_shape', 'together holds an object with children')
            return None
        problems_before = len(self.problems)
        for setting in together:
            if setting not in TOGETHER_SETTINGS:
                self._add_problem(path, 'unknown_setting', f'together takes {", ".join(TOGETHER_SETTINGS)}, not {setting!r}')
        flags = {}
        for name in ('group_margin', 'hedge_benefit'):
            value = together.get(name, name == 'group_margin')
            if not isinstance(value, bool):
                self._add_problem(path, 'bad_setting', f'{name} must be true or false, not {value!r}')
            flags[name] = value
        done_when = together.get('done_when', 'all')
        if done_when not in DONE_WHEN:
            self._add_problem(path, 'bad_setting', f'done_when must be one of {", ".join(DONE_WHEN)}, not {done_when!r}')
        children = self._read_children(together, path, keeps_tag, 'together', 1)
        if children is None or len(self.problems) > problems_before:
            return None
        return TogetherPart(path, children, flags['group_margin'], flags['hedge_benefit'], done_when)

    def _read_sequence(self, sequence, path, keeps_tag):
        """Reads a Sequence join.

        Args:
            sequence (object): The join's content as the caller wrote it.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first child's main order carries the caller's tag.

        Returns:
            SequencePart | None: The join, or None when it has a problem.
        """
        if not isinstance(sequence, dict):
            self._add_problem(path, 'join_shape', 'sequence holds an object with children')
            return None
        problems_before = len(self.problems)
        for setting in sequence:
            if setting not in SEQUENCE_SETTINGS:
                self._add_problem(path, 'unknown_setting', f'sequence takes {", ".join(SEQUENCE_SETTINGS)}, not {setting!r}')
        children = self._read_children(sequence, path, keeps_tag, 'sequence', 2)
        if children is None or len(self.problems) > problems_before:
            return None
        return SequencePart(path, children)

    def _read_repeat(self, repeat, path, keeps_tag):
        """Reads a Repeat join into one copy of its order per time, each after the first waiting its turn.

        Args:
            repeat (object): The join's content as the caller wrote it.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first copy carries the caller's tag.

        Returns:
            RepeatPart | None: The join, or None when it has a problem.
        """
        if not isinstance(repeat, dict):
            self._add_problem(path, 'join_shape', 'repeat holds an object with child, times and every_minutes')
            return None
        problems_before = len(self.problems)
        for setting in repeat:
            if setting not in REPEAT_SETTINGS:
                self._add_problem(path, 'unknown_setting', f'repeat takes {", ".join(REPEAT_SETTINGS)}, not {setting!r}')
        for name in ('every_trading_day_at', 'until'):
            if name in repeat:
                self._add_problem(path, 'not_built', f'{name} is part of the design but not built yet, because a plan does not yet outlive the trading day')
        times = self._whole_number(repeat.get('times'), path, 'times', 1, MOST_REPEATS)
        every_minutes = repeat.get('every_minutes')
        if isinstance(every_minutes, bool) or not isinstance(every_minutes, (int, float)) or every_minutes <= 0:
            self._add_problem(path, 'bad_setting', f'every_minutes must be a number of minutes above zero, not {every_minutes!r}')
        child = repeat.get('child')
        if not isinstance(child, dict) or list(child) != ['order']:
            self._add_problem(path, 'repeat_needs_order', 'repeat sends one order again and again, so its child is an order node')
        if len(self.problems) > problems_before:
            return None
        copies = []
        for index in range(times):
            copy_path = f'{path}.children.{index}'
            part = self._read_node(child, copy_path, keeps_tag and index == 0)
            if part is None:
                return None
            if index > 0:
                elapsed = ElapsedCondition(every_minutes * index)
                if part.trigger is None:
                    part.trigger = elapsed
                else:
                    part.trigger = ConditionGroup('all', [part.trigger, elapsed])
            copies.append(part)
        return RepeatPart(path, copies, times, every_minutes)

    def _read_overrides(self, order, path):
        """Reads the body values an order gives of its own, such as another instrument or quantity.

        Args:
            order (dict): The order as the caller wrote it.
            path (str): Where the order sits in the plan.

        Returns:
            dict: The values, checked.
        """
        overrides = {}
        for name in OVERRIDE_SETTINGS:
            if name not in order:
                continue
            value = order[name]
            if name == 'quantity' and isinstance(value, dict):
                continue
            if name == 'quantity':
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    self._add_problem(path, 'bad_setting', f'quantity must be a whole number of at least 1, not {value!r}')
                    continue
            elif name == 'transaction_type':
                if not isinstance(value, str) or value.strip().upper() not in ('BUY', 'SELL'):
                    self._add_problem(path, 'bad_setting', f'transaction_type must be BUY or SELL, not {value!r}')
                    continue
                value = value.strip().upper()
            elif not isinstance(value, str) or not value:
                self._add_problem(path, 'bad_setting', f'{name} must be text, not {value!r}')
                continue
            overrides[name] = value
        return overrides

    def _read_either(self, either, path, keeps_tag):
        """Reads an Either join.

        A `reduce` join's children share one quantity, which only makes sense when each child is one order, so any other child is refused.

        Args:
            either (object): The join's content as the caller wrote it.
            path (str): Where the join sits in the plan.
            keeps_tag (bool): Whether the first child's main order carries the caller's tag.

        Returns:
            EitherPart | None: The join, or None when it has a problem.
        """
        if not isinstance(either, dict):
            self._add_problem(path, 'join_shape', 'either holds an object with children and sibling_rule')
            return None
        problems_before = len(self.problems)
        for setting in either:
            if setting not in EITHER_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'either takes {", ".join(EITHER_SETTINGS)}, not {setting!r}',
                )
        sibling_rule = either.get('sibling_rule')
        if sibling_rule not in SIBLING_RULES:
            self._add_problem(
                path,
                'bad_setting',
                f'sibling_rule must be one of {", ".join(SIBLING_RULES)}, not {sibling_rule!r}',
            )
        cancel_before_send = either.get('cancel_before_send', False)
        if not isinstance(cancel_before_send, bool):
            self._add_problem(
                path,
                'bad_setting',
                f'cancel_before_send must be true or false, not {cancel_before_send!r}',
            )
        children = either.get('children')
        if not isinstance(children, list) or len(children) < 2:
            self._add_problem(
                path,
                'join_shape',
                'either holds children, a list of two or more plans',
            )
            return None
        read_children = []
        for index, child in enumerate(children):
            read_child = self._read_node(
                child,
                f'{path}.children.{index}',
                keeps_tag and index == 0,
            )
            if read_child is None:
                continue
            if sibling_rule == 'reduce' and not isinstance(read_child, OrderPart):
                self._add_problem(
                    read_child.path,
                    'reduce_needs_orders',
                    'the children of a reduce join share one quantity, so each must be a single order',
                )
            read_children.append(read_child)
        if len(self.problems) > problems_before:
            return None
        return EitherPart(path, read_children, sibling_rule, cancel_before_send)

    def _read_order(self, order, path, keeps_tag):
        """Reads one order, merging its presets and its own slot values, or the join a join preset in it stands for.

        Args:
            order (object): The order's content as the caller wrote it.
            path (str): Where the order sits in the plan.
            keeps_tag (bool): Whether its orders carry the caller's tag.

        Returns:
            object | None: The part, or None when the order has a problem.
        """
        if not isinstance(order, dict):
            self._add_problem(
                path,
                'order_shape',
                'an order is an object',
            )
            return None
        tree = self._join_preset_tree(order, path)
        if tree is not None:
            if not tree:
                return None
            return self._read_node(tree, path, keeps_tag)
        problems_before = len(self.problems)
        for setting in order:
            if setting not in ORDER_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'an order in a plan takes {", ".join(ORDER_SETTINGS)}, not {setting!r}',
                )
        sources = self._preset_sources(order.get('presets', []), path)
        overrides = self._read_overrides(order, path)
        own = {}
        for slot in ('trigger', 'side', 'pricing', 'execution', 'guards', 'lifetime'):
            if slot in order:
                own[slot] = order[slot]
        if isinstance(order.get('quantity'), dict):
            own['quantity'] = order['quantity']
        sources.append((own, path))
        position_quantity = None
        position_path = None

        preset_names = []
        for preset in order.get('presets', []) or []:
            if isinstance(preset, dict):
                for name in preset:
                    preset_names.append(name)
        conditions = []
        side = None
        pricing = None
        pricing_path = None
        cap = None
        cap_path = None
        discretion = None
        discretion_path = None
        post_only = None
        post_only_path = None
        lifetime = None
        lifetime_path = None
        execution = None
        execution_path = None
        for slots, source_path in sources:
            if 'quantity' in slots:
                position_quantity = slots['quantity']
                position_path = f'{source_path}.quantity'
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
                    read_setter, read_cap, read_discretion = read_pricing
                    if read_setter is not None:
                        if pricing is not None:
                            self._add_warning(
                                f'{source_path}.pricing',
                                'pricing_replaced',
                                f'this pricing replaces the pricing from {pricing_path}, because an order has one pricing rule at a time',
                            )
                        pricing = read_setter
                        pricing_path = f'{source_path}.pricing'
                    if read_cap is not None:
                        if cap is not None:
                            self._add_warning(
                                f'{source_path}.pricing',
                                'cap_replaced',
                                f'this cap replaces the cap from {cap_path}, because an order has one worst price',
                            )
                        cap = read_cap
                        cap_path = f'{source_path}.pricing'
                    if read_discretion is not None:
                        if discretion is not None:
                            self._add_warning(
                                f'{source_path}.pricing',
                                'discretion_replaced',
                                f'this discretion replaces the discretion from {discretion_path}',
                            )
                        discretion = read_discretion
                        discretion_path = f'{source_path}.pricing'
            if 'lifetime' in slots:
                read_lifetime = self._read_lifetime_list(
                    slots['lifetime'],
                    f'{source_path}.lifetime',
                )
                if read_lifetime is not None:
                    if lifetime is not None:
                        self._add_warning(
                            f'{source_path}.lifetime',
                            'lifetime_replaced',
                            f'this lifetime replaces the lifetime from {lifetime_path}, because an order has one lifetime',
                        )
                    lifetime = read_lifetime
                    lifetime_path = f'{source_path}.lifetime'
            if 'guards' in slots:
                read_post_only = self._read_guards_list(
                    slots['guards'],
                    f'{source_path}.guards',
                )
                if read_post_only is not None:
                    if post_only is not None:
                        self._add_warning(
                            f'{source_path}.guards',
                            'guard_replaced',
                            f'this post_only guard replaces the one from {post_only_path}',
                        )
                    post_only = read_post_only
                    post_only_path = f'{source_path}.guards'
            if 'execution' in slots:
                read_execution = self._read_execution_list(
                    slots['execution'],
                    f'{source_path}.execution',
                )
                if read_execution is not None:
                    if execution is not None:
                        self._add_warning(
                            f'{source_path}.execution',
                            'execution_replaced',
                            f'this execution replaces the execution from {execution_path}, because an order has one execution at a time',
                        )
                    execution = read_execution
                    execution_path = f'{source_path}.execution'
        if len(self.problems) > problems_before:
            return None
        trigger = None
        if len(conditions) == 1:
            trigger = conditions[0]
        elif conditions:
            trigger = ConditionGroup('all', conditions)
        if pricing is None:
            pricing = FixedPricing(None, None)
        if execution is None:
            execution = AllAtOnceExecution()
        if isinstance(pricing, STOP_PRICINGS):
            if not isinstance(execution, AllAtOnceExecution):
                self._add_problem(
                    path,
                    'stop_not_sliced',
                    'a resting stop protects the whole position at once, so its order cannot be split into pieces sent over time',
                )
                return None
        if post_only is not None and not self._can_rest(pricing, path):
            return None
        if discretion is not None and not self._can_take_at_discretion(pricing, execution, path):
            return None
        if lifetime is not None and not self._can_end(lifetime, pricing, side, path):
            return None
        position = None
        fill_ratio = None
        if position_quantity is not None and 'parent_fill' in position_quantity:
            fill_ratio = self._read_fill_ratio(position_quantity, position_path)
            if fill_ratio is None:
                return None
        elif position_quantity is not None:
            position = self._read_position(position_quantity, position_path)
            if position is None:
                return None
        if not self._closes_sensibly(side, position, pricing_path, execution, path):
            return None
        part = OrderPart(path, preset_names, trigger, side, pricing, keeps_tag, execution, cap, post_only, discretion, lifetime, overrides, position)
        part.fill_ratio = fill_ratio
        return part

    def _closes_sensibly(self, side, position, pricing_path, execution, path):
        """Whether a `close` side and a position quantity come together and with nothing they would ignore, reporting the problem when not.

        A close reads the position held and prices each closing order a little past the touch itself, so a pricing or an execution of its own would be ignored.

        Args:
            side (str | None): The order's side.
            position (PositionQuantity | None): The order's position quantity.
            pricing_path (str | None): Where the order's pricing was given, or None when it has none.
            execution (object): The order's execution.
            path (str): Where the order sits in the plan.

        Returns:
            bool: True when they are sensible.
        """
        if side == 'close' and position is None:
            self._add_problem(path, 'close_needs_position', 'a close reads the position held when it fires, so its quantity must be {"position": {...}}')
            return False
        if position is not None and side != 'close':
            self._add_problem(path, 'position_needs_close', 'a quantity read from the position closes that position, so the order\'s side must be close')
            return False
        if position is None:
            return True
        if pricing_path is not None or not isinstance(execution, AllAtOnceExecution):
            self._add_problem(path, 'close_prices_itself', 'a close sends one order per position a little past the touch, so it takes no pricing or execution of its own')
            return False
        return True

    def _read_fill_ratio(self, quantity, path):
        """Reads a quantity given as `{"parent_fill": {...}}`.

        Args:
            quantity (dict): The quantity as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            FillRatio | None: The sizing, or None when it has a problem.
        """
        settings = quantity.get('parent_fill')
        if len(quantity) != 1 or not isinstance(settings, dict):
            self._add_problem(path, 'bad_setting', 'a quantity is a whole number, or an object holding position or parent_fill and its settings')
            return None
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('ratio', 'whole_lots'), f'{path}.parent_fill', 'parent_fill', 'quantity')
        ratio = self._price(settings.get('ratio', 1), path, 'ratio')
        whole_lots = settings.get('whole_lots', False)
        if not isinstance(whole_lots, bool):
            self._add_problem(path, 'bad_setting', f'whole_lots must be true or false, not {whole_lots!r}')
        if len(self.problems) > problems_before:
            return None
        return FillRatio(ratio, whole_lots)

    def _read_position(self, quantity, path):
        """Reads a quantity given as `{"position": {...}}`.

        Args:
            quantity (dict): The quantity as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            PositionQuantity | None: The quantity, or None when it has a problem.
        """
        if len(quantity) != 1 or not isinstance(quantity.get('position'), dict):
            self._add_problem(path, 'bad_setting', 'a quantity is a whole number, or an object holding position and its settings')
            return None
        settings = quantity['position']
        problems_before = len(self.problems)
        self._refuse_unknown(settings, POSITION_SETTINGS, f'{path}.position', 'position', 'quantity')
        product = settings.get('product')
        if product is not None and product not in PRODUCTS:
            self._add_problem(path, 'bad_setting', f'product must be one of {", ".join(PRODUCTS)}, not {product!r}')
        instrument_ids = settings.get('instrument_ids')
        if instrument_ids is not None:
            valid = isinstance(instrument_ids, list) and bool(instrument_ids)
            if valid:
                for instrument_id in instrument_ids:
                    if not isinstance(instrument_id, str) or not instrument_id:
                        valid = False
            if not valid:
                self._add_problem(path, 'bad_setting', 'instrument_ids is a list of instrument ids')
        flags = {}
        for name, default in (('every_instrument', False), ('cancel_resting_first', True)):
            value = settings.get(name, default)
            if not isinstance(value, bool):
                self._add_problem(path, 'bad_setting', f'{name} must be true or false, not {value!r}')
            flags[name] = value
        if flags['every_instrument'] is True and instrument_ids is not None:
            self._add_problem(path, 'bad_setting', 'every_instrument closes every instrument held, so it takes no instrument_ids')
        ratio = settings.get('ratio', 1)
        if ratio not in (1, 2) or isinstance(ratio, bool):
            self._add_problem(path, 'bad_setting', f'ratio must be 1, to close, or 2, to close and reverse, not {ratio!r}')
        if len(self.problems) > problems_before:
            return None
        return PositionQuantity(product, instrument_ids, flags['every_instrument'], ratio, flags['cancel_resting_first'])

    def _can_end(self, lifetime, pricing, side, path):
        """Whether an order can end the way its lifetime says, reporting the problem when it cannot.

        Closing what filled is only safe for the plan's own order: inside a join, other orders are sized to its fills and would be left protecting a position that was closed under them. A protecting order closing what it filled would open the position again. A stop has no limit to make marketable.

        Args:
            lifetime (Lifetime): The order's lifetime.
            pricing (object): The order's pricing setter.
            side (str | None): The order's side.
            path (str): Where the order sits in the plan.

        Returns:
            bool: True when it can.
        """
        if lifetime.on_end == 'close_filled' and path != 'root':
            self._add_problem(
                path,
                'close_filled_needs_whole_plan',
                'closing what filled is only allowed for a plan that is one order, because orders joined to it are sized to its fills',
            )
            return False
        if lifetime.on_end == 'close_filled' and side == 'protect':
            self._add_problem(
                path,
                'close_filled_on_protect',
                'this order closes a position, so closing what it filled would open the position again',
            )
            return False
        if lifetime.on_end == 'marketable' and isinstance(pricing, STOP_PRICINGS):
            self._add_problem(
                path,
                'marketable_needs_limit',
                'a stop has no resting limit to make marketable; end it with cancel instead',
            )
            return False
        return True

    def _read_lifetime_list(self, lifetime, path):
        """Reads an order's lifetime: a list holding one object with `at_time` or `after_minutes`, and optionally `applies_to` and `on_end`.

        Args:
            lifetime (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            Lifetime | None: The lifetime, or None when it has a problem.
        """
        if not isinstance(lifetime, list) or len(lifetime) != 1 or not isinstance(lifetime[0], dict):
            self._add_problem(path, 'lifetime_shape', 'lifetime is a list holding one object, with at_time or after_minutes, and optionally applies_to and on_end')
            return None
        entry = lifetime[0]
        entry_path = f'{path}.0'
        problems_before = len(self.problems)
        for name in ('after_days', 'when'):
            if name in entry:
                self._add_problem(
                    entry_path,
                    'lifetime_not_built',
                    f'{name} is part of the design but not built yet; at_time and after_minutes are',
                )
        self._refuse_unknown(entry, ('at_time', 'after_minutes', 'applies_to', 'on_end', 'after_days', 'when'), entry_path, 'lifetime', 'value')
        has_time = 'at_time' in entry
        has_minutes = 'after_minutes' in entry
        if has_time == has_minutes:
            self._add_problem(entry_path, 'bad_setting', 'a lifetime ends at_time or after_minutes, exactly one')
        at_time = None
        after_minutes = None
        if has_time:
            if isinstance(entry['at_time'], str):
                at_time = entry['at_time']
            else:
                self._add_problem(entry_path, 'bad_setting', f'at_time is a time of day such as "14:30", not {entry["at_time"]!r}')
        if has_minutes:
            minutes = entry['after_minutes']
            if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
                self._add_problem(entry_path, 'bad_setting', f'after_minutes must be a number of minutes above zero, not {minutes!r}')
            else:
                after_minutes = minutes
        applies_to = entry.get('applies_to', 'both')
        if applies_to not in APPLIES_TO:
            self._add_problem(entry_path, 'bad_setting', f'applies_to must be one of {", ".join(APPLIES_TO)}, not {applies_to!r}')
        on_end = entry.get('on_end', 'cancel')
        if on_end not in ON_END:
            self._add_problem(entry_path, 'bad_setting', f'on_end must be one of {", ".join(ON_END)}, not {on_end!r}')
        if len(self.problems) > problems_before:
            return None
        return Lifetime(at_time, after_minutes, applies_to, on_end)

    def _can_take_at_discretion(self, pricing, execution, path):
        """Whether an order with this pricing and execution can have discretion, reporting the problem when it cannot.

        Discretion takes a price from one visible limit, so it needs a limit rather than a stop, and one visible order rather than pieces.

        Args:
            pricing (object): The order's pricing setter.
            execution (object): The order's execution.
            path (str): Where the order sits in the plan.

        Returns:
            bool: True when they can go together.
        """
        if isinstance(pricing, STOP_PRICINGS):
            self._add_problem(
                path,
                'discretion_needs_limit',
                'discretion takes a better price than a visible limit shows, and a stop order is not a visible limit',
            )
            return False
        if not isinstance(execution, AllAtOnceExecution):
            self._add_problem(
                path,
                'discretion_not_sliced',
                'discretion takes from one visible order, so the order cannot also be split into pieces',
            )
            return False
        return True

    def _can_rest(self, pricing, path):
        """Whether an order with this pricing can be post-only, reporting the problem when it cannot.

        A post-only order must be a limit meant to rest. A stop is not a resting limit, and marketable pricing, a chase or a peg to the opposite touch all mean to trade against the other side, which a post-only guard exists to prevent.

        Args:
            pricing (object): The order's pricing setter.
            path (str): Where the order sits in the plan.

        Returns:
            bool: True when the two can go together.
        """
        if isinstance(pricing, STOP_PRICINGS):
            self._add_problem(
                path,
                'post_only_needs_limit',
                'a post-only guard checks a limit before it rests, and a stop order is not a resting limit',
            )
            return False
        crossing = isinstance(pricing, (MarketablePricing, ChasePricing))
        if isinstance(pricing, PegPricing) and pricing.reference == 'opposite_touch':
            crossing = True
        if isinstance(pricing, FixedPricing) and pricing.order_type == 'MARKET':
            crossing = True
        if crossing:
            self._add_problem(
                path,
                'post_only_crosses',
                'this pricing means to trade against the other side of the book, which a post-only guard exists to prevent',
            )
            return False
        return True

    def _join_preset_tree(self, order, path):
        """The plan tree a join preset in an order stands for, or None when the order names none.

        Args:
            order (dict): The order as the caller wrote it.
            path (str): Where the order sits in the plan.

        Returns:
            dict | None: The tree, as a caller would write it, or None when there is no join preset or it has problems.
        """
        presets = order.get('presets')
        if not isinstance(presets, list):
            return None
        expander = PresetExpander(self.opening_side)
        found = []
        for index, preset in enumerate(presets):
            if not isinstance(preset, dict) or len(preset) != 1:
                continue
            for name, settings in preset.items():
                if isinstance(settings, dict) and expander.is_join(name, settings):
                    found.append((index, name, settings))
        if not found:
            return None
        if len(found) > 1:
            self._add_problem(
                f'{path}.presets',
                'two_join_presets',
                'an order can name one preset that stands for a join, such as a bracket or an oco, not several',
            )
            return {}
        index, name, settings = found[0]
        entry = dict(order)
        entry['presets'] = presets[:index] + presets[index + 1:]
        if not entry['presets']:
            entry.pop('presets')
        tree = expander.expand_join(name, settings, entry, f'{path}.presets.{index}')
        self.problems.extend(expander.problems)
        if expander.problems:
            return {}
        return tree

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
        expander = PresetExpander(self.opening_side)
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
            if kind == 'trails':
                return self._read_trails(content, f'{path}.trails')
            if kind == 'candle_closes':
                return self._read_candle_closes(content, f'{path}.candle_closes')
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
                f'{kind!r} is not a trigger condition; the conditions are price_crosses, trails, candle_closes, {", ".join(KINDS)}, all and any',
            )
        return None

    def _read_candle_closes(self, settings, path):
        """Reads a `candle_closes` condition.

        Args:
            settings (object): `level`, required; `direction` and `bar_minutes`, default 5, optional.
            path (str): Where it sits in the plan.

        Returns:
            CandleClosesCondition | None: The condition, or None when it has a problem.
        """
        if not isinstance(settings, dict):
            self._add_problem(path, 'bad_setting', 'candle_closes takes an object with level, and optionally direction and bar_minutes')
            return None
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('level', 'direction', 'bar_minutes'), path, 'candle_closes', 'condition')
        level = self._price(settings.get('level'), path, 'level')
        direction = settings.get('direction')
        if direction is not None and direction not in DIRECTIONS:
            self._add_problem(path, 'bad_setting', f'direction must be one of {", ".join(DIRECTIONS)}, not {direction!r}')
        bar_minutes = self._seconds(settings.get('bar_minutes', 5), path, 'bar_minutes')
        if len(self.problems) > problems_before:
            return None
        return CandleClosesCondition(level, direction, bar_minutes)

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
        """Reads an order's pricing: at most one setter, which decides the price, and at most one each of the modifiers `cap` and `discretion`.

        Args:
            pricing (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            tuple | None: The setter (object | None), the cap (CapModifier | None) and the discretion (DiscretionModifier | None), or None when the list has a problem.
        """
        if not isinstance(pricing, list) or not pricing:
            self._add_problem(
                path,
                'pricing_shape',
                'pricing is a list of one or more pricing values',
            )
            return None
        problems_before = len(self.problems)
        setter = None
        cap = None
        discretion = None
        for index, entry in enumerate(pricing):
            entry_path = f'{path}.{index}'
            if not isinstance(entry, dict) or len(entry) != 1:
                self._add_problem(
                    entry_path,
                    'pricing_shape',
                    'a pricing value is an object holding exactly one pricing name and its settings',
                )
                continue
            for name, settings in entry.items():
                if not isinstance(settings, dict):
                    self._add_problem(
                        entry_path,
                        'pricing_shape',
                        f'the {name} pricing\'s settings must be an object',
                    )
                    continue
                if name == 'cap':
                    if cap is not None:
                        self._add_problem(
                            entry_path,
                            'two_caps',
                            'an order has one worst price, so a pricing list can hold only one cap',
                        )
                        continue
                    cap = self._read_cap(settings, f'{entry_path}.cap')
                    continue
                if name == 'discretion':
                    if discretion is not None:
                        self._add_problem(
                            entry_path,
                            'two_discretions',
                            'an order has one discretion, so a pricing list can hold only one',
                        )
                        continue
                    discretion = self._read_discretion(settings, f'{entry_path}.discretion')
                    continue
                read_setter = self._read_setter(name, settings, entry_path)
                if read_setter is None:
                    continue
                if setter is not None:
                    self._add_problem(
                        entry_path,
                        'two_setters',
                        'each pricing setter decides the price from scratch, so an order can have only one; a cap may go beside it',
                    )
                    continue
                setter = read_setter
        if len(self.problems) > problems_before:
            return None
        return setter, cap, discretion

    def _read_setter(self, name, settings, entry_path):
        """Reads one pricing setter by its name.

        Args:
            name (str): The setter's name.
            settings (dict): Its settings.
            entry_path (str): Where it sits in the plan.

        Returns:
            object | None: The pricing, or None when it has a problem.
        """
        if name == 'fixed':
            return self._read_fixed(settings, f'{entry_path}.fixed')
        if name == 'marketable':
            return self._read_marketable(settings, f'{entry_path}.marketable')
        if name == 'native_stop':
            return self._read_native_stop(settings, f'{entry_path}.native_stop')
        if name == 'trail':
            return self._read_trail(settings, f'{entry_path}.trail')
        if name == 'peg':
            return self._read_peg(settings, f'{entry_path}.peg')
        if name == 'chase':
            return self._read_chase(settings, f'{entry_path}.chase')
        if name == 'follow_instrument':
            return self._read_follow_instrument(settings, f'{entry_path}.follow_instrument')
        if name == 'option_model':
            return self._read_option_model(settings, f'{entry_path}.option_model')
        if name == 'stages':
            return self._read_stages(settings, f'{entry_path}.stages')
        if name == 'from_parent_fill':
            self._refuse_unknown(settings, ('net_price',), f'{entry_path}.from_parent_fill', 'from_parent_fill')
            net_price = self._number(settings.get('net_price'), f'{entry_path}.from_parent_fill', 'net_price')
            if net_price is None:
                return None
            return FromParentFillPricing(net_price)
        self._add_problem(
            entry_path,
            'unknown_pricing',
            f'{name!r} is not a pricing a plan can use yet; the pricings available are fixed, marketable, native_stop, trail, stages, peg, chase, follow_instrument, option_model and from_parent_fill, with the modifiers cap and discretion',
        )
        return None

    def _read_peg(self, settings, path):
        """Reads `peg` pricing.

        Args:
            settings (dict): `reference`, default `own_touch`; `offset_ticks`, default 0; `follows`, default true; and `within_body_price`, default false.
            path (str): Where it sits in the plan.

        Returns:
            PegPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('reference', 'offset_ticks', 'follows', 'within_body_price'), path, 'peg')
        reference = settings.get('reference', 'own_touch')
        if reference not in REFERENCES:
            self._add_problem(
                path,
                'bad_setting',
                f'reference must be one of {", ".join(REFERENCES)}, not {reference!r}',
            )
        offset = settings.get('offset_ticks', 0)
        if isinstance(offset, bool) or not isinstance(offset, int):
            self._add_problem(
                path,
                'bad_setting',
                f'offset_ticks must be a whole number of ticks, not {offset!r}',
            )
        flags = {}
        for name, default in (('follows', True), ('within_body_price', False)):
            value = settings.get(name, default)
            if not isinstance(value, bool):
                self._add_problem(path, 'bad_setting', f'{name} must be true or false, not {value!r}')
            flags[name] = value
        if len(self.problems) > problems_before:
            return None
        return PegPricing(reference, offset, flags['follows'], flags['within_body_price'])

    def _read_chase(self, settings, path):
        """Reads `chase` pricing.

        Args:
            settings (dict): `step_ticks`, default 1; `step_seconds`, default 5; and `cross_after_seconds`, optional.
            path (str): Where it sits in the plan.

        Returns:
            ChasePricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('step_ticks', 'step_seconds', 'cross_after_seconds'), path, 'chase')
        step_ticks = self._whole_number(settings.get('step_ticks', 1), path, 'step_ticks', 1, None)
        step_seconds = self._seconds(settings.get('step_seconds', 5.0), path, 'step_seconds')
        cross_after = None
        if settings.get('cross_after_seconds') is not None:
            cross_after = self._seconds(settings['cross_after_seconds'], path, 'cross_after_seconds')
        if len(self.problems) > problems_before:
            return None
        return ChasePricing(step_ticks, step_seconds, cross_after)

    def _seconds(self, value, path, name):
        """Reads a number of seconds above zero.

        Args:
            value (object): The value as the caller wrote it.
            path (str): Where it sits in the plan.
            name (str): The setting's name, for the message.

        Returns:
            float | None: The seconds, or None when the value is not a number above zero.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            self._add_problem(
                path,
                'bad_setting',
                f'{name} must be a number of seconds above zero, not {value!r}',
            )
            return None
        return float(value)

    def _read_bounds(self, settings, path):
        """Reads the `lowest`, `highest` and `step_ticks` that the pricings following another instrument share.

        Args:
            settings (dict): The pricing's settings.
            path (str): Where it sits in the plan.

        Returns:
            tuple: The lowest and highest prices (decimal.Decimal | None) and the step (int | None).
        """
        lowest = None
        highest = None
        if settings.get('lowest') is not None:
            lowest = self._price(settings['lowest'], path, 'lowest')
        if settings.get('highest') is not None:
            highest = self._price(settings['highest'], path, 'highest')
        if lowest is not None and highest is not None and lowest > highest:
            self._add_problem(
                path,
                'bad_setting',
                f'lowest {lowest} is above highest {highest}',
            )
        step_ticks = self._whole_number(settings.get('step_ticks', 1), path, 'step_ticks', 1, None)
        return lowest, highest, step_ticks

    def _instrument_id(self, value, path):
        """Reads the instrument a pricing follows.

        Args:
            value (object): The value as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            str | None: The instrument id, or None when it is missing.
        """
        if not isinstance(value, str) or not value:
            self._add_problem(
                path,
                'bad_setting',
                f'instrument_id names the instrument to follow, and is required, not {value!r}',
            )
            return None
        return value

    def _read_follow_instrument(self, settings, path):
        """Reads `follow_instrument` pricing.

        Args:
            settings (dict): `instrument_id` and `delta`, required; `lowest`, `highest` and `step_ticks`, optional.
            path (str): Where it sits in the plan.

        Returns:
            FollowInstrumentPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('instrument_id', 'delta', 'lowest', 'highest', 'step_ticks'), path, 'follow_instrument')
        instrument_id = self._instrument_id(settings.get('instrument_id'), path)
        delta = self._number(settings.get('delta'), path, 'delta')
        lowest, highest, step_ticks = self._read_bounds(settings, path)
        if len(self.problems) > problems_before:
            return None
        return FollowInstrumentPricing(instrument_id, delta, lowest, highest, step_ticks)

    def _read_option_model(self, settings, path):
        """Reads `option_model` pricing.

        Args:
            settings (dict): `instrument_id` and `volatility`, required; `interest_rate`, `lowest`, `highest` and `step_ticks`, optional.
            path (str): Where it sits in the plan.

        Returns:
            OptionModelPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('instrument_id', 'volatility', 'interest_rate', 'lowest', 'highest', 'step_ticks'), path, 'option_model')
        instrument_id = self._instrument_id(settings.get('instrument_id'), path)
        volatility = self._price(settings.get('volatility'), path, 'volatility')
        if volatility is not None and volatility > HIGHEST_VOLATILITY_PERCENT:
            self._add_problem(
                path,
                'bad_setting',
                f'volatility is a percentage above zero and at most {HIGHEST_VOLATILITY_PERCENT}, not {volatility}',
            )
        interest_rate = decimal.Decimal('0')
        if settings.get('interest_rate') is not None:
            interest_rate = self._number(settings['interest_rate'], path, 'interest_rate')
        lowest, highest, step_ticks = self._read_bounds(settings, path)
        if len(self.problems) > problems_before:
            return None
        return OptionModelPricing(instrument_id, volatility, interest_rate, lowest, highest, step_ticks)

    def _number(self, value, path, name):
        """Reads any finite number, which may be zero or below.

        Args:
            value (object): The value as the caller wrote it.
            path (str): Where it sits in the plan.
            name (str): The setting's name, for the message.

        Returns:
            decimal.Decimal | None: The number, or None when it is missing or not a number.
        """
        number = None
        if value is not None and not isinstance(value, bool):
            try:
                number = decimal.Decimal(str(value))
            except (decimal.InvalidOperation, TypeError, ValueError):
                number = None
        if number is None or not number.is_finite():
            self._add_problem(
                path,
                'bad_setting',
                f'{name} must be a number, not {value!r}',
            )
            return None
        return number

    def _read_discretion(self, settings, path):
        """Reads the `discretion` pricing modifier.

        Args:
            settings (dict): `points`, required, and `quantity`, optional.
            path (str): Where it sits in the plan.

        Returns:
            DiscretionModifier | None: The discretion, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('points', 'quantity'), path, 'discretion')
        points = self._price(settings.get('points'), path, 'points')
        quantity = None
        if settings.get('quantity') is not None:
            quantity = self._whole_number(settings['quantity'], path, 'quantity', 1, None)
        if len(self.problems) > problems_before:
            return None
        return DiscretionModifier(points, quantity)

    def _read_cap(self, settings, path):
        """Reads the `cap` pricing modifier.

        Args:
            settings (dict): `worst_price`, required.
            path (str): Where it sits in the plan.

        Returns:
            CapModifier | None: The cap, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('worst_price',), path, 'cap')
        worst_price = self._price(settings.get('worst_price'), path, 'worst_price')
        if len(self.problems) > problems_before:
            return None
        return CapModifier(worst_price)

    def _read_guards_list(self, guards, path):
        """Reads an order's guards, of which `post_only` is the one built so far.

        Args:
            guards (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            PostOnlyGuard | None: The guard, or None when there is none or it has a problem.
        """
        if not isinstance(guards, list):
            self._add_problem(path, 'guards_shape', 'guards is a list of guard values')
            return None
        guard = None
        for index, entry in enumerate(guards):
            entry_path = f'{path}.{index}'
            if not isinstance(entry, dict) or len(entry) != 1:
                self._add_problem(entry_path, 'guards_shape', 'a guard is an object holding exactly one guard name and its settings')
                continue
            for name, settings in entry.items():
                if name != 'post_only':
                    self._add_problem(
                        entry_path,
                        'unknown_guard',
                        f'{name!r} is not a guard a plan can use yet; the guard available is post_only',
                    )
                    continue
                if not isinstance(settings, dict):
                    self._add_problem(entry_path, 'guards_shape', 'the post_only guard\'s settings must be an object')
                    continue
                problems_before = len(self.problems)
                self._refuse_unknown(settings, ('on_crossing',), f'{entry_path}.post_only', 'post_only', 'guard')
                on_crossing = settings.get('on_crossing', 'refuse')
                if on_crossing not in ON_CROSSING:
                    self._add_problem(
                        f'{entry_path}.post_only',
                        'bad_setting',
                        f'on_crossing must be one of {", ".join(ON_CROSSING)}, not {on_crossing!r}',
                    )
                if len(self.problems) == problems_before:
                    guard = PostOnlyGuard(on_crossing)
        return guard

    def _read_execution_list(self, execution, path):
        """Reads an order's execution, which in this stage is exactly one value.

        Args:
            execution (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            object | None: The execution, or None when it has a problem.
        """
        if not isinstance(execution, list) or not execution:
            self._add_problem(path, 'execution_shape', 'execution is a list holding one execution value')
            return None
        if len(execution) > 1:
            self._add_problem(
                path,
                'nesting_not_built',
                'an order takes one execution value so far; nesting one inside another is part of the design but not built yet',
            )
            return None
        entry = execution[0]
        entry_path = f'{path}.0'
        if not isinstance(entry, dict) or len(entry) != 1:
            self._add_problem(entry_path, 'execution_shape', 'an execution value is an object holding exactly one execution name and its settings')
            return None
        for name, settings in entry.items():
            if not isinstance(settings, dict):
                self._add_problem(entry_path, 'execution_shape', f'the {name} execution\'s settings must be an object')
                return None
            if name == 'all_at_once':
                self._refuse_unknown(settings, (), entry_path, 'all_at_once', 'execution')
                return AllAtOnceExecution()
            if name == 'iceberg':
                return self._read_iceberg(settings, f'{entry_path}.iceberg')
            if name in ('twap', 'vwap', 'front_loaded'):
                return self._read_timed(name, settings, f'{entry_path}.{name}')
            if name == 'participation':
                return self._read_participation(settings, f'{entry_path}.participation')
            if name == 'book_depth':
                return self._read_book_depth(settings, f'{entry_path}.book_depth')
            if name == 'top_up':
                self._refuse_unknown(settings, (), entry_path, 'top_up', 'execution')
                return TopUpExecution()
            self._add_problem(
                entry_path,
                'unknown_execution',
                f'{name!r} is not an execution a plan can use yet; the executions available are all_at_once, iceberg, twap, vwap, front_loaded, participation, book_depth and top_up',
            )
        return None

    def _whole_number(self, value, path, name, lowest, highest):
        """Reads a whole number within bounds.

        Args:
            value (object): The value as the caller wrote it.
            path (str): Where it sits in the plan.
            name (str): The setting's name, for the message.
            lowest (int): The smallest allowed.
            highest (int | None): The largest allowed, or None for no limit.

        Returns:
            int | None: The number, or None when it is missing or out of bounds.
        """
        is_whole = isinstance(value, int) and not isinstance(value, bool)
        in_bounds = is_whole and value >= lowest
        if in_bounds and highest is not None and value > highest:
            in_bounds = False
        if in_bounds:
            return value
        if highest is None:
            bounds = f'at least {lowest}'
        else:
            bounds = f'from {lowest} to {highest}'
        self._add_problem(path, 'bad_setting', f'{name} must be a whole number {bounds}, not {value!r}')
        return None

    def _read_iceberg(self, settings, path):
        """Reads `iceberg` execution.

        Args:
            settings (dict): `visible_quantity`, and optionally `randomise_percent`.
            path (str): Where it sits in the plan.

        Returns:
            IcebergExecution | None: The execution, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('visible_quantity', 'randomise_percent'), path, 'iceberg', 'execution')
        visible = self._whole_number(settings.get('visible_quantity'), path, 'visible_quantity', 1, None)
        randomise = self._whole_number(settings.get('randomise_percent', 0), path, 'randomise_percent', 0, 99)
        if len(self.problems) > problems_before:
            return None
        return IcebergExecution(visible, randomise)

    def _read_timed(self, name, settings, path):
        """Reads `twap`, `vwap` or `front_loaded` execution.

        Args:
            name (str): The execution's name.
            settings (dict): `slices` and `over_minutes`, `volume_profile` for VWAP and `urgency` for front-loaded.
            path (str): Where it sits in the plan.

        Returns:
            TimedSlicesExecution | None: The execution, or None when it has a problem.
        """
        problems_before = len(self.problems)
        known = ['slices', 'over_minutes']
        if name == 'vwap':
            known.append('volume_profile')
        if name == 'front_loaded':
            known.append('urgency')
        self._refuse_unknown(settings, tuple(known), path, name, 'execution')
        slices = self._whole_number(settings.get('slices'), path, 'slices', 2, MOST_SLICES)
        over_minutes = self._price(settings.get('over_minutes'), path, 'over_minutes')
        profile = None
        if name == 'vwap' and 'volume_profile' in settings:
            profile = self._read_profile(settings['volume_profile'], path)
        urgency = 0.5
        if name == 'front_loaded' and 'urgency' in settings:
            value = settings['urgency']
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if is_number and 0 <= value <= 1:
                urgency = float(value)
            else:
                self._add_problem(path, 'bad_setting', f'urgency must be a number from 0 to 1, not {value!r}')
        if len(self.problems) > problems_before:
            return None
        if name == 'twap':
            return TwapExecution(slices, float(over_minutes))
        if name == 'vwap':
            return VwapExecution(slices, float(over_minutes), profile)
        return FrontLoadedExecution(slices, float(over_minutes), urgency)

    def _read_participation(self, settings, path):
        """Reads `participation` execution.

        Args:
            settings (dict): `percent`, and optionally `most_slices`.
            path (str): Where it sits in the plan.

        Returns:
            ParticipationExecution | None: The execution, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('percent', 'most_slices'), path, 'participation', 'execution')
        percent = self._price(settings.get('percent'), path, 'percent')
        if percent is not None and percent > 100:
            self._add_problem(path, 'bad_setting', f'percent must be above zero and at most 100, not {percent}')
        most_slices = self._whole_number(settings.get('most_slices', 60), path, 'most_slices', 1, None)
        if len(self.problems) > problems_before:
            return None
        return ParticipationExecution(float(percent), most_slices)

    def _read_book_depth(self, settings, path):
        """Reads `book_depth` execution.

        Args:
            settings (dict): `limit_price` and `minimum_quantity`.
            path (str): Where it sits in the plan.

        Returns:
            BookDepthExecution | None: The execution, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('limit_price', 'minimum_quantity'), path, 'book_depth', 'execution')
        limit_price = self._price(settings.get('limit_price'), path, 'limit_price')
        minimum_quantity = self._whole_number(settings.get('minimum_quantity'), path, 'minimum_quantity', 1, None)
        if len(self.problems) > problems_before:
            return None
        return BookDepthExecution(limit_price, minimum_quantity)

    def _read_profile(self, profile, path):
        """Reads a VWAP volume profile: relative weights, one per half hour from the open.

        Args:
            profile (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            list | None: The weights, or None when the profile has a problem.
        """
        if not isinstance(profile, list) or not profile:
            self._add_problem(path, 'bad_setting', 'volume_profile must be a list of relative weights, one per half hour from the open')
            return None
        weights = []
        for value in profile:
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not is_number or value < 0:
                self._add_problem(path, 'bad_setting', f'every volume_profile weight must be a number at or above zero, not {value!r}')
                return None
            weights.append(float(value))
        if sum(weights) <= 0:
            self._add_problem(path, 'bad_setting', 'volume_profile weights must add up to more than zero')
            return None
        return weights

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

    def _read_distance(self, settings, path, name):
        """Reads the trailing distance a `trail` pricing or a `trails` condition takes: `points` or `percent`, exactly one.

        Args:
            settings (dict): The settings.
            path (str): Where they sit in the plan.
            name (str): The pricing's or condition's name, for the message.

        Returns:
            tuple: `points` and `percent` (decimal.Decimal | None), one of them None.
        """
        has_points = 'points' in settings
        has_percent = 'percent' in settings
        if has_points == has_percent:
            self._add_problem(
                path,
                'bad_setting',
                f'{name} takes points or percent, exactly one, to say how far behind the market it follows',
            )
            return None, None
        if 'points' in settings:
            return self._price(settings['points'], path, 'points'), None
        return None, self._price(settings['percent'], path, 'percent')

    def _read_trails(self, settings, path):
        """Reads a `trails` condition.

        Args:
            settings (object): `points` or `percent`.
            path (str): Where it sits in the plan.

        Returns:
            TrailsCondition | None: The condition, or None when it has a problem.
        """
        if not isinstance(settings, dict):
            self._add_problem(path, 'trigger_shape', 'trails holds an object of settings')
            return None
        problems_before = len(self.problems)
        for setting in settings:
            if setting not in ('points', 'percent'):
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'trails takes points or percent, not {setting!r}',
                )
        points, percent = self._read_distance(settings, path, 'trails')
        if len(self.problems) > problems_before:
            return None
        return TrailsCondition(points, percent)

    def _read_trail(self, settings, path):
        """Reads `trail` pricing, which with `atr` trails a multiple of the recent average range.

        Args:
            settings (dict): `points` or `percent`, `limit_offset`, and optionally `step_ticks` and `atr`.
            path (str): Where it sits in the plan.

        Returns:
            TrailPricing | AtrTrailPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(
            settings,
            ('points', 'percent', 'limit_offset', 'step_ticks', 'atr'),
            path,
            'trail',
        )
        points, percent = self._read_distance(settings, path, 'trail')
        limit_offset = self._price(settings.get('limit_offset'), path, 'limit_offset')
        step_ticks = self._step_ticks(settings, path)
        atr = None
        if 'atr' in settings:
            atr = self._read_atr(settings['atr'], f'{path}.atr')
            if percent is not None:
                self._add_problem(
                    path,
                    'bad_setting',
                    'a trail with atr falls back on points until enough bars have closed, so it takes points rather than percent',
                )
        if len(self.problems) > problems_before:
            return None
        if atr is not None:
            bar_minutes, periods, multiple = atr
            return AtrTrailPricing(points, limit_offset, step_ticks, bar_minutes, periods, multiple)
        return TrailPricing(points, percent, limit_offset, step_ticks)

    def _step_ticks(self, settings, path):
        """Reads a stop's `step_ticks`, the smallest move worth sending.

        Args:
            settings (dict): The pricing's settings.
            path (str): Where it sits in the plan.

        Returns:
            int | None: The step, default 1, or None when it is not a whole number of at least one.
        """
        step_ticks = settings.get('step_ticks', 1)
        if isinstance(step_ticks, bool) or not isinstance(step_ticks, int) or step_ticks < 1:
            self._add_problem(
                path,
                'bad_setting',
                f'step_ticks must be a whole number of ticks, at least one, not {step_ticks!r}',
            )
            return None
        return step_ticks

    def _read_atr(self, atr, path):
        """Reads a trail's `atr` settings.

        Args:
            atr (object): The settings as the caller wrote them: `bar_minutes` (default 5), `periods` (default 14) and `multiple` (default 2).
            path (str): Where they sit in the plan.

        Returns:
            tuple | None: The bar minutes (float), the periods (int) and the multiple (decimal.Decimal), or None when they have a problem.
        """
        if not isinstance(atr, dict):
            self._add_problem(path, 'bad_setting', 'atr is an object with bar_minutes, periods and multiple')
            return None
        problems_before = len(self.problems)
        self._refuse_unknown(atr, ('bar_minutes', 'periods', 'multiple'), path, 'atr', 'setting')
        bar_minutes = self._seconds(atr.get('bar_minutes', 5), path, 'bar_minutes')
        periods = self._whole_number(atr.get('periods', 14), path, 'periods', 2, None)
        multiple = self._price(atr.get('multiple', 2), path, 'multiple')
        if len(self.problems) > problems_before:
            return None
        return bar_minutes, periods, multiple

    def _read_stages(self, settings, path):
        """Reads `stages` pricing: a stop moved by profit milestones.

        Args:
            settings (dict): `entry_price`, `stop_price`, `limit_offset` and `rules`, required, and `step_ticks`, optional.
            path (str): Where it sits in the plan.

        Returns:
            StagesPricing | None: The pricing, or None when it has a problem.
        """
        problems_before = len(self.problems)
        self._refuse_unknown(settings, ('entry_price', 'stop_price', 'limit_offset', 'step_ticks', 'rules'), path, 'stages')
        entry_price = self._price(settings.get('entry_price'), path, 'entry_price')
        stop_price = self._price(settings.get('stop_price'), path, 'stop_price')
        limit_offset = self._price(settings.get('limit_offset'), path, 'limit_offset')
        step_ticks = self._step_ticks(settings, path)
        rules = self._read_rules(settings.get('rules'), f'{path}.rules')
        if len(self.problems) > problems_before:
            return None
        return StagesPricing(entry_price, stop_price, limit_offset, step_ticks, rules)

    def _read_rules(self, given, path):
        """Reads a stepped stop's milestones, with today's rules.

        Args:
            given (object): The list as the caller wrote it.
            path (str): Where it sits in the plan.

        Returns:
            list | None: The rules, each with `gain` and `stop_at_gain` or `trail_points` as `decimal.Decimal`, or None when they have a problem.
        """
        if not isinstance(given, list) or not given or len(given) > MOST_RULES:
            self._add_problem(path, 'bad_setting', f'rules is a list of 1 to {MOST_RULES} milestones')
            return None
        rules = []
        previous_gain = decimal.Decimal(0)
        for index, rule in enumerate(given):
            rule_path = f'{path}.{index}'
            if not isinstance(rule, dict):
                self._add_problem(rule_path, 'bad_setting', 'a rule is an object with gain and stop_at_gain or trail_points')
                return None
            self._refuse_unknown(rule, ('gain', 'stop_at_gain', 'trail_points'), rule_path, 'rule', 'setting')
            gain = self._price(rule.get('gain'), rule_path, 'gain')
            if gain is None:
                return None
            if gain <= previous_gain:
                self._add_problem(rule_path, 'bad_setting', f'the gain of {gain} must be larger than the rule before it')
                return None
            has_stop = rule.get('stop_at_gain') is not None
            has_trail = rule.get('trail_points') is not None
            if has_stop == has_trail:
                self._add_problem(rule_path, 'bad_setting', 'a rule takes exactly one of stop_at_gain and trail_points')
                return None
            checked = {
                'gain': gain,
            }
            if has_trail:
                if index != len(given) - 1:
                    self._add_problem(rule_path, 'bad_setting', 'this rule switches to trailing, so it must be the last rule')
                    return None
                checked['trail_points'] = self._price(rule['trail_points'], rule_path, 'trail_points')
            else:
                stop_at_gain = self._number(rule['stop_at_gain'], rule_path, 'stop_at_gain')
                if stop_at_gain is None:
                    return None
                if stop_at_gain >= gain:
                    self._add_problem(rule_path, 'bad_setting', f'the stop at {stop_at_gain} would be at or past the gain of {gain} that moves it, where it would fire at once')
                    return None
                checked['stop_at_gain'] = stop_at_gain
            rules.append(checked)
            previous_gain = gain
        return rules

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

    def _refuse_unknown(self, settings, known, path, name, kind='pricing'):
        """Reports every setting a slot value does not take.

        Args:
            settings (dict): The settings.
            known (tuple): The settings it takes.
            path (str): Where it sits in the plan.
            name (str): The value's name, for the message.
            kind (str): What the value is, such as `pricing`, `execution` or `guard`, for the message.

        Returns:
            None: This method returns nothing.
        """
        for setting in settings:
            if setting not in known:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'the {name} {kind} takes {", ".join(known)}, not {setting!r}',
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
