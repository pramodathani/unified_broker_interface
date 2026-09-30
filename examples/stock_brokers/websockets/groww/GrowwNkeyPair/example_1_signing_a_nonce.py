"""Generates a Groww NATS key pair, signs a server nonce with it, and verifies the signature.

Before each Groww connection a socket generates a fresh ed25519 key pair, sends its public key as a NATS user NKEY to obtain a socket JWT, and later signs the nonce from the server's INFO line with the private key. `GrowwNkeyPair.public_key` is the NKEY: base32 of a user prefix byte, the raw public key and a CRC-16 checksum, so it always starts with `U` and has 56 characters. `signed_nonce` returns the signature base64url encoded without padding, as NATS expects.

The key is random on every run, so this program prints properties of the key and the signature rather than their values, and checks the signature by decoding the NKEY back to the raw public key and verifying with the `cryptography` package, the same library the class uses. It needs no stand-ins.

Notice that the signature verifies against the nonce it signed and not against a different one.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwNkeyPair/example_1_signing_a_nonce.py
"""

import base64

from cryptography.exceptions import (
    InvalidSignature,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)
from stock_brokers.websockets.groww import (
    GrowwNkeyPair,
)


class SigningANonceExample:
    """Signs a nonce with a fresh key pair and verifies it.

    Attributes:
        key_pair (GrowwNkeyPair): The key pair being shown.
    """

    def __init__(self):
        """Generates the key pair.

        Returns:
            None: This method returns nothing.
        """
        self.key_pair = GrowwNkeyPair()

    def verifies(self, signature, nonce):
        """Says whether a signature verifies against a nonce with the key pair's public key.

        Args:
            signature (str): The base64url signature without padding.
            nonce (str): The nonce.

        Returns:
            bool: True when the signature is valid for the nonce.
        """
        public_key_bytes = base64.b32decode(self.key_pair.public_key)[1:33]
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        raw_signature = base64.urlsafe_b64decode(signature + '==')
        try:
            public_key.verify(raw_signature, nonce.encode())
        except InvalidSignature:
            return False
        return True

    def run(self):
        """Prints the key's form, signs a nonce, and verifies the signature against two nonces.

        Returns:
            None: This method returns nothing.
        """
        public_key = self.key_pair.public_key
        print(f'Public key starts with {public_key[0]} and has {len(public_key)} characters')
        signature = self.key_pair.signed_nonce('example-nonce')
        print(f'Signature has {len(signature)} characters and no padding: {not signature.endswith("=")}')
        print(f"Verifies against the signed nonce: {self.verifies(signature, 'example-nonce')}")
        print(f"Verifies against another nonce: {self.verifies(signature, 'other-nonce')}")


if __name__ == '__main__':
    SigningANonceExample().run()
