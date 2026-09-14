"""
Holding a broker's quote requests back after it has refused them for a reason retrying makes worse.

The quote service asks a broker on every request the cache cannot answer, so a broker that is refusing
this client - a rate limit, a firewall ban on the IP address, an account without the data entitlement -
would otherwise be asked again on the very next request, and the one after. For a rate limit that keeps
the limit hit; for Cloudflare's ban in front of Fyers every further request extends the ban. A pause
stops the module from sending anything for a while and lets the service move on to the next broker.
"""

import threading
import time

class RefusalPause:
    """
    Remembers, per worker, until when a broker's quote endpoint is not to be called.
    """

    def __init__(self):
        self._until = 0.0
        self._reason = None
        self._lock = threading.Lock()

    def pause(self, seconds, reason):
        """
        Stop calling the endpoint for a while. A longer pause already in force is kept.

        - `seconds` is how long to hold back.
        - `reason` says why, for the refusal message.
        """
        with self._lock:
            until = time.time() + seconds
            if until > self._until:
                self._until = until
                self._reason = reason

    def remaining(self):
        """
        The seconds left in the pause and its reason, or None when calling is allowed.
        """
        with self._lock:
            left = self._until - time.time()
            return (left, self._reason) if left > 0 else None
