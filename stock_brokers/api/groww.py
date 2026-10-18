import os
import pyotp
import requests
import time
import json as json_lib
from datetime import datetime

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

USER_DETAIL_URL = "https://api.groww.in/v1/user/detail"
TOKEN_URL = "https://api.groww.in/v1/token/api/access"

BLOCKED_KEY = "groww:api:blocked-until"
BLOCKED_SECONDS = 300

TOKEN_LOCK_KEY = "groww:login:token-lock"
TOKEN_LOCK_SECONDS = 60
TOKEN_ATTEMPT_KEY = "groww:login:token-attempt"
TOKEN_ATTEMPT_INTERVAL_SECONDS = 60
WAIT_FOR_OTHER_LOGIN_SECONDS = 60
WAIT_POLL_SECONDS = 2

class GrowwAPIException(BrokerAPIException):
    """A Groww broker API error.

    Attributes:
        status_code (int | None): The HTTP status of the refused request, or None when no request was sent.
    """

    def __init__(self, code=None, message=None, status_code=None):
        """Records the error and the HTTP status of the refusal.

        Args:
            code (str | int | None): Groww's own error code when it gave one, otherwise the HTTP status.
            message (object): Groww's error message, or the whole error body when it gave no message.
            status_code (int | None): The HTTP status of the refused request, or None when no request was sent.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(code=code, message=message)
        self.status_code = status_code

class GrowwBlockedError(GrowwAPIException):
    """Groww is limiting this account's requests with HTTP 429, so nothing is sent until the limit has had time to lift."""

