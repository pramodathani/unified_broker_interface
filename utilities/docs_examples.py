"""Adds every class's example programs, and the lines that call each method, to the code reference.

The example programs live under `examples/`, in a folder that mirrors the module path and ends with the class's name, such as `examples/unified_broker_interface/utilities/broker_selection/fixed_priority/FixedPrioritySelector/`. Each `.py` file there is one complete program, and a `.out` file beside it holds what the program prints. `python -m test_runs.examples` runs every program and compares its output with the `.out` file, so what the reference shows is known to work.

This is build tooling rather than project code. `mkdocs.yml` loads it as a griffe extension by path, it reads files without importing any project module, and it never runs outside a documentation build.
"""

import ast
import pathlib
import textwrap

import griffe


class ExampleProgram:
    """One example program and the output recorded for it.

    Attributes:
        relative_path (str): The program's path from the project root, with forward slashes.
        source (str): The program's full text.
        tree (ast.Module): The program, parsed.
        output (str | None): What the program prints, or None when no output has been recorded.
    """

    SIMPLE_STATEMENTS = (
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Expr,
        ast.Return,
        ast.Assert,
        ast.Delete,
        ast.Raise,
    )

    def __init__(self, path, root):
        """Reads and parses one program.

        Args:
            path (pathlib.Path): The program file.
            root (pathlib.Path): The project root, which relative paths are measured from.

        Returns:
            None: This method returns nothing.

        Raises:
            SyntaxError: When the program is not valid Python.
        """
        self.relative_path = path.relative_to(root).as_posix()
        self.source = path.read_text()
        self.tree = ast.parse(self.source)
        output_path = path.with_suffix('.out')
        self.output = None
        if output_path.exists():
            self.output = output_path.read_text()

    def title(self):
        """A short label for the program's tab, made from its file name.

        The file `example_2_preferred_broker_excluded.py` is labelled "Preferred broker excluded".

        Returns:
            str: The label.
        """
        words = pathlib.PurePosixPath(self.relative_path).stem.split('_')
        if len(words) > 2 and words[0] == 'example' and words[1].isdigit():
            words = words[2:]
        label = ' '.join(words)
        return label[:1].upper() + label[1:]

    def statements_using(self, member_name, is_property):
        """Finds the program's statements that call a method, or read a property, of that name.

        Calls made on `self` or `cls`, and anything under `if __name__ == '__main__':`, are left out, because those belong to the program's own class rather than to the class being shown.

        Args:
            member_name (str): The method or property name.
            is_property (bool): True to look for attribute reads, False to look for calls.

        Returns:
            list: The source text of each matching statement, in the order they appear, without repeats.
        """
        parents = {}
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        found = []
        for node in ast.walk(self.tree):
            if not self.is_use(node, member_name, is_property):
                continue
            if self.is_inside_main_guard(node, parents):
                continue
            text = self.enclosing_text(node, parents)
            if text is not None and text not in found:
                found.append(text)
        return found

    def is_use(self, node, member_name, is_property):
        """Says whether one syntax node uses the member on something other than `self` or `cls`.

        Args:
            node (ast.AST): The node to test.
            member_name (str): The method or property name.
            is_property (bool): True to match attribute reads, False to match calls.

        Returns:
            bool: True when the node is a matching use.
        """
        if is_property:
            attribute = node
            if not isinstance(attribute, ast.Attribute):
                return False
            if not isinstance(attribute.ctx, ast.Load):
                return False
        else:
            if not isinstance(node, ast.Call):
                return False
            attribute = node.func
            if not isinstance(attribute, ast.Attribute):
                return False
        if attribute.attr != member_name:
            return False
        receiver = attribute.value
        if isinstance(receiver, ast.Name) and receiver.id in ('self', 'cls'):
            return False
        return True

    def is_inside_main_guard(self, node, parents):
        """Says whether a node sits under the program's `if __name__ == '__main__':` block.

        Args:
            node (ast.AST): The node to test.
            parents (dict): Each node's parent node.

        Returns:
            bool: True when the node is inside the main guard.
        """
        current = node
        while current in parents:
            current = parents[current]
            if isinstance(current, ast.If) and '__main__' in ast.unparse(current.test):
                return True
        return False

    def enclosing_text(self, node, parents):
        """The source of the smallest whole statement around a node, or of the node itself inside a compound statement's header.

        Args:
            node (ast.AST): The matching call or attribute read.
            parents (dict): Each node's parent node.

        Returns:
            str | None: The source text, with common indentation removed, or None when it cannot be recovered.
        """
        current = node
        while current in parents:
            parent = parents[current]
            if isinstance(parent, self.SIMPLE_STATEMENTS):
                current = parent
                break
            if isinstance(parent, ast.stmt):
                break
            current = parent
        if not isinstance(current, self.SIMPLE_STATEMENTS):
            current = node
        text = ast.get_source_segment(self.source, current, padded=True)
        if text is None:
            return None
        return textwrap.dedent(text).strip()


