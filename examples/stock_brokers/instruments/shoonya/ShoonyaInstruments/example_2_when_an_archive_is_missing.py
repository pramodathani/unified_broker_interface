"""Shows the two ways `ShoonyaInstruments.download` fails: an archive that cannot be fetched, and archives that hold nothing readable.

`download` checks every archive's HTTP status and raises `requests.HTTPError` as soon as one fails, so a day's master is never stored with an exchange silently missing. When every archive downloads but none holds a `.txt` or `.csv` file, it raises `ValueError` instead, because an empty master is not a result worth storing.

The program must not download anything, so `requests.get` is replaced, only while `download` runs, by `FailingArchiveServer`, a stand-in built for each case. In the first case it answers the MCX archive with a 404, and in the second it serves every archive with only a `README.md` inside. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice that the first case stops at the fourth archive, the MCX one, without asking for the other three.

Run it from the project root:

    python examples/stock_brokers/instruments/shoonya/ShoonyaInstruments/example_2_when_an_archive_is_missing.py
"""

import io
import unittest.mock
import zipfile

import requests

from stock_brokers.instruments.shoonya import (
    ShoonyaInstruments,
)


class FailingArchiveServer:
    """A stand-in for `requests.get` that serves archives with nothing readable in them, and optionally fails one URL.

    Attributes:
        missing_archive (str | None): The file name of the archive to answer with a 404, or None to answer every one.
        urls_asked (list): Every URL requested, in order.
    """

    def __init__(self, missing_archive):
        """Holds the name of the archive to fail.

        Args:
            missing_archive (str | None): The file name of the archive to answer with a 404, or None to answer every one.

        Returns:
            None: This method returns nothing.
        """
        self.missing_archive = missing_archive
        self.urls_asked = []

    def archive_without_data(self):
        """Builds a ZIP archive holding only a README file.

        Returns:
            bytes: The archive.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('README.md', 'Symbols are published after 08:00 IST.\n')
        return buffer.getvalue()

    def get(self, url, timeout=None):
        """Serves one archive, or a 404 for the missing one, in place of `requests.get`.

        Args:
            url (str): The archive's URL.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: A 404 for the missing archive, otherwise an archive with no data file.
        """
        self.urls_asked.append(url)
        response = requests.Response()
        response.url = url
        if url.endswith('/' + str(self.missing_archive)):
            response.status_code = 404
            response.reason = 'Not Found'
            response.headers['Content-Type'] = 'text/html'
            response._content = b'<html><body>Not Found</body></html>'
            return response
        response.status_code = 200
        response.headers['Content-Type'] = 'application/zip'
        response._content = self.archive_without_data()
        return response


class WhenAnArchiveIsMissingExample:
    """Runs `download` against a server missing one archive and against one serving no data.

    Attributes:
        instruments (ShoonyaInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = ShoonyaInstruments()

    def run(self):
        """Runs both cases and prints what each raised.

        Returns:
            None: This method returns nothing.
        """
        server = FailingArchiveServer('MCX_symbols.txt.zip')
        with unittest.mock.patch.object(requests, 'get', server.get):
            try:
                self.instruments.download()
            except requests.HTTPError as error:
                print(f'Raised {type(error).__name__}: {error}')
        print(f'Archives asked for: {len(server.urls_asked)}')

        server = FailingArchiveServer(None)
        with unittest.mock.patch.object(requests, 'get', server.get):
            try:
                self.instruments.download()
            except ValueError as error:
                print(f'Raised {type(error).__name__}: {error}')
        print(f'Archives asked for: {len(server.urls_asked)}')


if __name__ == '__main__':
    WhenAnArchiveIsMissingExample().run()
