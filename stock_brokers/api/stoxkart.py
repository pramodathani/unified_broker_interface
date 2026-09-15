"""Stoxkart's REST API, with the client id, password and TOTP login that obtains its access token.

Typical usage example:

  stoxkart = StoxkartAPI()
  funds = stoxkart.get(url=f"{BASE_URL}/funds")
"""
import hashlib
import hmac
import json as json_lib
import time
from datetime import datetime

import pyotp
import requests

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

BASE_URL = "https://openapi.stoxkart.com"
LOGIN_DEVICE_ID = "developer-portal"
LOGIN_API_VERSION = "v2"
LOGIN_CLIENT_VERSION = "dev-portal"
LOGIN_TIMEOUT_SECONDS = 30
TOTP_MINIMUM_SECONDS_LEFT = 5


class StoxkartAPIException(BrokerAPIException):
    """An error returned by Stoxkart's API, or a Stoxkart response that could not be used."""


class StoxkartAPI(BrokerAPI):
    """A session with Stoxkart's REST API for the account in the `stoxkart` settings document."""

    def __init__(self, force_login=False):
        """Checks the stored access token and logs in again when Stoxkart no longer accepts it.

        Args:
            force_login (bool): When True, the stored token is not checked and a fresh login is always made.

        Raises:
            StoxkartAPIException: Stoxkart refused a login step, or checking the stored token failed for a reason other than an expired session.
        """
        super().__init__(broker_name="stoxkart")

        if not force_login and self._has_valid_session():
            return

        self._login()

    def _has_valid_session(self):
        """Reports whether Stoxkart still accepts the current access token.

        Only an authentication failure counts as an expired session. Any other error, such as a network outage, is raised so that it is not mistaken for a reason to log in.

        Returns:
            bool: True when the token is accepted, and False when there is no token or Stoxkart rejects it as unauthorised.

        Raises:
            StoxkartAPIException: The check failed for a reason other than authentication.
        """
        self._current_login()
        if not self._last_login or not self._last_login.get("access_token"):
            return False

        try:
            self.get(url=f"{BASE_URL}/funds")
            return True
        except StoxkartAPIException as error:
            if str(error.code) in ("AuthorizationError", "401", "Invalid Session"):
                self._logger.info(msg="Stoxkart session expired, logging in again.")
                return False
            raise

    def _login(self):
        """Logs in with the client id, password and TOTP, and stores the resulting access token.

        Raises:
            StoxkartAPIException: Stoxkart refused one of the login steps or left a token out of its answer.
        """
        self._login_session = requests.Session()
        register_token = self._register_token()
        request_token = self._verify_totp(register_token)
        access_token = self._exchange_request_token(request_token)
        self._persist_access_token(access_token)

    def _login_headers(self):
        """Builds the headers that every step of the version 2 login sends.

        The publisher key pair is read from the `publisher_api_key` and `publisher_api_secret` fields of the `stoxkart` settings document, and is separate from the app's own `api_key` and `api_secret`.

        Returns:
            dict: The platform, client id, device and publisher key headers, keyed by header name.

        Raises:
            StoxkartAPIException: The settings document has no publisher key pair.
        """
        publisher_api_key = self._settings.get("publisher_api_key")
        publisher_api_secret = self._settings.get("publisher_api_secret")
        if not publisher_api_key or not publisher_api_secret:
            raise StoxkartAPIException(
                code="500",
                message="The stoxkart settings document needs publisher_api_key and publisher_api_secret for the version 2 login.",
            )

        return {
            "platform": "api",
            "client-id": self._settings["ucc_code"],
            "device-id": LOGIN_DEVICE_ID,
            "x-api-key": publisher_api_key,
            "x-api-secret": publisher_api_secret,
            "api-version": LOGIN_API_VERSION,
            "client-version": LOGIN_CLIENT_VERSION,
        }

    def _login_post(self, path, step_headers):
        """Posts one step of the version 2 login and returns Stoxkart's decoded answer.

        The login steps carry everything in headers and send an empty JSON body. They do not go through `_request`, because no access token exists yet.

        Args:
            path (str): The endpoint path, such as `/auth/v2/login`.
            step_headers (dict): The headers this step adds to the common login headers.

        Returns:
            dict: The decoded JSON answer.

        Raises:
            StoxkartAPIException: Stoxkart answered with an error status or with something other than JSON.
        """
        headers = self._login_headers()
        headers.update(step_headers)
        response = self._login_session.post(
            f"{BASE_URL}{path}",
            params={"api-key": self._settings["api_key"]},
            json={},
            headers=headers,
            timeout=LOGIN_TIMEOUT_SECONDS,
        )

        try:
            body = response.json()
        except ValueError as error:
            raise StoxkartAPIException(
                code=response.status_code,
                message=f"Stoxkart returned a non-JSON response for {path}: {response.text[:300]}",
            ) from error

        if response.status_code >= 300:
            code = body.get("status_code") or body.get("code") or response.status_code
            message = body.get("status_message") or body.get("message") or body
            raise StoxkartAPIException(
                code=code,
                message=f"Stoxkart rejected {path} with HTTP {response.status_code}: {message}",
            )

        return body

    def _register_token(self):
        """Sends the client id and password and returns the token that the TOTP step needs.

        Returns:
            str: The register token from Stoxkart's answer.

        Raises:
            StoxkartAPIException: The password was refused, the account must change its password first, TOTP is not enabled on the account, or the answer had no register token.
        """
        body = self._login_post(
            "/auth/v2/login",
            {
                "password": self._settings["api_password"],
            },
        )
        data = body.get("data") or {}

        if data.get("is_change_pwd_required"):
            raise StoxkartAPIException(
                code="500",
                message="Stoxkart requires the account's password to be changed before it can log in.",
            )

        if not data.get("is_2fa_enabled"):
            raise StoxkartAPIException(
                code="500",
                message="Stoxkart asked for an SMS OTP rather than a TOTP, so TOTP must be enabled on the account before it can log in unattended.",
            )

        register_token = data.get("register_token")
        if not register_token:
            raise StoxkartAPIException(
                code="500",
                message=f"Stoxkart's login answer contained no register_token: {body}",
            )

        return register_token

    def _verify_totp(self, register_token):
        """Sends the current TOTP and returns the request token that is exchanged for an access token.

        Args:
            register_token (str): The token returned by the password step.

        Returns:
            str: The request token from Stoxkart's answer.

        Raises:
            StoxkartAPIException: The TOTP was refused or the answer had no request token.
        """
        body = self._login_post(
            "/auth/v2/twofa/verify",
            {
                "second-auth-type": "TOTP",
                "second-auth-value": self._current_totp(),
                "registered-token": register_token,
            },
        )

        request_token = (body.get("data") or {}).get("request_token")
        if not request_token:
            raise StoxkartAPIException(
                code="500",
                message=f"Stoxkart verified the TOTP but returned no request_token: {body}",
            )

        return request_token

    def _current_totp(self):
        """Returns a TOTP code that will stay valid while the request is in flight.

        When the current code has fewer than `TOTP_MINIMUM_SECONDS_LEFT` seconds left, this waits for the next code.

        Returns:
            str: The six digit TOTP code.
        """
        totp = pyotp.TOTP(self._settings["totp_secret"])
        seconds_left = totp.interval - time.time() % totp.interval
        if seconds_left < TOTP_MINIMUM_SECONDS_LEFT:
            time.sleep(seconds_left + 1)
        return totp.now()

    def _exchange_request_token(self, request_token):
        """Exchanges a request token for an access token.

        The signature is an HMAC-SHA256 whose key is the app's API key followed by the request token and whose message is the app's API secret.

        Args:
            request_token (str): The token returned by the TOTP step.

        Returns:
            str: The access token.

        Raises:
            StoxkartAPIException: Stoxkart refused the exchange or its answer had no access token.
        """
        app_key = self._settings["api_key"]
        key = (app_key + request_token).encode("utf-8")

        signature = hmac.new(
            key,
            self._settings["api_secret"].encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        params = {
            "api_key": app_key,
            "signature": signature,
            "req_token": request_token,
        }

        data = self.post(
            f"{BASE_URL}/auth/token",
            data=json_lib.dumps(params),
            headers={
                "Content-Type": "application/json",
            },
        )

        if "data" not in data or "access_token" not in data["data"]:
            raise StoxkartAPIException(
                code="500",
                message=f"Cannot get access token from the Stoxkart server. Response: {data}",
            )

        return data["data"]["access_token"]

    def _persist_access_token(self, access_token):
        """Stores the access token in MongoDB and then in Redis, so that every process uses it.

        Args:
            access_token (str): The token returned by the token exchange.
        """
        last_login = {
            "broker_name": "stoxkart",
            "access_token": access_token,
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }
        self._mongo_db["last_login"].replace_one({"broker_name": "stoxkart"}, last_login, upsert=True)
        self._cache.hset("last_login", "stoxkart", json_lib.dumps(last_login))
        self._last_login = last_login

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        Private generic REST API request to Broker API server.
        This is specialized into GET, POST, PUT, PATCH and DELETE by public methods.

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
        """
        self._current_login()

        if headers is None:
            headers = {
                "X-Client-Id": self._settings['ucc_code'],
                "X-Platform" : "api",
                "X-Api-Key": self._settings['api_key'],
                "X-Access-Token" : self._last_login["access_token"]
            }
        
        if verbose == True:
            rest_api_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S:%f')} - requests.request(method='{method}', url='{url}', params={params}, data={data}, headers={headers}, cookies={cookies}, files={files}, auth={auth}, timeout={timeout}, allow_redirects={allow_redirects}, proxies={proxies}, hooks={hooks}, stream={stream}, verify={verify}, cert={cert}, json={json})"
            self._cache.rpush('broker_api_calls', rest_api_message)
            self._logger.info(rest_api_message)            
                        
        response = requests.request(method=method, url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)

        content_type = response.headers.get("Content-Type", "")

        if response.status_code < 300:
            content = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "status": "success",
                "code": response.status_code
            }
            
            if "json" in content_type:
                body = response.json()
                content["data"] = body["data"] if "data" in body else body
            elif "text" in content_type:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "data" in json_content:
                        content["data"] = json_content["data"]
                    else:
                        content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in content_type:
                json_content = response.json()
                if "code" in json_content and "message" in json_content:
                    raise StoxkartAPIException(code=json_content["code"], message=json_content["message"])
                else:
                    raise StoxkartAPIException(code=response.status_code, message=json_content)
            elif "text" in content_type:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "code" in json_content and "message" in json_content:
                        raise StoxkartAPIException(code=json_content["code"], message=json_content["message"])
                    else:
                        raise StoxkartAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise StoxkartAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise StoxkartAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