class GrowwAPI(BrokerAPI):
    """
    Groww API class
    """

    def __init__(self):
        """Probes the stored session and logs in only when Groww says the session is dead.

        Returns:
            None: This method returns nothing.

        Raises:
            GrowwBlockedError: Groww is limiting this account, so no login is attempted.
            GrowwAPIException: The probe failed for a reason a login cannot fix, or the login failed.
        """
        super().__init__(broker_name="groww")

        try:
            self.get(url=USER_DETAIL_URL)
        except GrowwBlockedError:
            raise
        except GrowwAPIException as exception:
            if exception.status_code != 401:
                raise
            self._log_in()
        except (KeyError, TypeError):
            self._log_in()

    def _log_in(self):
        """Gets a new access token, letting only one process at a time ask Groww for it.

        Every Groww script builds its own `GrowwAPI`, so at the daily token expiry they all find the session dead at once. The process that takes the Redis lock asks Groww; the others wait for its token, which every request reads from Redis.

        Returns:
            None: This method returns nothing.

        Raises:
            GrowwBlockedError: Groww is limiting this account.
            GrowwAPIException: Another process's login produced no new token, or Groww refused the token request.
        """
        stale_login = dict(self._last_login or {})
        lock_value = str(os.getpid())
        acquired = self._cache.set(TOKEN_LOCK_KEY, lock_value, nx=True, ex=TOKEN_LOCK_SECONDS)
        if not acquired:
            self._wait_for_other_login(stale_login)
            return

        try:
            if self._has_newer_login(stale_login):
                self._logger.info("Another process logged Groww in moments ago. Using its token.")
                return
            last_attempt = float(self._cache.get(TOKEN_ATTEMPT_KEY) or 0)
            seconds_since_attempt = time.time() - last_attempt
            if seconds_since_attempt < TOKEN_ATTEMPT_INTERVAL_SECONDS:
                raise GrowwAPIException(code="500", message=f"Groww was asked for a token {seconds_since_attempt:.0f} s ago, so another request waits until {TOKEN_ATTEMPT_INTERVAL_SECONDS} s have passed.")
            self._cache.set(TOKEN_ATTEMPT_KEY, str(time.time()))
            self._request_new_token()
        finally:
            if self._cache.get(TOKEN_LOCK_KEY) == lock_value:
                self._cache.delete(TOKEN_LOCK_KEY)

    def _request_new_token(self):
        """Exchanges the TOTP token and a TOTP for a new access token, and stores it in MongoDB and Redis.

        Returns:
            None: This method returns nothing.

        Raises:
            GrowwBlockedError: Groww is limiting this account.
            GrowwAPIException: Groww refused the request or answered without a token.
        """
        headers = {
            "Authorization": f"Bearer {self._settings['totp_token']}",
            "Content-Type": "application/json"
        }
        body = {
            "key_type": "totp",
            "totp": pyotp.TOTP(self._settings["totp_secret"]).now()
        }
        self._logger.warning("Asking Groww for a new access token.")
        answer = self.post(url=TOKEN_URL, data=json_lib.dumps(body), headers=headers)
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict) or "token" not in data:
            raise GrowwAPIException(code="500", message=f"Groww answered the token request without a token: {str(answer)[:300]}")

        last_login = {
            "broker_name": "groww",
            "access_token": data["token"],
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        }
        self._mongo_db["last_login"].replace_one({"broker_name": "groww"}, last_login, upsert=True)
        self._cache.hset("last_login", "groww", json_lib.dumps(last_login))
        self._last_login = last_login

    def _has_newer_login(self, stale_login):
        """Whether the login in force is newer than the one that was found dead.

        Args:
            stale_login (dict): The `last_login` document whose token Groww refused, or an empty dictionary when there was none.

        Returns:
            bool: True when another process has stored a newer login.
        """
        current_moment = self._login_moment(self._current_login())
        if current_moment is None:
            return False
        stale_moment = self._login_moment(stale_login)
        return stale_moment is None or current_moment > stale_moment

    def _wait_for_other_login(self, stale_login):
        """Waits while another process holds the token lock, then uses the token it stored.

        Args:
            stale_login (dict): The `last_login` document whose token Groww refused.

        Returns:
            None: This method returns nothing.

        Raises:
            GrowwAPIException: The other process finished, or the wait ran out, without a newer login being stored.
        """
        self._logger.info("Another process is logging Groww in. Waiting for its token.")
        deadline = time.time() + WAIT_FOR_OTHER_LOGIN_SECONDS
        while time.time() < deadline:
            time.sleep(WAIT_POLL_SECONDS)
            if self._has_newer_login(stale_login):
                self._logger.info("Another process logged Groww in. Using its token.")
                return
            if not self._cache.exists(TOKEN_LOCK_KEY):
                break
        if self._has_newer_login(stale_login):
            return
        raise GrowwAPIException(code="500", message="Another process tried to log Groww in and no new token was stored.")

    def _blocked_until(self):
        """When Groww's limit on this account is expected to have lifted, as recorded by any process.

        A cache that cannot be read never stops a request.

        Returns:
            float | None: The epoch until which nothing is sent, or None when no limit is recorded.
        """
        try:
            raw = self._cache.get(BLOCKED_KEY)
        except Exception:
            return None
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _record_block(self):
        """Records for every process that Groww limited this account, so none sends anything for a while.

        Returns:
            float: The epoch until which nothing is sent.
        """
        until = time.time() + BLOCKED_SECONDS
        try:
            self._cache.set(BLOCKED_KEY, str(until), ex=BLOCKED_SECONDS)
        except Exception:
            pass
        return until

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        Private generic REST API request to Broker API server.
        This is specialized into GET, POST, PUT, PATCH and DELETE by public methods.

        Nothing is sent while a 429 from Groww is recorded in Redis, and a new 429 records one, because every request sent into a limit renews it.

        - `method`: HTTP method to use for the request.
        - `url`: URL of the API endpoint.
        - `params`: Dictionary of parameters to be sent as part of the request.
        - `data`: Dictionary, bytes, or file-like object to send in the body of the request.
        - `headers`: Dictionary of HTTP headers to be sent with the request.
        - `cookies`: Dictionary of cookies to be sent with the request.
        - `files`: Dictionary of files to be sent with the request.
        - `auth`: Authentication tuple or object to be sent with the request.
        - `timeout`: Timeout value for the request.
        - `allow_redirects`: Boolean value indicating whether redirects should be allowed.
        - `proxies`: Dictionary of proxy settings for the request.
        - `hooks`: Dictionary of hooks to be called during the request lifecycle.
        - `stream`: Boolean value indicating whether response content should be streamed.
        - `verify`: Boolean value indicating whether SSL certificate verification should be performed.
        - `cert`: Certificate file or tuple containing certificate and key files for client-side SSL certificate verification.
        - `json`: JSON data to send in the body of the request.
        - `verbose`: If set to True, the request and response are logged.

        Returns:
            dict: The answer, with `timestamp`, `status`, `code` and `data`.

        Raises:
            GrowwBlockedError: A limit is recorded, or Groww answered with HTTP 429.
            GrowwAPIException: Groww answered with any other error status.
        """
        blocked_until = self._blocked_until()
        if blocked_until is not None and blocked_until > time.time():
            until_text = datetime.fromtimestamp(blocked_until).strftime("%H:%M:%S")
            raise GrowwBlockedError(code="429", message=f"Groww limited this account's requests, so nothing is sent until {until_text}.")

        self._current_login()
        if headers is None:
            headers = {
                'Accept': 'application/json',
                'Authorization': f"Bearer {self._last_login['access_token']}",
                'X-API-Version': '1.0'
            }

        if verbose == True:
            rest_api_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S:%f')} - requests.request(method='{method}', url='{url}', params={params}, data={data}, headers={headers}, cookies={cookies}, files={files}, auth={auth}, timeout={timeout}, allow_redirects={allow_redirects}, proxies={proxies}, hooks={hooks}, stream={stream}, verify={verify}, cert={cert}, json={json})"
            self._cache.rpush('broker_api_calls', rest_api_message)
            self._logger.info(rest_api_message)

        response = requests.request(method=method, url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)

        if response.status_code < 300:
            content = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "status": "success",
                "code": response.status_code
            }

            if "json" in response.headers["Content-Type"]:
                if "payload" in response.json():
                    content["data"] = response.json()["payload"]
                else:
                    content["data"] = response.json()
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "payload" in json_content:
                        content["data"] = json_content["payload"]
                    else:
                        content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content

        raise self._refusal(response)

    def _refusal(self, response):
        """Builds the exception for an error answer, so that every error status raises.

        Groww nests its error under `error`, with a `code` and a `message`; when either is missing, or the body is not that shape, the whole body is the message and the HTTP status the code.

        Args:
            response (requests.Response): The error answer.

        Returns:
            GrowwAPIException: A GrowwBlockedError for HTTP 429, otherwise a GrowwAPIException.
        """
        body = response.content.decode("utf-8", errors="replace").strip()
        try:
            json_content = json_lib.loads(body)
        except json_lib.JSONDecodeError:
            json_content = None

        code = response.status_code
        message = json_content if json_content is not None else body
        if isinstance(json_content, dict):
            error = json_content.get("error")
            if isinstance(error, dict) and "code" in error and "message" in error:
                code = error["code"]
                message = error["message"]

        if response.status_code == 429:
            until_text = datetime.fromtimestamp(self._record_block()).strftime("%H:%M:%S")
            self._logger.warning(f"Groww limited this account with HTTP 429. Sending nothing until {until_text}.")
            return GrowwBlockedError(code=code, message=message, status_code=response.status_code)
        return GrowwAPIException(code=code, message=message, status_code=response.status_code)
