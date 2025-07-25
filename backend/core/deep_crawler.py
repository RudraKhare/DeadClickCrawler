import time
import hashlib
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException

class DeepCrawler:
    def __init__(self, driver, logger=None, max_depth=2):
        self.driver = driver
        self.logger = logger or print
        self.max_depth = max_depth
        self.seen_elements = set()
        self.clickables = []
        self.visited_states = set()

    def crawl_page(self, url):
        self.logger(f"Loading URL: {url}")
        self.driver.get(url)
        self.wait_for_frameworks()
        self.recursive_scan(depth=0)
        return self.clickables

    def recursive_scan(self, depth):
        if depth > self.max_depth:
            return
        self.logger(f"Deep scan at depth {depth}")
        self.simulate_scrolls()
        self.simulate_hovers()
        self.simulate_keyboard_navigation()
        self.expand_accordions_and_dropdowns()
        self.scan_shadow_dom()
        self.scan_iframes(depth)
        self.find_pointer_cursor_elements()
        self.find_event_listener_elements()
        self.find_clickable_by_selectors()
        # Optionally, inject MutationObserver and re-scan on DOM changes
        # Optionally, trigger route changes for SPA
        # Optionally, take screenshots for visual debugging

    def simulate_scrolls(self):
        self.logger("Simulating scrolls...")
        height = self.driver.execute_script("return document.body.scrollHeight")
        for y in [0, height//4, height//2, 3*height//4, height-1]:
            self.driver.execute_script(f"window.scrollTo(0, {y});")
            time.sleep(0.5)

    def simulate_hovers(self):
        self.logger("Simulating hovers...")
        hover_selectors = ['.menu-item', '.dropdown', '[aria-haspopup="true"]', '[data-hover]']
        for selector in hover_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        if el.is_displayed():
                            ActionChains(self.driver).move_to_element(el).pause(0.3).perform()
                            self.logger(f"Hovered: {selector}")
                            time.sleep(0.2)
                    except Exception:
                        continue
            except Exception:
                continue

    def simulate_keyboard_navigation(self):
        self.logger("Simulating keyboard navigation...")
        body = self.driver.find_element(By.TAG_NAME, 'body')
        for key in [Keys.TAB, Keys.TAB, Keys.ENTER, Keys.SPACE, Keys.ARROW_DOWN, Keys.ARROW_RIGHT]:
            try:
                body.send_keys(key)
                time.sleep(0.2)
            except Exception:
                continue

    def expand_accordions_and_dropdowns(self):
        self.logger("Expanding accordions and dropdowns...")
        expanders = ['.accordion__toggle', '.dropdown-toggle', '[aria-expanded="false"]', '[data-toggle]']
        for selector in expanders:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        if el.is_displayed() and el.is_enabled():
                            ActionChains(self.driver).move_to_element(el).pause(0.2).click(el).perform()
                            self.logger(f"Expanded: {selector}")
                            time.sleep(0.3)
                    except Exception:
                        continue
            except Exception:
                continue

    def scan_shadow_dom(self):
        self.logger("Scanning shadow DOM...")
        # Recursively scan all shadow roots for clickables
        # (Stub: implement as needed)
        pass

    def scan_iframes(self, depth):
        self.logger("Scanning iframes...")
        iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
        for idx, iframe in enumerate(iframes):
            try:
                self.driver.switch_to.frame(iframe)
                self.logger(f"Switched to iframe {idx+1}/{len(iframes)}")
                self.recursive_scan(depth+1)
                self.driver.switch_to.default_content()
            except Exception as e:
                self.logger(f"Could not scan iframe {idx+1}: {e}")
                self.driver.switch_to.default_content()

    def find_pointer_cursor_elements(self):
        self.logger("Finding pointer cursor elements...")
        try:
            pointer_elements = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('*')).filter(el => {
                    return window.getComputedStyle(el).cursor === 'pointer' &&
                           el.offsetWidth > 0 &&
                           el.offsetHeight > 0;
                });
            """)
            for el in pointer_elements:
                try:
                    if el.is_displayed() and el.is_enabled():
                        self.clickables.append(el)
                except Exception:
                    continue
        except Exception:
            pass

    def find_event_listener_elements(self):
        self.logger("Finding event listener elements...")
        # (Stub: use JS to find elements with click event listeners)
        pass

    def find_clickable_by_selectors(self):
        self.logger("Finding clickables by selectors...")
        selectors = [
            'a', 'button', '[onclick]', '[role="button"]', '[tabindex]',
            'input[type="button"]', 'input[type="submit"]', 'input[type="reset"]',
            '[data-action]', '[data-click]', '[data-href]', '[data-url]'
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        if el.is_displayed() and el.is_enabled():
                            self.clickables.append(el)
                    except Exception:
                        continue
            except Exception:
                continue

    def wait_for_frameworks(self):
        self.logger("Waiting for frameworks to finish rendering...")
        # (Stub: use JS to check for React/Vue/Angular markers, or wait for network idle)
        time.sleep(2) 