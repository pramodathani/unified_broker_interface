"""A plan order kept whole as an exposure hedge: a hedge traded whenever the account's net exposure leaves a band."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)

DEFAULT_BUFFER_TICKS = 2
SETTINGS = (
    'watched',
    'hedge_instrument_id',
    'hedge_exposure_per_unit',
    'lower_band',
    'upper_band',
)


class ExposureHedgePart(WholePart):
    """An exposure hedge in a plan, with the rules of today's exposure hedge type.

    On every tick the account's positions in the `watched` instruments are read from `unified:portfolio:positions`, each multiplied by its `exposure_per_unit` (1 when not given) and added up, with the hedges this part has sent and not had rejected or cancelled counted at once, before the positions catch up with them. Inside `lower_band` to `upper_band` nothing happens. Outside it a hedge is sent on `hedge_instrument_id`, sized to bring the total back to the middle of the band at `hedge_exposure_per_unit` (1 when not given) per unit, as a limit two ticks past the hedge's touch, so it trades now.

    The hedge instrument is the part's own instrument, so the plan remembers its tick size and the hedge is priced from its own quote. The part places nothing when the plan is placed, so the plan answers `armed`, and it never ends on its own: it watches until its join or the caller stops it, and is done once its hedges have finished after that.
    """

    def __init__(self, path, name, settings, keeps_tag=True, overrides=None):
        """Builds the part, trading the hedge instrument.

        Args:
            path (str): The part's path in the plan.
            name (str): The preset's name.
            settings (dict): The preset's settings.
            keeps_tag (bool): Whether its orders carry the caller's tag.
            overrides (dict | None): The order's own values written over the body's.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(path, name, settings, keeps_tag, overrides)
        self.overrides = dict(self.overrides)
        if settings.get('hedge_instrument_id'):
            self.overrides['instrument_id'] = settings['hedge_instrument_id']

    def _number(self, value):
        """A finite number, or None.

        Args:
            value (object): The value.

        Returns:
            decimal.Decimal | None: The number, or None when it is not a finite number.
        """
        if isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite():
            return None
        return number

    def settings_problems(self):
        """Every problem with the settings, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in SETTINGS:
                problems.append(f'the exposure_hedge preset takes {", ".join(SETTINGS)}, not {name!r}')
        watched = self.settings.get('watched')
        if not isinstance(watched, list) or not watched:
            problems.append('an exposure hedge needs watched, a list of the instruments whose positions count, each with its exposure_per_unit')
        else:
            for position, entry in enumerate(watched):
                if not isinstance(entry, dict):
                    problems.append(f'watched entry {position + 1} must be an object, not {type(entry).__name__}')
                    continue
                if not entry.get('instrument_id'):
                    problems.append(f'watched entry {position + 1} must name its instrument_id')
                if self._number(entry.get('exposure_per_unit', 1)) is None:
                    problems.append(f'watched entry {position + 1} exposure_per_unit must be a number, not {entry.get("exposure_per_unit")!r}')
        lower = self.settings.get('lower_band')
        upper = self.settings.get('upper_band')
        if lower is None or upper is None:
            problems.append('an exposure hedge needs lower_band and upper_band, the range the exposure is allowed to sit in')
        elif self._number(lower) is None or self._number(upper) is None:
            problems.append(f'lower_band and upper_band must be numbers, not {lower!r} and {upper!r}')
        elif self._number(lower) >= self._number(upper):
            problems.append(f'lower_band of {lower} is not below upper_band of {upper}')
        if not self.settings.get('hedge_instrument_id'):
            problems.append('an exposure hedge needs hedge_instrument_id, the instrument it trades to bring the exposure back')
        per_unit = self._number(self.settings.get('hedge_exposure_per_unit', 1))
        if per_unit is None:
            problems.append(f'hedge_exposure_per_unit must be a number, not {self.settings.get("hedge_exposure_per_unit")!r}')
        elif per_unit == 0:
            problems.append('hedge_exposure_per_unit cannot be zero: an instrument with no exposure per unit cannot hedge anything')
        return problems

    def needs_prices(self):
        """Whether this part reads quotes, which it does to price its hedge.

        Returns:
            bool: True.
        """
        return True

    def moves_on_ticks(self):
        """Whether this part is looked at on every tick, which it is, to measure the exposure.

        Returns:
            bool: True.
        """
        return True

    def held(self, positions, instrument_id):
        """How much of one instrument the account is holding, signed, from the positions document's `net` list.

        Args:
            positions (dict | None): The positions document.
            instrument_id (str): The instrument.

        Returns:
            decimal.Decimal: The net quantity, zero when there is no position.
        """
        total = decimal.Decimal('0')
        if not isinstance(positions, dict):
            return total
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict) or entry.get('instrument_id') != instrument_id:
                continue
            quantity = self._number(entry.get('quantity', 0))
            if quantity is not None:
                total = total + quantity
        return total

    def hedges_in_flight(self, parent):
        """The exposure of the hedges this part has sent, counted before the positions catch up with them.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            decimal.Decimal: The exposure already on its way.
        """
        per_unit = self._number(self.settings.get('hedge_exposure_per_unit', 1))
        total = decimal.Decimal('0')
        for leg in self.own_legs(parent):
            if leg.state in ('rejected', 'cancelled'):
                continue
            quantity = decimal.Decimal(str(leg.quantity or 0))
            if leg.transaction_type == 'SELL':
                quantity = -quantity
            total = total + quantity * per_unit
        return total

    def exposure(self, positions, parent):
        """The total exposure of everything watched, counting the hedges already sent.

        Args:
            positions (dict | None): The positions document.
            parent (ParentOrder): The plan order's parent.

        Returns:
            decimal.Decimal: The total.
        """
        total = decimal.Decimal('0')
        for entry in self.settings['watched']:
            per_unit = self._number(entry.get('exposure_per_unit', 1))
            total = total + self.held(positions, entry['instrument_id']) * per_unit
        return total + self.hedges_in_flight(parent)

    def hedge_price(self, view, side):
        """The price the hedge goes out at, two ticks past the touch so that it trades now.

        Args:
            view (MarketView): The hedge instrument's quote.
            side (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when the book gives nothing to price against.
        """
        touch = view.opposite_touch(side)
        if touch is None:
            touch = view.last()
        if touch is None:
            return None
        price = view.rounded(view.moved(touch, DEFAULT_BUFFER_TICKS, side, True), side)
        if price is None or price <= 0:
            return None
        return price

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Starts watching, placing nothing until the exposure leaves its band.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused.
            started_at (float | None): Unused.
            quotes (dict): Unused.
            now (float | None): Unused.

        Returns:
            list: Nothing is placed, so an empty list.
        """
        del target, started_at, quotes, now
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part watches the exposure, which may sit from {self.settings["lower_band"]} to {self.settings["upper_band"]}')
        return []

    def move(self, plan_order, quotes, now):
        """Sends a hedge when the exposure has left its band.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.

        Returns:
            bool: True when a hedge was sent.
        """
        del now
        if plan_order.part_record(self.path).get('state') != 'working' or self.is_stopped(plan_order):
            return False
        context = self.context(plan_order)
        _, _, positions = context.placement.market_context(plan_order.parent.instrument_id, False, True)
        lower = self._number(self.settings['lower_band'])
        upper = self._number(self.settings['upper_band'])
        total = self.exposure(positions, plan_order.parent)
        if lower <= total <= upper:
            return False
        per_unit = self._number(self.settings.get('hedge_exposure_per_unit', 1))
        wanted = ((lower + upper) / 2 - total) / per_unit
        quantity = int(abs(wanted))
        if quantity < 1:
            return False
        side = 'BUY' if wanted > 0 else 'SELL'
        price = self.hedge_price(context.view(quotes), side)
        if price is None:
            return False
        self.place_order(plan_order, self.limit_order(plan_order, side, price, quantity), None)
        return True

    def settle(self, plan_order):
        """Marks the hedge done once it has been stopped and its hedges have finished; a filled hedge leaves it watching.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: Nothing is placed while settling, so an empty list.
        """
        if self.is_stopped(plan_order):
            self.finish_when_done(plan_order)
        return []
