import time
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

class ZerodhaAPIException(BrokerAPIException):
    """Raised for Zerodha broker API errors."""

class ZerodhaAPI(BrokerAPI):
    """
    Zerodha API class
    """

    def __init__(self):
        """
        Zerodha API class
        """
        super().__init__(broker_name="zerodha")

        try:
            self.get(url="https://api.kite.trade/user/profile")
        except Exception as e:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            driver = Chrome(options=chrome_options)
            login_url = f'https://kite.trade/connect/login?api_key={self._settings["api_key"]}&v=3'
            driver.get(login_url)
            
            time.sleep(2)
            self._logger.info(msg="Started the chrome driver")

            # Enter user name and password using selenium webdriver on the loging page
            txt_user_name = driver.find_element(By.XPATH, r'//*[@id="userid"]')
            txt_password = driver.find_element(By.XPATH, r'//*[@id="password"]')
            btn_login = driver.find_element(By.XPATH, r'//*[@id="container"]/div/div/div[2]/form/div[4]/button')

            txt_user_name.send_keys(self._settings['username'])
            txt_password.send_keys(self._settings['password'])
            btn_login.click()

            time.sleep(2)

            # Enter OTP. Entering full OTP implicitly clicks 'Continue' button on the OTP page
            txt_totp = driver.find_element(By.XPATH, r'//*[@id="container"]/div[2]/div/div[2]/form/div[1]/input')
            totp = pyotp.TOTP(self._settings['totp_secret']).now()
            txt_totp.send_keys(str(totp))

            try:
                WebDriverWait(driver, 10).until(lambda d: "request_token=" in d.current_url)
            except TimeoutException:
                current_url = driver.current_url
                page_excerpt = driver.page_source[:2000]
                driver.quit()
                raise ZerodhaAPIException(
                    code="500",
                    message=(
                        "Zerodha login did not redirect with a request_token within 10s. "
                        f"Final URL: {current_url}. This usually means the credentials/TOTP were "
                        f"rejected or Zerodha changed its login page. Page excerpt: {page_excerpt}"
                    ),
                )

            parsed_url = urlparse(driver.current_url)
            request_token = parse_qs(parsed_url.query)['request_token'][0]
            driver.quit()

            h = hashlib.sha256(self._settings['api_key'].encode("utf-8") + request_token.encode("utf-8") + self._settings['api_secret'].encode("utf-8"))
            checksum = h.hexdigest()
            
            url = "https://api.kite.trade/session/token"
            headers = {"X-Kite-Version": "3", "User-Agent": "Kiteconnect-python/4.1.0"}
            data = {
                "api_key": self._settings['api_key'], 
                "request_token": request_token, 
                "checksum": checksum
            }
            
            data = self.post(url=url, data=data, headers=headers)
            if "data" not in data:
                raise ZerodhaAPIException(code="500", message="Cannot get access token from Zerodha KiteConnect server.")
            data = data["data"]
            
            if "access_token" not in data:
                raise ZerodhaAPIException(code="500", message="Cannot get access token from Zerodha KiteConnect server.")
            
            last_login = {
                "broker_name": 'zerodha',
                "access_token": data['access_token'],
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            }
            self._mongo_db['last_login'].replace_one({'broker_name': 'zerodha'}, last_login, upsert=True)
            self._cache.hset('last_login', 'zerodha', json_lib.dumps(last_login))
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
                "X-Kite-Version": "3",
                "User-Agent": "Kiteconnect-python/4.1.0",
                "Authorization": f"token {self._settings['api_key']}:{self._last_login['access_token']}"
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
                json_content = response.json()
                if "data" in json_content:
                    content["data"] = json_content["data"]
                else:
                    content["data"] = json_content
            elif "text" in response.headers["Content-Type"]:
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
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                if "error_type" in json_content and "message" in json_content:
                    raise ZerodhaAPIException(code=json_content["error_type"], message=json_content["message"])
                else:
                    raise ZerodhaAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "error_type" in json_content and "message" in json_content:
                        raise ZerodhaAPIException(code=json_content["error_type"], message=json_content["message"])
                    else:
                        raise ZerodhaAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise ZerodhaAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise ZerodhaAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