class ExamplesExtension(griffe.Extension):
    """A griffe extension that appends example programs to class docstrings and example calls to method docstrings.

    Attributes:
        root (pathlib.Path): The project root.
        examples_directory (pathlib.Path): The folder holding every example program.
        programs_by_folder (dict): The programs already read, keyed by their folder.
    """

    MOST_CALLS_SHOWN = 3

    def __init__(self, examples_directory='examples'):
        """Builds the extension.

        Args:
            examples_directory (str): The example folder, relative to the directory the build runs in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.root = pathlib.Path.cwd()
        self.examples_directory = self.root / examples_directory
        self.programs_by_folder = {}

    def programs_for(self, class_object):
        """Reads the example programs written for one class.

        Args:
            class_object (griffe.Class): The class.

        Returns:
            list: The class's `ExampleProgram` objects, in file name order, or an empty list when it has none.
        """
        module_path = class_object.module.path
        class_path = class_object.path[len(module_path) + 1:]
        folder = self.examples_directory.joinpath(*module_path.split('.'), class_path)
        if folder not in self.programs_by_folder:
            programs = []
            if folder.is_dir():
                for path in sorted(folder.glob('*.py')):
                    programs.append(ExampleProgram(path, self.root))
            self.programs_by_folder[folder] = programs
        return self.programs_by_folder[folder]

    def indented(self, text):
        """Indents every non-blank line by four spaces, so it sits inside a content tab.

        Args:
            text (str): The text to indent.

        Returns:
            str: The indented text.
        """
        lines = []
        for line in text.splitlines():
            if line.strip():
                lines.append('    ' + line)
            else:
                lines.append('')
        return '\n'.join(lines)

    def class_section(self, programs):
        """Builds the Markdown that shows a class's programs, one content tab each.

        Args:
            programs (list): The class's `ExampleProgram` objects.

        Returns:
            str: The Markdown to append to the class docstring.
        """
        parts = [
            '**Example programs**',
        ]
        for program in programs:
            parts.append(f'=== "{program.title()}"')
            code_block = f'````python title="{program.relative_path}"\n{program.source.rstrip()}\n````'
            parts.append(self.indented(code_block))
            if program.output is not None:
                parts.append(self.indented('It prints:'))
                output_block = f'````text\n{program.output.rstrip()}\n````'
                parts.append(self.indented(output_block))
        return '\n\n'.join(parts)

    def method_section(self, statements):
        """Builds the Markdown that shows the example lines using one method or property.

        Args:
            statements (list): Pairs of (statement text, program path).

        Returns:
            str: The Markdown to append to the method docstring.
        """
        parts = [
            '**Example usage**',
        ]
        for text, relative_path in statements:
            file_name = pathlib.PurePosixPath(relative_path).name
            parts.append(f'````python title="From {file_name}"\n{text}\n````')
        return '\n\n'.join(parts)

    def append(self, owner, markdown):
        """Adds Markdown to the end of an object's docstring, creating the docstring when there is none.

        Args:
            owner (griffe.Object): The class or function.
            markdown (str): The Markdown to add.

        Returns:
            None: This method returns nothing.
        """
        if owner.docstring is None:
            owner.docstring = griffe.Docstring(markdown, parent=owner)
            return
        owner.docstring.value = f'{owner.docstring.value.rstrip()}\n\n{markdown}'

    def on_class_members(self, *, node, cls, agent, **kwargs):
        """Adds the class's programs to its docstring, and each member's example lines to that member's docstring.

        Args:
            node (ast.AST | griffe.ObjectNode): The class's syntax node.
            cls (griffe.Class): The class, with its members loaded.
            agent (griffe.Visitor | griffe.Inspector): The object that loaded the class.
            **kwargs (Any): Other arguments griffe passes, which are not used.

        Returns:
            None: This method returns nothing.
        """
        del node
        del agent
        del kwargs
        programs = self.programs_for(cls)
        if not programs:
            return
        constructor = cls.members.get('__init__')
        if constructor is not None and not constructor.is_alias and constructor.docstring is not None:
            self.append(constructor, self.class_section(programs))
        else:
            self.append(cls, self.class_section(programs))
        for member in cls.members.values():
            if member.is_alias or not member.is_function:
                continue
            if member.name == '__init__':
                continue
            is_property = 'property' in member.labels
            statements = []
            for program in programs:
                for text in program.statements_using(member.name, is_property):
                    statements.append((text, program.relative_path))
            if statements:
                self.append(member, self.method_section(statements[:self.MOST_CALLS_SHOWN]))
