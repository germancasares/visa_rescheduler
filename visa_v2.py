from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from time import sleep
from configparser import ConfigParser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.support import expected_conditions as EC
from random import randint
from json import loads
from requests import post, get


REGEX_CONTINUE = "//a[contains(text(),'Continue')]"
STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 60*10  # wait time between retries/checks for available dates: 10 minutes
COOLDOWN_TIME = 60*60  # wait time when temporary banned (empty list): 60 minutes

config = ConfigParser()
config.read('config.ini')

COUNTRY_CODE = config['USVISA']['COUNTRY_CODE'] 
USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
FACILITY_ID = config['USVISA']['FACILITY_ID']
MY_SCHEDULE_DATE = config['USVISA']['MY_SCHEDULE_DATE']

PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))


def go_to_login():
    print('Start go_to_login')
    navigate_to(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    sleep(STEP_TIME)

    driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]').click()
    sleep(STEP_TIME)

    driver.find_element(By.XPATH, '//*[@id="header"]/nav/div[1]/div[1]/div[2]/div[1]/ul/li[3]/a').click()
    sleep(STEP_TIME)

    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

    driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]').click()
    sleep(STEP_TIME)

    print("End go_to_login")


def input_credentials():
    print('Start input_credentials')

    driver.find_element(By.ID, 'user_email').send_keys(USERNAME)
    sleep(randint(1, 3))

    driver.find_element(By.ID, 'user_password').send_keys(PASSWORD)
    sleep(randint(1, 3))

    driver.find_element(By.CLASS_NAME, 'icheckbox').click()
    sleep(randint(1, 3))

    driver.find_element(By.NAME, 'commit').click()
    sleep(randint(1, 3))

    print('End input_credentials')


def is_logged_in():
    driver.refresh()
    return driver.current_url != 'https://ais.usvisa-info.com/en-ca/niv/users/sign_in'


def navigate_to(url):
    driver.get(url)
    sleep(STEP_TIME)

    if "502 Bad Gateway" in driver.page_source:
        send_pushover(f"IP Banned, wait for {COOLDOWN_TIME/60} minutes")
        sleep(COOLDOWN_TIME)
        main()


def get_earlier_than_scheduled_dates():
    days = next(
        loads(request.response.body) 
        for request in reversed(driver.requests) 
        if request.url == 'https://ais.usvisa-info.com/en-ca/niv/schedule/51087110/appointment/days/95.json?appointments[expedite]=false' and request.response != None
    )

    global MY_SCHEDULE_DATE
    earlier_days = [entry["date"] for entry in days if entry["date"] < MY_SCHEDULE_DATE]

    return earlier_days


def select_date_in_datepicker(date):
    js_script = f"document.getElementById('appointments_consulate_appointment_date').value = '{date}';"
    driver.execute_script(js_script)

    driver.find_element(By.ID, "appointments_consulate_appointment_date").click()

    driver.find_element(By.CLASS_NAME, "ui-state-active").click()
    sleep(STEP_TIME)


def get_times_for_current_date():
    return next(
        loads(request.response.body) 
        for request in reversed(driver.requests) 
        if request.url == f'https://ais.usvisa-info.com/en-ca/niv/schedule/51087110/appointment/times/95.json?date={date}&appointments[expedite]=false'
    )["available_times"]


def try_to_schedule(date, time):
    data = {
        "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        # "appointments[consulate_appointment][date]": "2023-08-20",
        "appointments[consulate_appointment][time]": time,
    }

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment",
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    request = post(
        f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment", 
        headers=headers, 
        data=data
    )

    return request.text.find('Successfully Scheduled') != -1


def send_pushover(msg):
    print(msg)
    post(
        "https://api.pushover.net/1/messages.json",
        {
            "token": PUSH_TOKEN,
            "user": PUSH_USER,
            "message": msg
        }
    )


max_retries = 5

def main():
    send_pushover("Starting main loop")
    navigate_to(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment")
    sleep(STEP_TIME)
    if not is_logged_in():
        send_pushover("Logging in")
        go_to_login()
        input_credentials()
        send_pushover("Logged in")
        main()

    earlier_than_schedule_dates = get_earlier_than_scheduled_dates()

    for date in earlier_than_schedule_dates:
        select_date_in_datepicker(date)

        times = get_times_for_current_date()

        for time in times:
            send_pushover(f"Trying to schedule for {date} at {time}")
            is_reescheduled = try_to_schedule(date, time)

            if(is_reescheduled):
                send_pushover(f"Rescheduled Successfully! New date on {date} at {time}")
                global MY_SCHEDULE_DATE
                MY_SCHEDULE_DATE = date
                return
            else:
                send_pushover(f"Reschedule failed for {date} at {time}")
    
    global max_retries
    max_retries = max_retries - 1
    send_pushover(f"No earlier dates, waiting for {RETRY_TIME/60} minutes. Max retries available: {max_retries}")
    sleep(RETRY_TIME)
    if max_retries == 0:
        return
    main()
                

main()

send_pushover("Program has finished. Update MY_SCHEDULE_DATE and start again")