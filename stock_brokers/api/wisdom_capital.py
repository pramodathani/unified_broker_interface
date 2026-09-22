import os
import time
import json
import urllib3
import requests
import json as json_lib
from bs4 import BeautifulSoup
from datetime import datetime
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import *
from selenium.webdriver.common.by import By
from urllib.parse import urlparse, parse_qs

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INTERACTIVE_BALANCE_URL = "https://trade.wisdomcapital.in/interactive/user/balance"
INTERACTIVE_SESSION_URL = "https://trade.wisdomcapital.in/interactive/user/session"
MARKET_DATA_PROBE_URL = "https://trade.wisdomcapital.in/apimarketdata/config/clientConfig"
MARKET_DATA_SESSION_URL = "https://trade.wisdomcapital.in/apimarketdata/auth/login"
HOST_LOOKUP_URL = "https://developers.symphonyfintech.in/hostlookup"

MARKET_DATA_LOCK_KEY = "wisdom_capital:session:marketdata:lock"
MARKET_DATA_LOCK_SECONDS = 120
MARKET_DATA_WAIT_SECONDS = 120

RATE_LIMIT_MARKERS = ("e-apirl",)
SESSION_REFUSED_MARKERS = ("e-session", "e-token", "invalid token", "unauthorized")

class WisdomCapitalAPIException(BrokerAPIException):
    """Raised for Wisdom Capital broker API errors."""

