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

class ShoonyaAPIException(BrokerAPIException):
    """Raised for Shoonya broker API errors."""

class ShoonyaAPI(BrokerAPI):
    """
    Shoonya API class
    """

    def __init__(self):
        """
        Shoonya API class
        """
        super().__init__(broker_name="shoonya")

        try:
            # Noren refuses a dead session inside an HTTP 200, which the request raises nothing for, so the
            # body is checked too: without it a dead token would never lead to a login.
            details = (self.post(url="https://api.shoonya.com/NorenWClientAPI/UserDetails") or {}).get("data")
            if not isinstance(details, dict) or str(details.get("stat", "")).lower() != "ok":
                raise ShoonyaAPIException(code="Not_Ok", message=f"UserDetails refused the session: {str(details)[:200]}")
        except Exception as e:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            driver = Chrome(options=chrome_options)
            login_url = f'https://trade.shoonya.com/OAuthlogin/investor-entry-level/login?api_key={self._settings["vendor_code"]}&route_to={self._settings["ucc_code"]}'
            driver.get(login_url)

            time.sleep(2)
            self._logger.info(msg="Started the chrome driver")

            # Enter user name and password using selenium webdriver on the loging page
            txt_user_name = driver.find_element(By.XPATH, r'//*[@id="lgnusrid"]')
            txt_password = driver.find_element(By.XPATH, r'//*[@id="lgnpwd"]')
            txt_otp = driver.find_element(By.XPATH, r'//*[@id="lgnotp"]')
            # btn_login = driver.find_element(By.XPATH, r'//*[@id="app"]/div[9]/div/div/div[2]/div/div[2]/form/button')
            btn_login = driver.find_element(By.XPATH, r'//*[@id="mainContent"]/div/div[2]/form/button') # new login button xpath            

            txt_user_name.send_keys(self._settings['ucc_code'])
            txt_password.send_keys(self._settings['password'])
            txt_otp.send_keys(str(pyotp.TOTP(self._settings['totp_secret']).now()))
            btn_login.click()

            try:
                WebDriverWait(driver, 10).until(lambda d: "code=" in d.current_url)
            except TimeoutException:
                current_url = driver.current_url
                page_excerpt = driver.page_source[:2000]
                driver.quit()
                raise ShoonyaAPIException(
                    code="500",
                    message=(
                        "Shoonya login did not redirect with an authorization code within 10s. "
                        f"Final URL: {current_url}. This usually means the credentials/TOTP were "
                        f"rejected or Shoonya changed its login page. Page excerpt: {page_excerpt}"
                    ),
                )

            parsed_url = urlparse(driver.current_url)
            request_token = parse_qs(parsed_url.query)['code'][0]
            print(f"Got request token: {request_token} from Shoonya trading platform.")
            driver.quit()

            h = hashlib.sha256(self._settings['vendor_code'].encode("utf-8") + self._settings['api_secret'].encode("utf-8") + request_token.encode("utf-8"))
            checksum = h.hexdigest()

            data = {
                "code": request_token,
                "checksum": checksum,
                "uid": self._settings['ucc_code']
            }
            # Escaped as a JSON \u0026 rather than left literal: Noren splits this body on the
            # ampersand before it parses the JSON, so a trading symbol containing one - ARE&M,
            # M&M, L&T - ends the jData field early and comes back as "jData is not valid json
            # object". Percent-encoding the field instead is refused: Noren does not decode it.
            data = json_lib.dumps(data).replace("&", "\\u0026")
            data = "jData=" + data

            url = "https://api.shoonya.com/NorenWClientAPI/GenAcsTok"
            data = self.post(url=url, data=data)
            if "data" not in data:
                raise ShoonyaAPIException(code="500", message="Cannot get access token from Shoonya  API server.")
            data = data["data"]

            if "susertoken" not in data:
                raise ShoonyaAPIException(code="500", message="Cannot get access token from Shoonya  API server.")
            
            last_login = {
                "broker_name": "shoonya",
                "access_token": data["susertoken"],
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "shoonya"}, last_login, upsert=True)
            self._cache.hset("last_login", "shoonya", json_lib.dumps(last_login))
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
        
        if data is None:
            data = {
                "uid": self._settings["ucc_code"]
            }
            # Escaped as a JSON \u0026 rather than left literal: Noren splits this body on the
            # ampersand before it parses the JSON, so a trading symbol containing one - ARE&M,
            # M&M, L&T - ends the jData field early and comes back as "jData is not valid json
            # object". Percent-encoding the field instead is refused: Noren does not decode it.
            data = json_lib.dumps(data).replace("&", "\\u0026")
            data = "jData=" + data
            data += f"&jKey={self._last_login['access_token']}"
        elif isinstance(data, dict):
            data["uid"] = self._settings["ucc_code"]
            # Escaped as a JSON \u0026 rather than left literal: Noren splits this body on the
            # ampersand before it parses the JSON, so a trading symbol containing one - ARE&M,
            # M&M, L&T - ends the jData field early and comes back as "jData is not valid json
            # object". Percent-encoding the field instead is refused: Noren does not decode it.
            data = json_lib.dumps(data).replace("&", "\\u0026")
            data = "jData=" + data
            data += f"&jKey={self._last_login['access_token']}"
        
        rest_api_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S:%f')} - requests.request(method='{method}', url='{url}', params={params}, data={data}, headers={headers}, cookies={cookies}, files={files}, auth={auth}, timeout={timeout}, allow_redirects={allow_redirects}, proxies={proxies}, hooks={hooks}, stream={stream}, verify={verify}, cert={cert}, json={json})"
        if verbose == True:
            self._logger.info(rest_api_message)
            self._cache.rpush('broker_api_calls', rest_api_message)
                        
        response = requests.request(method=method, url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        
        if response.status_code < 300:
            content = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "status": "success",
                "code": response.status_code
            }
            
            if "json" in response.headers.get("Content-Type", ""):
                content["data"] = response.json()
            elif "text" in response.headers.get("Content-Type", ""):
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in response.headers.get("Content-Type", ""):
                json_content = response.json()
                if "emsg" in json_content:                    
                    raise ShoonyaAPIException(code=response.status_code, message=json_content["emsg"])
                else:
                    raise ShoonyaAPIException(code=response.status_code, message=json_content)                
            elif "text" in response.headers.get("Content-Type", ""):
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "emsg" in json_content:
                        raise ShoonyaAPIException(code=response.status_code, message=json_content["emsg"])
                    else:
                        raise ShoonyaAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise ShoonyaAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise ShoonyaAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
