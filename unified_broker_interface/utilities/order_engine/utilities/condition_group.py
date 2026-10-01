"""Trigger conditions joined with `all` or `any`."""


class ConditionGroup:
    """Several trigger conditions joined so that all of them, or any one of them, must hold.

    Each member keeps its own memory under its position in the group, so a `held` price condition inside a group counts its own time. With `all`, every member is asked on every tick, even after one says no, so that each keeps its confirmation count up to date.

    Attributes:
        joiner (str): `all` or `any`.
        members (list): The conditions, each a condition object or another `ConditionGroup`.
    """

    def __init__(self, joiner, members):
        """Builds the group.

        Args:
            joiner (str): `all` or `any`.
            members (list): The conditions.

        Returns:
            None: This method returns nothing.
        """
        self.joiner = joiner
        self.members = members

    def needs_prices(self):
        """Whether any member reads quotes.

        Returns:
            bool: True when at least one does.
        """
        for member in self.members:
            if member.needs_prices():
                return True
        return False

    def instruments(self):
        """The instruments other than the order's own that any member watches.

        Returns:
            list: The instrument ids, each once.
        """
        found = []
        for member in self.members:
            for instrument_id in member.instruments():
                if instrument_id not in found:
                    found.append(instrument_id)
        return found

    def _member_memory(self, memory, index):
        """One member's memory, inside the group's.

        Args:
            memory (dict): The group's memory, changed in place when the member has none yet.
            index (int): The member's position.

        Returns:
            dict: The member's memory.
        """
        key = str(index)
        if key not in memory:
            memory[key] = {}
        return memory[key]

    def prepare(self, plan_order, memory):
        """Readies every member when the plan is placed.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The group's memory.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: When a member cannot be readied.
        """
        for index, member in enumerate(self.members):
            member.prepare(plan_order, self._member_memory(memory, index))

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether all members hold, or any one does.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The group's memory, changed in place.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.
            opening_side (str): BUY or SELL, the side the caller's order was opened with.
            sending_side (str): BUY or SELL, the side the order will be sent on.

        Returns:
            bool: True when the group holds.
        """
        results = []
        for index, member in enumerate(self.members):
            results.append(member.is_met(
                plan_order,
                self._member_memory(memory, index),
                quotes,
                now,
                opening_side,
                sending_side,
            ))
        if self.joiner == 'all':
            return all(results)
        return any(results)

    def described(self):
        """This group as a dry run shows it.

        Returns:
            dict: The joiner and each member.
        """
        described_members = []
        for member in self.members:
            described_members.append(member.described())
        return {
            self.joiner: described_members,
        }
