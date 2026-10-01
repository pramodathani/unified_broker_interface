"""The venue that never sends an order, and fills it on paper from the virtual book's queue estimate."""


class PaperVenue:
    """A plan order's venue that keeps the order on paper instead of sending it to a broker.

    It keeps the rules of today's virtual limit type with `paper: true`. The order waits on a `limit_marketable` trigger, which the plan reader insists on, so `bin/unified/orders/virtual_book` follows its place in the queue. On every price tick the order takes whatever more the estimate says a resting order at its price would have filled: partly as the queue ahead of it trades away, and wholly once the other side reaches its price. Each fill is recorded as a `paper_filled` event at the order's limit price, and the order is done once its whole quantity has filled.
    """

    def check(self, context, now=None):
        """Checks the order can be kept on paper, which needs nothing beyond what the plan reader checked.

        Args:
            context (OrderContext): Unused.
            now (datetime.datetime | None): Unused.

        Returns:
            None: This method returns nothing.
        """
        del context, now

    def fill(self, plan_order, part):
        """Records whatever more the queue estimate says the order would have filled, and ends the order once it has filled completely.

        Args:
            plan_order (PlanOrder): The plan order.
            part (OrderPart): The order, whose trigger is a `limit_marketable` condition.

        Returns:
            bool: True when a fill was recorded.
        """
        estimate = part.trigger.estimate(plan_order, part.path)
        if estimate is None:
            return False
        filled = estimate.get('filled')
        if isinstance(filled, bool) or not isinstance(filled, int):
            return False
        record = plan_order.part_record(part.path)
        held = ((record.get('memory') or {}).get('trigger') or {}).get('held') or {}
        quantity = int(held.get('quantity') or 0)
        filled = min(filled, quantity)
        already = record.get('paper_filled') or 0
        if filled <= already:
            return False
        price = held.get('price')
        plan_order.record({
            'event': 'paper_filled',
            'parent_state': plan_order.parent.state,
            'path': part.path,
            'transaction_type': held.get('transaction_type'),
            'quantity': quantity,
            'filled_quantity': filled,
            'price': plan_order.json_number(price),
            'detail': {
                'estimate': estimate,
            },
        })
        if plan_order.parent.state == 'received':
            plan_order.record_state('working', f'paper fill of {filled} of {quantity}')
        record['paper_filled'] = filled
        message = f'the plan\'s {part.path} part filled {filled} of {quantity} on paper'
        if filled >= quantity:
            record['state'] = 'done'
            record['reason'] = 'filled_on_paper'
            message = f'the plan\'s {part.path} part filled on paper: {filled} at {price}'
        plan_order.set_part_record(part.path, record, message)
        return True

    def described(self):
        """This venue as a dry run shows it.

        Returns:
            dict: The session.
        """
        return {
            'session': 'paper',
        }
