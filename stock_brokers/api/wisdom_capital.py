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

# Wisdom Capital's trading host (trade.wisdomcapital.in) serves the certificate of
# its white-label provider (CN=*.ashlarindia.com), so every HTTPS call to it fails
# verification with a hostname mismatch. We deliberately talk to it unverified (see
# WisdomCapitalAPI._VERIFY_SSL), so silence the per-request InsecureRequestWarning
# that urllib3 would otherwise emit on every single call.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class WisdomCapitalAPIException(BrokerAPIException):
    """Raised for Wisdom Capital broker API errors."""

class WisdomCapitalAPI(BrokerAPI):
    """
    Wisdom Capital API class
    """

    # Wisdom Capital logs in through a direct session request (POST
    # appKey+secretKey to /interactive/user/session, no Selenium/PIN flow
    # needed). A Selenium-driven login through the web UI (_connect_legacy)
    # is kept as a fallback - flip this to True to use it if the direct
    # endpoint stops working.
    _USE_LEGACY_LOGIN = False

    # trade.wisdomcapital.in is served off Wisdom Capital's white-label provider and
    # presents that provider's certificate (CN=*.ashlarindia.com), which does not cover
    # the wisdomcapital.in name - so certificate verification fails for every call to
    # it. Wisdom Capital is the only broker in this project with a broken certificate,
    # so verification is disabled for its endpoints only (not globally), and only for
    # the wisdomcapital.in hosts - third-party hosts used during login, such as
    # developers.symphonyfintech.in, present valid certificates and stay verified.
    # Flip this back to True once Wisdom Capital fixes their certificate.
    _VERIFY_SSL = False

    def __init__(self):
        """
        Wisdom Capital API class
        """
        super().__init__(broker_name="wisdom_capital")

        if self._has_valid_session():
            return

        if self._USE_LEGACY_LOGIN:
            return self._connect_legacy()

        response = requests.post(
            'https://trade.wisdomcapital.in/interactive/user/session',
            headers={'Content-Type': 'application/json'},
            json={"appKey": self._settings['api_key'], "secretKey": self._settings['api_secret']},
            verify=self._VERIFY_SSL
        )
        login_data = response.json()
        if "result" not in login_data or "token" not in (login_data.get("result") or {}):
            raise WisdomCapitalAPIException(
                code=response.status_code,
                message=f"Wisdom Capital session login did not return a token: {login_data}",
            )
        token = login_data['result']['token']

        last_login = {
            "broker_name": "wisdom_capital",
            "access_token": token,
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._mongo_db["last_login"].replace_one({"broker_name": "wisdom_capital"}, last_login, upsert=True)
        self._cache.hset("last_login", "wisdom_capital", json_lib.dumps(last_login))
        self._last_login = last_login

    @staticmethod
    def _is_rate_limited(exception):
        """
        True if `exception` is Wisdom Capital's per-endpoint rate-limit rejection
        (HTTP 429 / error code e-apirl-xxxx).
        """
        if getattr(exception, "code", None) == 429:
            return True
        return "e-apirl" in str(getattr(exception, "message", ""))

    def _has_valid_session(self):
        """
        Check whether the stored access token still works, so a usable session is
        not thrown away and replaced on every instantiation.

        The probe is GET /user/balance, the funds endpoint. It is not
        /user/profile, because Wisdom Capital allows only about one profile call a day,
        which is a budget an object that gets constructed several times a day cannot
        live inside. The funds endpoint authenticates identically, so it proves the
        same thing about the token without spending that allowance.

        Wisdom Capital rate limits on a rolling window regardless of endpoint, and a
        429 is NOT a reason to log in again: the rate limiter runs only after the
        request has authenticated - its error names the authenticated user - so a
        throttled probe still proves the token is good. An expired or missing token
        instead comes back as e-token-0002 ("Please Provide token to Authenticate"),
        which does mean a fresh login is needed.
        """
        access_token = (self._last_login or {}).get("access_token")
        # A previously failed login persists the string "None" rather than a token.
        if not access_token or access_token == "None":
            return False

        try:
            self.get(url=f"https://trade.wisdomcapital.in/interactive/user/balance?clientID={self._settings['ucc_code']}")
            return True
        except Exception as exception:
            return self._is_rate_limited(exception)
        
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

        # Callers that do not say anything about certificate verification get the
        # broker-wide default (_VERIFY_SSL), which is off because of Wisdom Capital's
        # mismatched certificate. An explicit verify= from the caller still wins.
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

    def _connect_legacy(self):
        """
        Selenium fallback login (UCC/password/PIN through the web UI, then
        hostlookup + session exchange), used in place of the direct session
        login when that stops working - see _USE_LEGACY_LOGIN.
        """
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        # Same mismatched certificate as above - Chrome would otherwise stop at an
        # interstitial instead of loading the login page.
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
            # 1. Parse the HTML
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            # 2. Locate the <pre> tag and get its text content
            pre_tag = soup.find('pre')
            if not pre_tag:
                raise ValueError("Could not find the <pre> tag in the HTML.")

            json_string = pre_tag.get_text().strip()

            # 3. Parse the outer JSON
            outer_data = json.loads(json_string)

            # 4. Get the serialized session string
            session_str = outer_data.get("session")
            if not session_str:
                raise KeyError("Key 'session' not found in the JSON.")

            # 5. Parse the inner nested JSON
            inner_data = json.loads(session_str)

            # 6. Extract the access token
            access_token = inner_data.get("accessToken")
            if not access_token:
                raise KeyError("Key 'accessToken' not found in the nested session JSON.")

        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            print(f"Error parsing token: {e}")
            access_token = None

        driver.quit()

        if not access_token:
            raise WisdomCapitalAPIException(
                code="500",
                message="Could not extract an access token from the Wisdom Capital login page. The credentials/PIN may have been rejected or the login page changed.",
            )

        response = requests.post('https://developers.symphonyfintech.in/hostlookup', headers={'Content-Type': 'application/json'}, data=json.dumps({"accesspassword": "2021HostLookUpAccess", "version": "interactive_1.0.2"}))
        hostlookup_data = response.json()
        if "result" not in hostlookup_data or "uniqueKey" not in (hostlookup_data.get("result") or {}):
            raise WisdomCapitalAPIException(
                code=response.status_code,
                message=f"Wisdom Capital hostlookup did not return a uniqueKey: {hostlookup_data}",
            )
        unique_key = hostlookup_data['result']['uniqueKey']

        response = requests.post(
            'https://trade.wisdomcapital.in/interactive/user/session',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({"appKey": self._settings['api_key'], "secretKey": self._settings['api_secret'], "uniqueKey": unique_key, "accessToken": access_token}),
            verify=self._VERIFY_SSL
        )
        login_data = response.json()
        if "result" not in login_data or "token" not in (login_data.get("result") or {}):
            raise WisdomCapitalAPIException(
                code=response.status_code,
                message=f"Wisdom Capital session login did not return a token: {login_data}",
            )
        token = login_data['result']['token']

        last_login = {
            "broker_name": "wisdom_capital",
            "access_token": token,
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._mongo_db["last_login"].replace_one({"broker_name": "wisdom_capital"}, last_login, upsert=True)
        self._cache.hset("last_login", "wisdom_capital", json_lib.dumps(last_login))
        return True