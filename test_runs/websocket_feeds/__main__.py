"""Runs the websocket feed recordings from the command line."""

import argparse
import json
import os
import pathlib
import sys
import time

from test_runs.websocket_feeds import dhan
from test_runs.websocket_feeds import flattrade
from test_runs.websocket_feeds import fyers
from test_runs.websocket_feeds import groww
from test_runs.websocket_feeds import harness
from test_runs.websocket_feeds import indmoney
from test_runs.websocket_feeds import kotak
from test_runs.websocket_feeds import shoonya
from test_runs.websocket_feeds import wisdom_capital
from test_runs.websocket_feeds import zerodha

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'websocket_feeds.jsonl'
)

BROKER_CASES = {
    'dhan': dhan.DhanFeedCases,
    'flattrade': flattrade.FlattradeFeedCases,
    'fyers': fyers.FyersFeedCases,
    'groww': groww.GrowwFeedCases,
    'indmoney': indmoney.IndmoneyFeedCases,
    'kotak': kotak.KotakFeedCases,
    'shoonya': shoonya.ShoonyaFeedCases,
    'wisdom_capital': wisdom_capital.WisdomCapitalFeedCases,
    'zerodha': zerodha.ZerodhaFeedCases,
}


class WebsocketFeedsSuite:
    """Runs the chosen brokers' scenarios, then records them or compares them with the fixture.

    Attributes:
        loader (harness.ScriptLoader): Loads the scripts under test.
    """

    def __init__(self):
        """Builds the suite with an empty script loader.

        Returns:
            None: This method returns nothing.
        """
        self.loader = harness.ScriptLoader()

    def run_scenario(self, cases, scenario):
        """Runs one scenario with every outside dependency replaced.

        Args:
            cases (object): The broker's case class instance.
            scenario (tuple): The scenario's name, connections, failing logins and runner.

        Returns:
            dict: The recorded result: the scenario's name, its ordered events and its outcome.
        """
        name, connections, failing_logins, runner = scenario
        context = harness.ScenarioContext(name, connections)
        context.logins.failing_logins = set(failing_logins)
        stub_modules = cases.stub_modules(context)
        with harness.PatchedWorld(context, stub_modules, cases.datetime_holders(), cases.attribute_patches()):
            outcome = runner(context)
        return {
            'name': name,
            'events': context.event_log.events,
            'outcome': outcome,
        }

    def run_brokers(self, brokers):
        """Runs every scenario of the chosen brokers.

        Args:
            brokers (list): Broker names.

        Returns:
            list: One recorded result per scenario, in order.
        """
        results = []
        for broker in brokers:
            cases = BROKER_CASES[broker](self.loader)
            for scenario in cases.scenarios():
                results.append(self.run_scenario(cases, scenario))
        return results

    def encode(self, result):
        """Encodes one result as a single stable line of JSON.

        Args:
            result (dict): The result.

        Returns:
            str: The JSON line, with sorted keys.
        """
        return json.dumps(result, sort_keys=True, ensure_ascii=False)

    def read_recording(self):
        """Reads the fixture file.

        Returns:
            dict: Scenario names to recorded results, in file order.
        """
        recorded = {}
        if not FIXTURE_PATH.exists():
            return recorded
        for line in FIXTURE_PATH.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            recorded_result = json.loads(line)
            recorded[recorded_result['name']] = recorded_result
        return recorded

    def broker_of(self, scenario_name):
        """The broker a scenario belongs to, which is the first part of its name.

        Args:
            scenario_name (str): The scenario's name, such as `zerodha.quotes.every_packet_shape`.

        Returns:
            str: The broker's name.
        """
        return scenario_name.split('.')[0]

    def record(self, brokers, results):
        """Rewrites the chosen brokers' lines in the fixture and keeps every other broker's lines.

        Args:
            brokers (list): The brokers that were run.
            results (list): Their results.

        Returns:
            int: The exit code, always 0.
        """
        kept = []
        for name, recorded_result in self.read_recording().items():
            if self.broker_of(name) not in brokers:
                kept.append(recorded_result)
        combined = kept + results
        combined.sort(key=self.sort_key)
        lines = []
        for result in combined:
            lines.append(self.encode(result))
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'recorded {len(results)} scenarios for {", ".join(brokers)} to {FIXTURE_PATH}')
        return 0

    def sort_key(self, result):
        """Orders fixture lines by broker, keeping each broker's scenarios in the order they run.

        Args:
            result (dict): A recorded result.

        Returns:
            str: The broker's name.
        """
        return self.broker_of(result['name'])

    def compare(self, brokers, results):
        """Compares the chosen brokers' results with the fixture and prints every difference.

        Args:
            brokers (list): The brokers that were run.
            results (list): Their results.

        Returns:
            int: The exit code: 0 when everything matches, 1 otherwise.
        """
        recorded = self.read_recording()
        failures = 0
        current_names = set()
        for result in results:
            current_names.add(result['name'])
            expected = recorded.get(result['name'])
            if expected is None:
                failures = failures + 1
                print(f'NEW      {result["name"]}')
            elif self.encode(expected) != self.encode(result):
                failures = failures + 1
                print(f'CHANGED  {result["name"]}')
                self.print_first_difference(expected, result)
        for name in recorded:
            if self.broker_of(name) in brokers and name not in current_names:
                failures = failures + 1
                print(f'MISSING  {name}')
        passed = len(results) - failures
        print(f'{passed} of {len(results)} scenarios match the recording, {failures} differ')
        if failures:
            return 1
        return 0

    def print_first_difference(self, expected, result):
        """Prints the first event where a scenario departs from its recording.

        Args:
            expected (dict): The recorded result.
            result (dict): The result now.

        Returns:
            None: This method returns nothing.
        """
        expected_events = expected['events']
        current_events = result['events']
        for index in range(max(len(expected_events), len(current_events))):
            expected_event = None
            if index < len(expected_events):
                expected_event = expected_events[index]
            current_event = None
            if index < len(current_events):
                current_event = current_events[index]
            if expected_event != current_event:
                print(f'  event {index} recorded: {json.dumps(expected_event)[:400]}')
                print(f'  event {index} now:      {json.dumps(current_event)[:400]}')
                return
        print(f'  outcome recorded: {json.dumps(expected["outcome"])}')
        print(f'  outcome now:      {json.dumps(result["outcome"])}')

    def run(self):
        """Runs the suite from the command line.

        Returns:
            int: The exit code.
        """
        parser = argparse.ArgumentParser(
            description='Check every broker websocket against its recorded behaviour.',
        )
        parser.add_argument(
            'brokers',
            nargs='*',
            help='brokers to run, every broker when none is named',
        )
        parser.add_argument(
            '--record',
            action='store_true',
            help='rewrite the named brokers\' recordings from the current code',
        )
        arguments = parser.parse_args()
        brokers = arguments.brokers or list(BROKER_CASES)
        for broker in brokers:
            if broker not in BROKER_CASES:
                print(f'No cases for {broker!r}. Known brokers: {", ".join(BROKER_CASES)}')
                return 2
        os.environ['TZ'] = 'Asia/Kolkata'
        time.tzset()
        results = self.run_brokers(brokers)
        if arguments.record:
            return self.record(brokers, results)
        return self.compare(brokers, results)


if __name__ == '__main__':
    sys.exit(WebsocketFeedsSuite().run())
