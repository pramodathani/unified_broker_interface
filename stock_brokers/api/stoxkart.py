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

        The stored token counts as expired only when Stoxkart rejects it as unauthorised. Any other error while checking it, such as a network outage, is raised so that it is not mistaken for a reason to log in.

        The login has three steps. The client id and password are posted to `/auth/v2/login`, which answers with a register token. The current TOTP and the register token are posted to `/auth/v2/twofa/verify`, which answers with a request token. The request token is then exchanged at `/auth/token` for an access token, which is stored in MongoDB first and Redis second so that every process uses it.

        The two version 2 steps carry everything in headers, send an empty JSON body, and include the publisher key pair from the `publisher_api_key` and `publisher_api_secret` fields of the `stoxkart` settings document. That pair is separate from the app's own `api_key` and `api_secret`. The steps do not go through `_request`, because no access token exists yet.

        Args:
            force_login (bool): When True, the stored token is not checked and a fresh login is always made.

        Raises:
            StoxkartAPIException: Checking the stored token failed for a reason other than an expired session, the settings document has no publisher key pair, Stoxkart refused a login step or answered with something other than JSON, the account must change its password or has no TOTP enabled, or an answer left out the token the next step needs.
        """
        super().__init__(broker_name="stoxkart")

        if not force_login:
            self._current_login()
            if self._last_login and self._last_login.get("access_token"):
                try:
                    self.get(url=f"{BASE_URL}/funds")
                except StoxkartAPIException as error:
                    if str(error.code) not in ("AuthorizationError", "401", "Invalid Session"):
                        raise
                    self._logger.info(msg="Stoxkart session expired, logging in again.")
                else:
                    return

        publisher_api_key = self._settings.get("publisher_api_key")
        publisher_api_secret = self._settings.get("publisher_api_secret")
        if not publisher_api_key or not publisher_api_secret:
            raise StoxkartAPIException(
                code="500",
                message="The stoxkart settings document needs publisher_api_key and publisher_api_secret for the version 2 login.",
            )

        login_headers = {
            "platform": "api",
            "client-id": self._settings["ucc_code"],
            "device-id": LOGIN_DEVICE_ID,
            "x-api-key": publisher_api_key,
            "x-api-secret": publisher_api_secret,
            "api-version": LOGIN_API_VERSION,
            "client-version": LOGIN_CLIENT_VERSION,
        }
        login_session = requests.Session()

        password_headers = dict(login_headers)
        password_headers["password"] = self._settings["api_password"]
        response = login_session.post(
            f"{BASE_URL}/auth/v2/login",
            params={"api-key": self._settings["api_key"]},
            json={},
            headers=password_headers,
            timeout=LOGIN_TIMEOUT_SECONDS,
        )
        try:
            body = response.json()
        except ValueError as error:
            raise StoxkartAPIException(
                code=response.status_code,
                message=f"Stoxkart returned a non-JSON response for /auth/v2/login: {response.text[:300]}",
            ) from error
        if response.status_code >= 300:
            code = body.get("status_code") or body.get("code") or response.status_code
            message = body.get("status_message") or body.get("message") or body
            raise StoxkartAPIException(
                code=code,
                message=f"Stoxkart rejected /auth/v2/login with HTTP {response.status_code}: {message}",
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

        totp = pyotp.TOTP(self._settings["totp_secret"])
        seconds_left = totp.interval - time.time() % totp.interval
        if seconds_left < TOTP_MINIMUM_SECONDS_LEFT:
            time.sleep(seconds_left + 1)

        totp_headers = dict(login_headers)
        totp_headers["second-auth-type"] = "TOTP"
        totp_headers["second-auth-value"] = totp.now()
        totp_headers["registered-token"] = register_token
        response = login_session.post(
            f"{BASE_URL}/auth/v2/twofa/verify",
            params={"api-key": self._settings["api_key"]},
            json={},
            headers=totp_headers,
            timeout=LOGIN_TIMEOUT_SECONDS,
        )
        try:
            body = response.json()
        except ValueError as error:
            raise StoxkartAPIException(
                code=response.status_code,
                message=f"Stoxkart returned a non-JSON response for /auth/v2/twofa/verify: {response.text[:300]}",
            ) from error
        if response.status_code >= 300:
            code = body.get("status_code") or body.get("code") or response.status_code
            message = body.get("status_message") or body.get("message") or body
            raise StoxkartAPIException(
                code=code,
                message=f"Stoxkart rejected /auth/v2/twofa/verify with HTTP {response.status_code}: {message}",
            )

        request_token = (body.get("data") or {}).get("request_token")
        if not request_token:
            raise StoxkartAPIException(
                code="500",
                message=f"Stoxkart verified the TOTP but returned no request_token: {body}",
            )

        app_key = self._settings["api_key"]
        signature = hmac.new(
            (app_key + request_token).encode("utf-8"),
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

        last_login = {
            "broker_name": "stoxkart",
            "access_token": data["data"]["access_token"],
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
