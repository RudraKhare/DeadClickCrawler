# services/test_service.py
import logging
from core.click_tester import ClickableElementTester
from config.settings import Config

class TestService:
    def __init__(self, config=Config):
        self.config = config
        self.tester = None  # Will be initialized per run with params
        self.logger = logging.getLogger(__name__)

    def run_and_report(self, url=None, wait_time=5, strictness='normal'):
        url = url or self.config.DEFAULT_URL
        # Pass wait_time and strictness to tester
        self.tester = ClickableElementTester(self.config.HEADLESS, self.config.TIMEOUT, self.config.MAX_WORKERS, wait_time=wait_time, strictness=strictness)
        results = self.tester.run_comprehensive_test_concurrent(url)
        self.tester.print_detailed_report(results)
        self.tester.save_results_to_file(results)
        return results 