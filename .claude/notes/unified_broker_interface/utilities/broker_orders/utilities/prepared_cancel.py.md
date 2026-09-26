# Notes on `unified_broker_interface/utilities/broker_orders/utilities/prepared_cancel.py`

## Why this class exists

Before lists, `cancel_order` checked the order and then built its dry-run answer or its sent answer inline. A list needs the same two answers for each of its orders, so the answers moved here, beside the state they need: the broker, the order id, the stored order and the built request. The single form and each order of a list answer through the same two methods, so the bodies cannot differ between the forms.

`PreparedModification` is its twin, kept as a separate class in its own file rather than one class with a flag, following the project's rule that each case is its own readable class. The two differ in their status field (`status_before_cancel` against `status_before_modify`), in the modification's `instrument_id`, and in which broker call they make.
