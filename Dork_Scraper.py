import re
import random
import time
import urllib.parse
import requests
from colorama import Fore
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, parse_qs

def get_urls_from_dork(query):
    MAX_REQUESTS = 5
    TIME_INTERVAL = 60
    requests_sent = 0
    start_time = time.time()
    delay = random.randint(1, 10)
    user_agent = UserAgent()
    query = urllib.parse.quote(query)
    url = 'https://www.google.com/search?q=' + query + '&num=100'

    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=options)

    wait = WebDriverWait(driver, 30)

    driver.get(url)
    try:
        accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[text()="I agree"]')))
        accept_button.click()
    except:
        pass
    
    time.sleep(3)
    wait.until(EC.presence_of_element_located((By.ID, "search")))
    
    requests_sent += 1
    time.sleep(delay)
    elapsed_time = time.time() - start_time

    if requests_sent >= MAX_REQUESTS and elapsed_time < TIME_INTERVAL:
        time.sleep(TIME_INTERVAL - elapsed_time)
        requests_sent = 0
        start_time = time.time()

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    cites = soup.select('div.apx8Vc cite')
    
    results = []
    for cite in cites:
        try:
            url = cite.get_text()
            if not url.startswith('http'):
                continue
            results.append(url.replace('\xa0', ' '))
        except:
            pass

    driver.quit()
    
    if len(results) == 0:
        print(Fore.RED + "[-] No URLs found for dork: {}".format(query))
    else:
        print(Fore.GREEN + '[+] Found {} URLs.'.format(len(results)))
    
    return results
    
    
banner = ''' 
 ____               ____          _ _____ 
| __ ) _   _  __ _ / ___|___   __| |___ / 
|  _ \| | | |/ _` | |   / _ \ / _` | |_ \ 
| |_) | |_| | (_| | |__| (_) | (_| |___) |
|____/ \__,_|\__, |\____\___/ \__,_|____/ 
             |___/  Dork-Scraper Version: 1.0
'''

print(Fore.RED + banner)

if __name__ == "__main__":
    query = input(Fore.CYAN + "Enter Dork: ")
    print(Fore.GREEN + "[+] Fetching URLs for dork:", query)
    urls = get_urls_from_dork(query)
    print(Fore.GREEN + "[+] Found", len(urls), "URLs.")
    file_path = "URLS.txt"
    try:
        print(Fore.GREEN + "[+] Saving URLs to file:", file_path)
        with open(file_path, "w") as f:
            for url in urls:
                f.write(url + "\n")
        print(Fore.GREEN + "[+] URLs saved successfully.")
    except Exception as e:
        print(Fore.RED + "[-] An error occurred while saving URLs:", e)
