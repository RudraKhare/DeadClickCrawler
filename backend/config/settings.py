# config/settings.py
import os

class Config:
    TIMEOUT = int(os.getenv('TIMEOUT', 15))
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 3))
    HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
    DEFAULT_URL = os.getenv('DEFAULT_URL', 'https://cont-sites.bajajfinserv.in/personal-loan') 