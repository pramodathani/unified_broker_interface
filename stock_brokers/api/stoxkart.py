import hmac
import pyotp
import hashlib
import requests
import json as json_lib
from datetime import datetime
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import *
from selenium.webdriver.common.by import By
from urllib.parse import urlparse, parse_qs

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

BASE_URL = "https://openapi.stoxkart.com"
LOGIN_PORTAL_URL = "https://superrtrade.stoxkart.com/login"


class StoxkartAPIException(BrokerAPIException):
    """Raised for Stoxkart broker API errors."""


class StoxkartAPI(BrokerAPI):
    """
    Stoxkart API class
    """

    def __init__(self, force_login=False):
        """
        Stoxkart API class.

        On construction the existing access token is validated against the broker.
        If it is missing or stale a fresh login is performed and the new token is
        persisted to MongoDB and Redis.

        - `force_login`: skip the cached-session check and always log in again.
        """
        super().__init__(broker_name="stoxkart")

        if not force_login and self._has_valid_session():
            return

        self._login()

    def _has_valid_session(self):
        """
        Returns True when the cached access token is still accepted by the broker.

        Only an authentication failure is treated as "needs login"; any other
        error (network outage, broker downtime) is propagated so that a transient
        problem is not silently turned into a full login attempt.
        """
        # Another process may have logged in since this object was built.
        self._current_login()
        if not self._last_login or not self._last_login.get("access_token"):
            return False

        try:
            self.get(url=f"{BASE_URL}/funds")
            return True
        except StoxkartAPIException as e:
            if str(e.code) in ("AuthorizationError", "401", "Invalid Session"):
                self._logger.info(msg="Stoxkart session expired, logging in again.")
                return False
            raise

    def _login(self):
        """
        Logs in to Stoxkart and stores the resulting access token.

        The direct REST login documented at
        https://developers.stoxkart.com/api-documentation/login is attempted
        first because it needs no browser. The Selenium based portal login is
        kept as a fallback for the case where the REST flow is unavailable.
        """
        try:
            request_token = self._request_token_via_rest()
        except StoxkartAPIException:
            raise
        except Exception as e:
            self._logger.warning(msg=f"Stoxkart REST login failed ({e}), falling back to browser login.")
            request_token = self._request_token_via_browser()

        access_token = self._exchange_request_token(request_token)
        self._persist_access_token(access_token)

    def _auth_post(self, path, payload):
        """
        Posts to an unauthenticated Stoxkart `/auth/*` endpoint and returns the
        decoded JSON body. Login endpoints are not covered by `_request` because
        they must not send the (not yet existing) access token headers.

        - `path`: endpoint path, e.g. `/auth/login`.
        - `payload`: dictionary sent as the JSON request body.
        """
        url = f"{BASE_URL}{path}?api-key={self._settings['api_key']}"
        response = self._session.post(
            url,
            data=json_lib.dumps(payload),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )

        try:
            body = response.json()
        except ValueError:
            raise StoxkartAPIException(
                code=response.status_code,
                message=f"Stoxkart returned a non-JSON response for {path}: {response.text[:300]}",
            )

        if response.status_code >= 300:
            code = body.get("status_code") or body.get("code") or response.status_code
            message = body.get("status_message") or body.get("message") or body

            if str(code) == "E-011" or "API Key not found" in str(message):
                raise StoxkartAPIException(
                    code="E-011",
                    message=(
                        f"Stoxkart does not recognise API key '{self._settings['api_key']}' "
                        f"(endpoint {path} returned 'API Key not found'). The client id, password "
                        "and TOTP are not the problem - the app registration itself is missing or "
                        "revoked. Regenerate the API key/secret under MyApps on "
                        "https://developers.stoxkart.com and update the 'stoxkart' document in the "
                        "MongoDB 'settings' collection."
                    ),
                )

            if str(code) == "E-010" or "Invalid X-API-Key" in str(message):
                raise StoxkartAPIException(
                    code="E-010",
                    message=(
                        f"Stoxkart rejected {path} with '{message}'. This is a gateway level "
                        "rejection on the 'api' platform that happens before the API key is "
                        "looked up: a valid key, an unregistered key and a random string all "
                        "produce this identical response, so it does not indicate a problem with "
                        f"API key '{self._settings['api_key']}'. The 'api' platform requires a "
                        "publisher X-API-Key/X-API-Secret pair that is separate from the app "
                        "key/secret. The same failure affects Stoxkart's own login portal, so "
                        "this needs to be raised with Stoxkart support rather than fixed here."
                    ),
                )

            raise StoxkartAPIException(code=code, message=message)

        return body

    def _request_token_via_rest(self):
        """
        Performs the documented client id / password / TOTP login and returns the
        request token that is exchanged for an access token.
        """
        self._session = requests.Session()

        login = self._auth_post(
            "/auth/login",
            {
                "platform": "api",
                "data": {
                    "client_id": self._settings["ucc_code"],
                    "password": self._settings["api_password"],
                },
            },
        )

        data = login.get("data", {})
        request_token = data.get("request_token")

        if not data.get("is_2fa_enabled") and request_token:
            return request_token

        # The login call only opens the session; the final request token is issued
        # once the second factor has been verified. On the "api" platform the
        # interim token comes back as request_token, the web portal calls the same
        # field token/register_token.
        session_token = request_token or data.get("token") or data.get("register_token")
        if not session_token:
            raise StoxkartAPIException(
                code="500",
                message=f"Stoxkart login response did not contain a session token: {login}",
            )

        verified = self._auth_post(
            "/auth/twofa/verify",
            {
                "platform": "api",
                "data": {
                    "client_id": self._settings["ucc_code"],
                    "req_token": session_token,
                    "action": "api-key-validation",
                    "otp": pyotp.TOTP(self._settings["totp_secret"]).now(),
                },
            },
        )

        request_token = verified.get("data", {}).get("request_token")
        if not request_token:
            raise StoxkartAPIException(
                code="500",
                message=(
                    "Stoxkart verified the TOTP but returned no request_token: "
                    f"{verified}. The API key is most likely not bound to this login."
                ),
            )

        return request_token

    def _request_token_via_browser(self):
        """
        Fallback login that drives the Stoxkart web login portal with Selenium and
        reads the request token off the redirect URL.

        Elements are located by their stable `name` attributes; the portal is a
        React application whose generated element ids change on every deployment,
        so they must not be used as selectors.
        """
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1400,1000')
        driver = Chrome(options=chrome_options)

        try:
            driver.get(f"{LOGIN_PORTAL_URL}?api_key={self._settings['api_key']}")
            self._logger.info(msg="Started the chrome driver")

            wait = WebDriverWait(driver, 20)
            wait.until(lambda d: d.find_elements(By.NAME, "client_id"))

            driver.find_element(By.NAME, "client_id").send_keys(self._settings['ucc_code'])
            driver.find_element(By.NAME, "password").send_keys(self._settings['api_password'])
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

            otp_field = wait.until(self._find_otp_field)
            otp_field.send_keys(pyotp.TOTP(self._settings['totp_secret']).now())

            for button in driver.find_elements(By.TAG_NAME, "button"):
                if button.is_displayed() and button.text.strip().lower() in ("verify", "submit", "continue", "login"):
                    button.click()
                    break

            try:
                wait.until(lambda d: "request_token=" in d.current_url)
            except TimeoutException:
                raise StoxkartAPIException(
                    code="500",
                    message=(
                        "Stoxkart login did not redirect with a request_token. "
                        f"Final URL: {driver.current_url}. Page text: "
                        f"{driver.find_element(By.TAG_NAME, 'body').text[:1000]}"
                    ),
                )

            return parse_qs(urlparse(driver.current_url).query)['request_token'][0]
        finally:
            driver.quit()

    @staticmethod
    def _find_otp_field(driver):
        """
        Returns the OTP input once the second factor dialog is rendered.

        The dialog reuses plain text inputs, so the credential fields are excluded
        by name rather than by position in the DOM.
        """
        for field in driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[type='number']"):
            if field.get_attribute("name") not in ("client_id", "password") and field.is_displayed():
                return field
        return False

    def _exchange_request_token(self, request_token):
        """
        Exchanges a request token for an access token using the HMAC-SHA256
        signature scheme documented by Stoxkart, where the message is the API
        secret and the key is the API key concatenated with the request token.

        - `request_token`: the token obtained from the login flow.
        """
        app_key = self._settings['api_key']
        key = (app_key + request_token).encode('utf-8')

        signature = hmac.new(
            key,
            self._settings['api_secret'].encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        params = {
            "api_key": app_key,
            "signature": signature,
            "req_token": request_token
        }

        data = self.post(
            f"{BASE_URL}/auth/token",
            data=json_lib.dumps(params),
            headers={"Content-Type": "application/json"},
        )

        if 'data' not in data or 'access_token' not in data['data']:
            raise StoxkartAPIException(
                code="500",
                message=f"Cannot get access token from the Stoxkart server. Response: {data}",
            )

        return data['data']['access_token']

    def _persist_access_token(self, access_token):
        """
        Stores the access token in MongoDB and Redis so that later sessions reuse
        it instead of logging in again.

        - `access_token`: the token returned by the token exchange.
        """
        last_login = {
            "broker_name": 'stoxkart',
            "access_token": access_token,
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        }
        self._mongo_db['last_login'].replace_one({'broker_name': 'stoxkart'}, last_login, upsert=True)
        self._cache.hset('last_login', 'stoxkart', json_lib.dumps(last_login))
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
