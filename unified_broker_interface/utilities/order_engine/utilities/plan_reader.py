"""Reading a caller's plan into the parts that run it, and every problem that stops it running."""

from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
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
)
PRESET_NAMES = (
    'simple',
)


class PlanReader:
    """Reads the `plan` object of a `plan` order into its parts, collecting every problem rather than stopping at the first.

    A plan is a tree. Each node is an object holding exactly one key: `order` for a leaf, or the name of a join for a branch. Each part gets a path from its place in the tree, starting at `root`, which is how its broker orders and its state are told apart from every other part's.

    Only what the engine can run so far is accepted. An order takes a list of `presets`, and the only preset is `simple`. The joins are named in the design and recognised here, so a caller who writes one is told it is not built yet rather than that it is unknown.

    Attributes:
        problems (list): Every problem found by the last `read`, each a dictionary with `path`, `rule` and `message`.
    """

    def __init__(self):
        """Builds a reader that has found no problems.

        Returns:
            None: This method returns nothing.
        """
        self.problems = []

    def read(self, plan):
        """Reads a whole plan.

        Args:
            plan (object): The `plan` object from the caller's `synthetic` object.

        Returns:
            OrderPart | None: The root part, or None when the plan has any problem, which are then in `problems`.
        """
        self.problems = []
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
        """Reads one order.

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
        found_problem = False
        for setting in order:
            if setting not in ORDER_SETTINGS:
                self._add_problem(
                    path,
                    'unknown_setting',
                    f'an order in a plan takes only {", ".join(ORDER_SETTINGS)} so far, not {setting!r}',
                )
                found_problem = True
        presets = self._read_presets(order.get('presets', []), path)
        if presets is None or found_problem:
            return None
        return OrderPart(path, presets)

    def _read_presets(self, presets, path):
        """Reads an order's list of presets.

        Args:
            presets (object): The list as the caller wrote it.
            path (str): Where the order sits in the plan.

        Returns:
            list | None: The preset names in order, or None when any has a problem.
        """
        if not isinstance(presets, list):
            self._add_problem(
                f'{path}.presets',
                'presets_shape',
                'presets is a list of objects, each holding one preset name and its settings',
            )
            return None
        names = []
        found_problem = False
        for index, preset in enumerate(presets):
            preset_path = f'{path}.presets.{index}'
            if not isinstance(preset, dict) or len(preset) != 1:
                self._add_problem(
                    preset_path,
                    'preset_shape',
                    'a preset is an object holding exactly one preset name, whose value is that preset\'s settings',
                )
                found_problem = True
                continue
            for name, settings in preset.items():
                if name not in PRESET_NAMES:
                    self._add_problem(
                        preset_path,
                        'unknown_preset',
                        f'{name!r} is not a preset a plan can use yet; the presets available are {", ".join(PRESET_NAMES)}',
                    )
                    found_problem = True
                    continue
                if settings != {}:
                    self._add_problem(
                        preset_path,
                        'unknown_setting',
                        f'the {name} preset takes no settings, so its value must be an empty object',
                    )
                    found_problem = True
                    continue
                names.append(name)
        if found_problem:
            return None
        return names

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
