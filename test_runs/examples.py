"""Runs every example program under `examples/` and checks that each still prints what it printed when it was recorded.

The code reference shows each class's example programs with their output, so this suite is what keeps those pages true. Each program runs in its own Python process from the project root. Redis, MongoDB and PostgreSQL are pointed at port 9 on this machine, where nothing listens, and every HTTP request is sent through a proxy on the same closed port, so a program that tried to reach a real data store or broker would fail rather than touch it.

`--record` writes each program's output to the `.out` file beside it, after an intended change. `--coverage` lists every class that has fewer than two programs and every public method that no program of its class calls. Naming paths runs only the programs under them.

Typical usage:

    python -m test_runs.examples
    python -m test_runs.examples examples/unified_broker_interface/utilities/broker_selection
    python -m test_runs.examples --record examples/unified_broker_interface/utilities/broker_selection
    python -m test_runs.examples --coverage
"""

import argparse
import ast
import concurrent.futures
import os
import pathlib
import subprocess
import sys

from utilities.docs_examples import ExampleProgram


class ExampleRun:
    """The result of running one example program.

    Attributes:
        path (pathlib.Path): The program file.
        exit_code (int): The process's exit code, or -1 when it ran out of time.
        output (str): What the program printed to standard output.
        errors (str): What the program printed to standard error.
    """

    def __init__(self, path, exit_code, output, errors):
        """Holds one run's result.

        Args:
            path (pathlib.Path): The program file.
            exit_code (int): The process's exit code, or -1 when it ran out of time.
            output (str): What the program printed to standard output.
            errors (str): What the program printed to standard error.

        Returns:
            None: This method returns nothing.
        """
        self.path = path
        self.exit_code = exit_code
        self.output = output
        self.errors = errors

    def recorded_output(self):
        """The output recorded for this program.

        Returns:
            str | None: The `.out` file's text, or None when there is no recording.
        """
        output_path = self.path.with_suffix('.out')
        if not output_path.exists():
            return None
        return output_path.read_text()