class WisdomCapitalAPI(BrokerAPI):
    """
    Wisdom Capital API class
    """

    _USE_LEGACY_LOGIN = False

    _VERIFY_SSL = False

    def __init__(self):
        """Establishes both of the sessions Wisdom Capital's platform needs, logging in only where the stored token has stopped working.

        Symphony XTS splits a broker into two applications with separate credentials. The interactive application places orders and reports the account, and the market data application serves quotes and charts; each issues its own token and refuses the other's. Constructing this class establishes both, and leaves them in the `last_login` document as `access_token` and `market_data_access_token`.

        Neither token is minted when the stored one still works. The interactive token is checked with `GET /user/balance`, the funds endpoint. It is not `/user/profile`, because Wisdom Capital allows only about one profile call a day, which is a budget an object that is constructed several times a day cannot live inside. The funds endpoint authenticates identically, so it proves the same thing about the token without spending that allowance. The market data token is checked with `GET /apimarketdata/config/clientConfig` in the same spirit.

        Wisdom Capital rate limits on a rolling window regardless of endpoint, and a rate-limit rejection (HTTP 429, or an error code containing `e-apirl`) is not a reason to log in again. The rate limiter runs only after the request has authenticated, and its error names the authenticated user, so a throttled check still proves the token is good. An expired or missing token instead comes back as `e-token-0002` ("Please Provide token to Authenticate"), which does mean a fresh login is needed. A previously failed login stored the string "None" rather than a token, which also means a fresh login.

        A market data login that fails is recorded in `market_data_session_error` rather than raised, because the scripts that poll orders, positions and funds need only the interactive token and must not be stopped by a market data credential they never use. `bin/wisdom_capital/session/connect` reports that error and exits non-zero, so the morning login is still where a broken market data credential is caught.

        Raises:
            WisdomCapitalAPIException: The legacy login found no access token on the login page, the host lookup returned no unique key, or the interactive session request returned no token.
        """
        super().__init__(broker_name="wisdom_capital")

        self.market_data_session_error = None
        self._ensure_trading_session()
        try:
            self._ensure_market_data_session()
        except Exception as exception:
            self.market_data_session_error = exception
            self._logger.warning("Wisdom Capital's market data session could not be established (%s: %s). The interactive session is unaffected.", type(exception).__name__, exception)

    @staticmethod
    def is_rate_limited(exception):
        """Whether Wisdom Capital refused a request for rate rather than for the token it carried.

        Args:
            exception (Exception): Whatever the request raised.

        Returns:
            bool: True when the refusal came from the rate limiter, which runs only after the request has authenticated and so still proves the token is good.
        """
        if getattr(exception, "code", None) in (429, "429"):
            return True
        text = str(exception).lower()
        for marker in RATE_LIMIT_MARKERS:
            if marker in text:
                return True
        return False

    @staticmethod
    def is_session_refused(exception):
        """Whether Wisdom Capital refused a request because the token it carried is expired, unknown or missing.

        Args:
            exception (Exception): Whatever the request raised.

        Returns:
            bool: True when the platform named the session or the token as the problem.
        """
        if getattr(exception, "code", None) in (401, "401"):
            return True
        text = str(exception).lower()
        for marker in SESSION_REFUSED_MARKERS:
            if marker in text:
                return True
        return False

    def market_data_session(self):
        """The market data token and user id in force now, read from the shared login rather than from this object.

        Returns:
            dict: `access_token` (str | None) and `user_id` (str | None), both None when no market data session is stored.
        """
        login = self._current_login() or {}
        return {
            "access_token": login.get("market_data_access_token"),
            "user_id": login.get("market_data_user_id"),
        }

    def replace_market_data_session(self, stale_access_token=None):
        """Establishes a market data session, unless another process has already replaced the one that failed.

        XTS issues exactly one market data session per application key, and a second login invalidates the first token rather than handing out a second. Two processes that each log in therefore take turns invalidating each other's session, so whoever finds the stored token unusable takes a Redis lock, logs in once, and publishes the result for everyone else to read.

        Args:
            stale_access_token (str | None): The market data token that was just refused, so that a token another process has already published in its place is recognised as a replacement rather than as the same failure.

        Returns:
            dict: `access_token` (str) and `user_id` (str | None) of the session now in force.

        Raises:
            WisdomCapitalAPIException: The market data credentials are missing, the login returned no token, or another process held the lock for longer than `MARKET_DATA_WAIT_SECONDS`.
        """
        published = self._published_market_data_session(stale_access_token)
        if published["access_token"]:
            return published

        deadline = time.time() + MARKET_DATA_WAIT_SECONDS
        while not self._cache.set(MARKET_DATA_LOCK_KEY, str(os.getpid()), nx=True, ex=MARKET_DATA_LOCK_SECONDS):
            time.sleep(1)
            published = self._published_market_data_session(stale_access_token)
            if published["access_token"]:
                return published
            if time.time() > deadline:
                raise WisdomCapitalAPIException(
                    code="500",
                    message="Timed out waiting for another process to log in to Wisdom Capital's market data API.",
                )

        try:
            published = self._published_market_data_session(stale_access_token)
            if published["access_token"]:
                return published
            return self._log_in_to_market_data()
        finally:
            self._cache.delete(MARKET_DATA_LOCK_KEY)

    def _ensure_trading_session(self):
        """Makes sure the interactive token in the shared login is one Wisdom Capital still accepts, logging in again when it is not.

        Returns:
            None: The token in force is left in `self._last_login`.

        Raises:
            WisdomCapitalAPIException: The login produced no token.
        """
        stored_token = (self._current_login() or {}).get("access_token")
        if stored_token and stored_token != "None" and self._trading_token_works():
            return
        self._log_in_to_trading()

    def _trading_token_works(self):
        """Asks Wisdom Capital for the account balance to find out whether the stored interactive token is still accepted.

        Returns:
            bool: True when the balance came back, or when the request was refused for rate, which happens only after it has authenticated.
        """
        try:
            self.get(url=f"{INTERACTIVE_BALANCE_URL}?clientID={self._settings['ucc_code']}")
        except Exception as exception:
            return self.is_rate_limited(exception)
        return True

    def _log_in_to_trading(self):
        """Exchanges the interactive credentials for a token and stores it.

        Returns:
            dict: The stored login after the token was written into it.

        Raises:
            WisdomCapitalAPIException: The legacy login found no access token on the login page, the host lookup returned no unique key, or the session request returned no token.
        """
        session_request = {
            "appKey": self._settings['api_key'],
            "secretKey": self._settings['api_secret'],
        }

        if self._USE_LEGACY_LOGIN:
            session_request.update(self._browser_login_fields())

        response = requests.post(
            INTERACTIVE_SESSION_URL,
            headers={'Content-Type': 'application/json'},
            json=session_request,
            verify=self._VERIFY_SSL
        )
        login_data = response.json()
        if "result" not in login_data or "token" not in (login_data.get("result") or {}):
            raise WisdomCapitalAPIException(
                code=response.status_code,
                message=f"Wisdom Capital session login did not return a token: {login_data}",
            )

        self._logger.info("Logged in to Wisdom Capital's interactive API.")
        return self._store_login({
            "access_token": login_data['result']['token'],
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _browser_login_fields(self):
        """Drives Wisdom Capital's web login page with Selenium and returns the extra fields the legacy session request carries.

        Returns:
            dict: `accessToken`, scraped from the page the login lands on, and `uniqueKey`, from Symphony's host lookup.

        Raises:
            WisdomCapitalAPIException: No access token could be extracted from the login page, or the host lookup returned no unique key.
        """
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--ignore-certificate-errors')
        driver = Chrome(options=chrome_options)
        login_url = f'https://trade.wisdomcapital.in/interactive/thirdparty?appKey={self._settings["api_key"]}&returnURL=https://trade.wisdomcapital.in/interactive/testapi#!/logIn'
        driver.get(login_url)
        time.sleep(2)

        user_id = driver.find_element(By.XPATH, '//*[@id="loginPart"]/div/div/div[2]/div[2]/form/div/input')
        user_id.send_keys(self._settings['ucc_code'])
        btn_validate = driver.find_element(By.XPATH, '//*[@id="loginPart"]/div/div/div[2]/div[2]/form/button')
        btn_validate.click()
        time.sleep(2)

        password = driver.find_element(By.XPATH, '//*[@id="login_password_field"]')
        password.send_keys(f'{self._settings["password"]}')
        chk_confirm = driver.find_element(By.XPATH, '//*[@id="confirmimage"]')
        chk_confirm.click()
        btn_submit = driver.find_element(By.XPATH, '//*[@id="loginPart"]/div/div/div/div[2]/form/div[4]/div[2]/button')
        btn_submit.click()
        time.sleep(2)

        pin = driver.find_element(By.XPATH, '//*[@id="efirstPin"]')
        pin.send_keys(f'{self._settings["pin"]}')
        btn_submit = driver.find_element(By.XPATH, '//*[@id="loginPart"]/div/div/div/div[2]/form/div[2]/button')
        btn_submit.click()
        time.sleep(2)

        try:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            pre_tag = soup.find('pre')
            if not pre_tag:
                raise ValueError("Could not find the <pre> tag in the HTML.")
            outer_data = json.loads(pre_tag.get_text().strip())
            session_str = outer_data.get("session")
            if not session_str:
                raise KeyError("Key 'session' not found in the JSON.")
            inner_data = json.loads(session_str)
            access_token = inner_data.get("accessToken")
            if not access_token:
                raise KeyError("Key 'accessToken' not found in the nested session JSON.")
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            self._logger.error("Could not parse the Wisdom Capital login page: %s", error)
            access_token = None

        driver.quit()

        if not access_token:
            raise WisdomCapitalAPIException(
                code="500",
                message="Could not extract an access token from the Wisdom Capital login page. The credentials/PIN may have been rejected or the login page changed.",
            )

        response = requests.post(HOST_LOOKUP_URL, headers={'Content-Type': 'application/json'}, data=json.dumps({"accesspassword": "2021HostLookUpAccess", "version": "interactive_1.0.2"}))
        hostlookup_data = response.json()
        if "result" not in hostlookup_data or "uniqueKey" not in (hostlookup_data.get("result") or {}):
            raise WisdomCapitalAPIException(
                code=response.status_code,
                message=f"Wisdom Capital hostlookup did not return a uniqueKey: {hostlookup_data}",
            )

        return {
            "uniqueKey": hostlookup_data['result']['uniqueKey'],
            "accessToken": access_token,
        }

    def _ensure_market_data_session(self):
        """Makes sure the market data token in the shared login is one Wisdom Capital still accepts, logging in again when it is not.

        Returns:
            None: The token in force is left in `self._last_login`.

        Raises:
            WisdomCapitalAPIException: No market data session could be established.
        """
        stored_token = (self._current_login() or {}).get("market_data_access_token")
        if stored_token and stored_token != "None" and self._market_data_token_works(stored_token):
            return
        self.replace_market_data_session(stale_access_token=stored_token)

    def _market_data_token_works(self, access_token):
        """Asks the market data application for its client configuration to find out whether a token is still accepted.

        A failure that does not name the session is deliberately read as "cannot tell" and the token is kept. Minting a new one invalidates whatever the live quotes feed and the candle downloader are holding, which is too destructive to do on the strength of a timeout or a bad gateway.

        Args:
            access_token (str): The market data token to check.

        Returns:
            bool: True when the token is still accepted, or when the answer said nothing about the session.
        """
        try:
            self.get(url=MARKET_DATA_PROBE_URL, headers=self._market_data_headers(access_token))
        except Exception as exception:
            if self.is_rate_limited(exception):
                return True
            if self.is_session_refused(exception):
                return False
            self._logger.warning("Wisdom Capital's market data check failed for a reason that is not the token (%s: %s). Keeping the stored market data token.", type(exception).__name__, exception)
            return True
        return True

    def _market_data_headers(self, access_token):
        """The headers a market data request carries, which authorize with the market data token rather than the interactive one.

        Args:
            access_token (str): The market data token.

        Returns:
            dict: The headers for a market data request.
        """
        return {
            'Content-Type': 'application/json',
            'authorization': access_token,
        }

    def _published_market_data_session(self, stale_access_token):
        """The market data session another process has published, when it is not the one that has just failed.

        Args:
            stale_access_token (str | None): The market data token that was refused, or None when there was none to refuse.

        Returns:
            dict: `access_token` (str | None) and `user_id` (str | None), with `access_token` None when nothing usable is published.
        """
        login = self._current_login() or {}
        access_token = login.get("market_data_access_token")
        if not access_token or access_token == "None" or access_token == stale_access_token:
            return {
                "access_token": None,
                "user_id": None,
            }
        return {
            "access_token": access_token,
            "user_id": login.get("market_data_user_id"),
        }

    def _log_in_to_market_data(self):
        """Exchanges the market data credentials for a token and stores it.

        Returns:
            dict: `access_token` (str) and `user_id` (str | None) of the session just established.

        Raises:
            WisdomCapitalAPIException: The market data credentials are missing from the broker's settings, or the login returned no token.
        """
        settings = self._settings or {}
        application_key = settings.get("price_api_key")
        application_secret = settings.get("price_api_secret")
        if not application_key or not application_secret:
            raise WisdomCapitalAPIException(
                code="500",
                message="wisdom_capital has no price_api_key or price_api_secret in its settings, so the market data session cannot be established.",
            )

        response = self.post(
            url=MARKET_DATA_SESSION_URL,
            headers={'Content-Type': 'application/json'},
            json={
                "appKey": application_key,
                "secretKey": application_secret,
                "source": "WEBAPI",
            },
        )
        result = (response or {}).get("data") or {}
        if not result.get("token"):
            raise WisdomCapitalAPIException(
                code="500",
                message=f"Wisdom Capital's market data login did not return a token: {str(response)[:200]}",
            )

        self._logger.info("Logged in to Wisdom Capital's market data API.")
        self._store_login({
            "market_data_access_token": result["token"],
            "market_data_user_id": result.get("userID"),
            "market_data_last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        return {
            "access_token": result["token"],
            "user_id": result.get("userID"),
        }

    def _store_login(self, fields):
        """Merges freshly minted session fields into the shared login, MongoDB first and Redis second.

        The two tokens are minted by different paths and at different times, so a login is merged into whatever is stored rather than replacing it. Without that, establishing one session would erase the other's token for every process reading the same document.

        Args:
            fields (dict): The fields to set on the `last_login` document.

        Returns:
            dict: The stored login after the merge, also left in `self._last_login`.
        """
        login = dict(self._current_login() or {})
        login["broker_name"] = "wisdom_capital"
        login.update(fields)

        self._mongo_db["last_login"].replace_one({"broker_name": "wisdom_capital"}, login, upsert=True)
        self._cache.hset("last_login", "wisdom_capital", json_lib.dumps(login))
        self._last_login = login
        return login

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        Private generic REST API request to Broker API server.
        This is specialized into GET, POST, PUT, PATCH and DELETE by public methods.

        - `method`: HTTP method to use for the request.
        - `url
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
                'Content-Type': 'application/json',
                'authorization': self._last_login['access_token']
            }        

        if verify is None:
            verify = self._VERIFY_SSL

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
                if "result" in response.json():
                    content["data"] = response.json()["result"]
                else:
                    content["data"] = response.json()
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "result" in json_content:
                        content["data"] = json_content["result"]
                    else:
                        content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                if "code" in json_content and "description" in json_content:
                    raise WisdomCapitalAPIException(code=json_content["code"], message=json_content["description"])
                elif "errorType" in json_content and "errorMessage" in json_content:
                    raise WisdomCapitalAPIException(code=json_content["errorType"], message=json_content["errorMessage"])
                else:
                    raise WisdomCapitalAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "code" in json_content and "description" in json_content:
                        raise WisdomCapitalAPIException(code=json_content["code"], message=json_content["description"])
                    elif "errorType" in json_content and "errorMessage" in json_content:
                        raise WisdomCapitalAPIException(code=json_content["errorType"], message=json_content["errorMessage"])
                    else:
                        raise WisdomCapitalAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise WisdomCapitalAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise WisdomCapitalAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
