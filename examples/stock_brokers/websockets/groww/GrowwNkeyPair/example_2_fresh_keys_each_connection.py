"""Shows that every Groww key pair is fresh, and that a nonce signs the same whether given as text or bytes.

A Groww socket makes a new `GrowwNkeyPair` for every connection, so a socket JWT obtained for one connection cannot be reused with another key. `signed_nonce` accepts the nonce as text or bytes, encoding text first, and ed25519 signatures are deterministic, so the same key signs the same nonce identically either way.

The keys are random, so this program compares them rather than printing them. It needs no stand-ins.

Notice that the two public keys differ, and that the text and bytes nonces give the same signature.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwNkeyPair/example_2_fresh_keys_each_connection.py
"""


from stock_brokers.websockets.groww import (
    GrowwNkeyPair,
)


class FreshKeysEachConnectionExample:
    """Compares two key pairs and two ways of passing a nonce.

    Attributes:
        first_key_pair (GrowwNkeyPair): The key pair of one connection.
        second_key_pair (GrowwNkeyPair): The key pair of the next connection.
    """

    def __init__(self):
        """Generates two key pairs.

        Returns:
            None: This method returns nothing.
        """
        self.first_key_pair = GrowwNkeyPair()
        self.second_key_pair = GrowwNkeyPair()

    def run(self):
        """Prints whether the keys differ and whether the two nonce forms sign alike.

        Returns:
            None: This method returns nothing.
        """
        print(f'The two public keys differ: {self.first_key_pair.public_key != self.second_key_pair.public_key}')
        from_text = self.first_key_pair.signed_nonce('example-nonce')
        from_bytes = self.first_key_pair.signed_nonce(b'example-nonce')
        print(f'Text and bytes nonces sign alike: {from_text == from_bytes}')
        other_key = self.second_key_pair.signed_nonce('example-nonce')
        print(f'Another key signs differently: {from_text != other_key}')


if __name__ == '__main__':
    FreshKeysEachConnectionExample().run()