class ExampleSuite:
    """Runs the example programs and reports how many behaved as recorded.

    Attributes:
        root (pathlib.Path): The project root.
        examples_directory (pathlib.Path): The folder holding every example program.
        packages (tuple): The packages whose classes are expected to have examples.
        passed (int): How many programs passed.
        failed (list): The paths of the programs that failed, with the reason.
    """

    TIMEOUT_SECONDS = 120
    CLOSED_PORT = '9'
    WORKERS = 8
    MINIMUM_PROGRAMS = 2
    EXCLUDED_PARTS = (
        '__pycache__',
        'proto',
        'gen_ref_pages',
        'docs_examples',
    )

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.root = pathlib.Path(__file__).resolve().parent.parent
        self.examples_directory = self.root / 'examples'
        self.packages = (
            'stock_brokers',
            'unified_broker_interface',
            'utilities',
        )
        self.passed = 0
        self.failed = []

    def offline_environment(self):
        """The environment each program runs with, which sends every data store and HTTP request to a closed port.

        Returns:
            dict: The environment variables.
        """
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(self.root)
        environment['PYTHONHASHSEED'] = '0'
        environment['TZ'] = 'Asia/Kolkata'
        stores = (
            'REDIS',
            'MONGODB',
            'POSTGRES',
        )
        for store in stores:
            environment[f'UNIFIED_BROKER_INTERFACE_{store}_HOST'] = '127.0.0.1'
            environment[f'UNIFIED_BROKER_INTERFACE_{store}_PORT'] = self.CLOSED_PORT
        proxy = f'http://127.0.0.1:{self.CLOSED_PORT}'
        proxy_names = (
            'HTTP_PROXY',
            'HTTPS_PROXY',
            'http_proxy',
            'https_proxy',
            'ALL_PROXY',
            'all_proxy',
        )
        for name in proxy_names:
            environment[name] = proxy
        environment['NO_PROXY'] = ''
        environment['no_proxy'] = ''
        return environment

    def program_paths(self, selected_paths):
        """Lists the example programs to run.

        Args:
            selected_paths (list): Folders or files to limit the run to, or an empty list for every program.

        Returns:
            list: The program files, sorted.
        """
        if not selected_paths:
            selected_paths = [
                str(self.examples_directory),
            ]
        paths = set()
        for selected in selected_paths:
            selected_path = (self.root / selected).resolve()
            if selected_path.is_file():
                paths.add(selected_path)
                continue
            for path in selected_path.rglob('*.py'):
                if '__pycache__' not in path.parts:
                    paths.add(path)
        return sorted(paths)

    def run_one(self, path, environment):
        """Runs one program in its own process.

        Args:
            path (pathlib.Path): The program file.
            environment (dict): The environment to run it with.

        Returns:
            ExampleRun: What happened.
        """
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(path),
                ],
                cwd=self.root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            return ExampleRun(path, -1, error.stdout or '', f'Timed out after {self.TIMEOUT_SECONDS} seconds.')
        return ExampleRun(path, completed.returncode, completed.stdout, completed.stderr)

    def judge(self, example_run, record):
        """Decides whether one run passed, and records its output when asked to.

        Args:
            example_run (ExampleRun): The run to judge.
            record (bool): True to write the output to the `.out` file instead of comparing with it.

        Returns:
            None: This method returns nothing.
        """
        name = example_run.path.relative_to(self.root).as_posix()
        if example_run.exit_code != 0:
            last_lines = '\n'.join(example_run.errors.strip().splitlines()[-8:])
            self.failed.append(f'{name}: exit code {example_run.exit_code}\n{last_lines}')
            return
        if record:
            example_run.path.with_suffix('.out').write_text(example_run.output)
            self.passed += 1
            return
        recorded = example_run.recorded_output()
        if recorded is None:
            self.failed.append(f'{name}: no recorded output; run with --record')
            return
        if recorded != example_run.output:
            self.failed.append(f'{name}: output differs from {example_run.path.with_suffix(".out").name}')
            return
        self.passed += 1

    def run_programs(self, selected_paths, record):
        """Runs the chosen programs, several at a time, and prints the result.

        Args:
            selected_paths (list): Folders or files to limit the run to, or an empty list for every program.
            record (bool): True to write each output to its `.out` file.

        Returns:
            int: 0 when every program passed, otherwise 1.
        """
        paths = self.program_paths(selected_paths)
        environment = self.offline_environment()
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.WORKERS) as executor:
            futures = []
            for path in paths:
                futures.append(executor.submit(self.run_one, path, environment))
            for future in futures:
                self.judge(future.result(), record)
        for failure in self.failed:
            print(f'FAILED {failure}')
        print(f'{self.passed}/{len(paths)} example programs passed.')
        if self.failed:
            return 1
        return 0

    def classes_in(self, path):
        """Lists the classes defined in one module, including nested ones, with their public methods and properties.

        Args:
            path (pathlib.Path): The module file.

        Returns:
            list: Pairs of (qualified class name, list of (member name, is property)).
        """
        tree = ast.parse(path.read_text())
        found = []
        pending = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                pending.append((node.name, node))
        while pending:
            qualified_name, class_node = pending.pop(0)
            members = []
            for item in class_node.body:
                if isinstance(item, ast.ClassDef):
                    pending.append((f'{qualified_name}.{item.name}', item))
                    continue
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name.startswith('_'):
                    continue
                is_property = False
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == 'property':
                        is_property = True
                members.append((item.name, is_property))
            found.append((qualified_name, members))
        return found

    def report_coverage(self):
        """Prints every class with too few programs and every public member no program of its class uses.

        Returns:
            int: 0 when nothing is missing, otherwise 1.
        """
        classes_short = 0
        members_missing = 0
        total_classes = 0
        for package in self.packages:
            for path in sorted((self.root / package).rglob('*.py')):
                relative = path.relative_to(self.root).with_suffix('')
                if any(part in self.EXCLUDED_PARTS for part in relative.parts):
                    continue
                module_parts = list(relative.parts)
                if module_parts[-1] == '__init__':
                    module_parts = module_parts[:-1]
                for qualified_name, members in self.classes_in(path):
                    total_classes += 1
                    folder = self.examples_directory.joinpath(*module_parts, qualified_name)
                    programs = []
                    if folder.is_dir():
                        for program_path in sorted(folder.glob('*.py')):
                            programs.append(ExampleProgram(program_path, self.root))
                    label = f'{".".join(module_parts)}.{qualified_name}'
                    if len(programs) < self.MINIMUM_PROGRAMS:
                        classes_short += 1
                        print(f'CLASS {label}: {len(programs)} of {self.MINIMUM_PROGRAMS} programs')
                    if not programs:
                        continue
                    for member_name, is_property in members:
                        used = False
                        for program in programs:
                            if program.statements_using(member_name, is_property):
                                used = True
                                break
                        if not used:
                            members_missing += 1
                            print(f'MEMBER {label}.{member_name}: used by no program')
        covered = total_classes - classes_short
        print(f'{covered}/{total_classes} classes have at least {self.MINIMUM_PROGRAMS} programs; {members_missing} public members of those classes are used by no program.')
        if classes_short or members_missing:
            return 1
        return 0

    def run(self, arguments):
        """Runs the programs, or reports coverage, as the command line asks.

        Args:
            arguments (list): The command-line arguments, without the program name.

        Returns:
            int: The process exit code, 0 on success, 1 on a failure and 2 on a bad argument.
        """
        parser = argparse.ArgumentParser(description='Run the example programs under examples/.')
        parser.add_argument('paths', nargs='*', help='Folders or files under examples/ to run; every program when omitted.')
        parser.add_argument('--record', action='store_true', help='Write each output to the .out file beside its program.')
        parser.add_argument('--coverage', action='store_true', help='List classes with fewer than two programs and public members no program uses.')
        options = parser.parse_args(arguments)
        if options.coverage:
            return self.report_coverage()
        return self.run_programs(options.paths, options.record)


if __name__ == '__main__':
    sys.exit(ExampleSuite().run(sys.argv[1:]))
