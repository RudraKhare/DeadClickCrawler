# core/click_tester.py
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
    NoSuchElementException
)
from typing import List, Dict, Optional
from utils.element_utils import (
    extract_element_info,
    extract_element_info_for_hidden,
    advanced_deduplication,
    get_status_code,
    get_element_xpath,
    get_element_css_selector,
    create_unique_id,
    is_duplicate_element,
    is_dead_click_by_href
)
import json
import hashlib
from selenium.webdriver.common.action_chains import ActionChains
import tempfile
from .deep_crawler import DeepCrawler

class ClickableElementTester:
    def __init__(self, headless: bool = True, timeout: int = 10, max_workers: int = 3, wait_time: int = 5, strictness: str = 'normal'):
        self.timeout = timeout
        self.max_workers = max_workers
        self.wait_time = wait_time
        self.strictness = strictness
        self.results: List[Dict] = []
        self.driver = self._setup_driver(headless)
        self.url: str = ""
        self.seen_elements = set()
        self.headless = headless
        self.driver_pool = []
        self.logger = logging.getLogger(__name__)

    def _setup_driver(self, headless: bool) -> webdriver.Chrome:
        chrome_options = ChromeOptions()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--window-size=1920,1080")
        # Use a unique user data dir for each driver instance
        chrome_options.add_argument(f"--user-data-dir={tempfile.mkdtemp()}")
        # Set a real user agent
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        try:
            driver = ChromeDriver(options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            self.logger.error(f"Error setting up Chrome driver: {e}")
            raise

    def _setup_driver_pool(self) -> List[webdriver.Chrome]:
        driver_pool = []
        for i in range(self.max_workers):
            try:
                driver = self._setup_driver(self.headless)
                driver_pool.append(driver)
                self.logger.info(f"Driver {i+1} initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize driver {i+1}: {e}")
        return driver_pool

    def _close_driver_pool(self, driver_pool: List[webdriver.Chrome]) -> None:
        for i, driver in enumerate(driver_pool):
            try:
                driver.quit()
                self.logger.info(f"Driver {i+1} closed")
            except Exception as e:
                self.logger.error(f"Error closing driver {i+1}: {e}")

    def _divide_elements_into_batches(self, elements: List[Dict], num_batches: int = 3) -> List[List[Dict]]:
        batch_size = len(elements) // num_batches
        remainder = len(elements) % num_batches
        batches = []
        start_idx = 0
        for i in range(num_batches):
            current_batch_size = batch_size + (1 if i < remainder else 0)
            end_idx = start_idx + current_batch_size
            batch = elements[start_idx:end_idx]
            if batch:
                batches.append(batch)
            start_idx = end_idx
        return batches

    def _test_element_batch(self, batch: List[Dict], driver: webdriver.Chrome, batch_id: int, url: str) -> List[Dict]:
        batch_results = []
        self.logger.info(f"Batch {batch_id} starting - {len(batch)} elements")
        for i, element_info in enumerate(batch, 1):
            try:
                if driver.current_url != url:
                    driver.get(url)
                    time.sleep(2)
                self.logger.info(f"Batch {batch_id} - Testing element {i}/{len(batch)}")
                result = self._test_element_click_with_driver(element_info, driver, url)
                batch_results.append(result)
                if result['click_status'].startswith('active'):
                    self.logger.info(f"ACTIVE: {result['click_status']}")
                elif result['click_status'] == 'dead_click':
                    self.logger.info("DEAD CLICK")
                else:
                    self.logger.warning(f"ERROR: {result['click_status']}")
            except Exception as e:
                self.logger.error(f"Error testing element in batch {batch_id}: {e}")
                error_result = {
                    'element_info': element_info,
                    'click_status': 'batch_error',
                    'error_message': str(e),
                    'page_changed': False,
                    'url_before': url,
                    'url_after': url,
                    'new_elements_appeared': False,
                    'timestamp': datetime.now().isoformat()
                }
                batch_results.append(error_result)
        self.logger.info(f"Batch {batch_id} completed - {len(batch_results)} results")
        return batch_results

    def _test_element_click_with_driver(self, element_info: Dict, driver: webdriver.Chrome, original_url: str) -> Dict:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.action_chains import ActionChains
        import hashlib
        result = {
            'element_info': element_info,
            'click_status': 'unknown',
            'error_message': '',
            'page_changed': False,
            'url_before': '',
            'url_after': '',
            'new_elements_appeared': False,
            'timestamp': datetime.now().isoformat()
        }
        try:
            initial_url = driver.current_url
            initial_title = driver.title
            result['url_before'] = initial_url
            dom_before = driver.execute_script("return document.body.innerHTML;")
            dom_hash_before = hashlib.md5(dom_before.encode('utf-8')).hexdigest()
            # Always re-locate the element just before clicking, with retries
            element = None
            for attempt in range(3):
                element = self._find_element_by_info_with_driver(element_info, driver)
                if element and element.is_displayed() and element.is_enabled():
                    break
                self.logger.info(f"Retry {attempt+1}: Could not locate element, waiting and retrying...")
                time.sleep(0.7)
            if not element:
                result['click_status'] = 'element_not_found'
                result['error_message'] = 'Element could not be located for clicking (after retries)'
                self.logger.warning(f"Element not found after retries: {element_info}")
                return result
            if element_info.get('is_carousel_element', False):
                self._make_carousel_element_clickable_with_driver(element, driver)
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            time.sleep(1)
            if not (element.is_displayed() and element.is_enabled()):
                result['click_status'] = 'not_clickable'
                result['error_message'] = 'Element is not displayed or enabled'
                self.logger.warning(f"Element not clickable: {element_info}")
                return result
            # Robust click simulation: move mouse, click, wait longer
            try:
                ActionChains(driver).move_to_element(element).pause(0.5).click(element).perform()
                self.logger.info(f"Mouse moved and clicked: {element_info}")
            except ElementClickInterceptedException:
                try:
                    driver.execute_script("arguments[0].click();", element)
                    self.logger.info(f"Fallback JS click: {element_info}")
                except Exception as js_error:
                    result['click_status'] = 'click_intercepted'
                    result['error_message'] = f'Click intercepted: {str(js_error)}'
                    self.logger.warning(f"Click intercepted: {element_info}, error: {js_error}")
                    return result
            except Exception as e:
                result['click_status'] = 'error'
                result['error_message'] = f'Error during click: {str(e)}'
                self.logger.error(f"Error during click: {element_info}, error: {e}")
                return result
            # Wait for possible DOM mutation, navigation, or modal
            dom_changed = False
            try:
                WebDriverWait(driver, 6).until(lambda d: hashlib.md5(d.execute_script("return document.body.innerHTML;").encode('utf-8')).hexdigest() != dom_hash_before)
                dom_changed = True
                self.logger.info(f"DOM changed after click: {element_info}")
            except Exception:
                dom_changed = False
                self.logger.info(f"No DOM change after click: {element_info}")
            time.sleep(2)
            current_url = driver.current_url
            current_title = driver.title
            result['url_after'] = current_url
            dom_after = driver.execute_script("return document.body.innerHTML;")
            dom_hash_after = hashlib.md5(dom_after.encode('utf-8')).hexdigest()
            # Loosened dead click logic
            modals = []
            dropdowns = []
            try:
                modals = driver.find_elements(By.CSS_SELECTOR,
                    '.modal, .popup, .overlay, .dialog, [role="dialog"], [role="alertdialog"]')
                dropdowns = driver.find_elements(By.CSS_SELECTOR,
                    '.dropdown-menu, .menu-open, [aria-expanded="true"]')
            except Exception as e:
                self.logger.warning(f"Error checking for modals/dropdowns: {e}")
            is_suspicious = is_dead_click_by_href(element_info)
            if current_url != initial_url:
                result['click_status'] = 'active_navigation'
                result['page_changed'] = True
                self.logger.info(f"Active navigation: {element_info}")
            elif current_title != initial_title:
                result['click_status'] = 'active_title_change'
                result['page_changed'] = True
                self.logger.info(f"Active title change: {element_info}")
            elif dom_changed:
                result['click_status'] = 'active_dom_change'
                self.logger.info(f"Active DOM change: {element_info}")
            elif modals or dropdowns:
                result['click_status'] = 'active_ui_change'
                result['new_elements_appeared'] = True
                self.logger.info(f"Active UI change (modal/dropdown): {element_info}")
            elif is_suspicious:
                result['click_status'] = 'dead_click'
                result['error_message'] = 'Dead click: suspicious href or onclick and no visible effect'
                self.logger.info(f"Dead click (suspicious): {element_info}")
            else:
                result['click_status'] = 'dead_click'
                result['error_message'] = 'Dead click: no visible effect after click'
                self.logger.info(f"Dead click (no effect): {element_info}")
            result['dom_hash_before'] = dom_hash_before
            result['dom_hash_after'] = dom_hash_after
        except Exception as e:
            result['click_status'] = 'error'
            result['error_message'] = str(e)
            self.logger.error(f"Error in click test: {element_info}, error: {e}")
        self.logger.info(f"Click test result: tag={element_info.get('tag_name')}, class={element_info.get('class_names')}, text={element_info.get('text')}, status={result['click_status']}, error={result['error_message']}, dom_changed={result.get('dom_hash_before') != result.get('dom_hash_after')}")
        return result

    def _find_element_by_info_with_driver(self, element_info: Dict, driver: webdriver.Chrome) -> Optional[webdriver.remote.webelement.WebElement]:
        try:
            # 1. Try XPath
            xpath = element_info.get('xpath')
            if xpath and xpath != 'xpath_unavailable':
                try:
                    element = driver.find_element(By.XPATH, xpath)
                    if element.is_displayed():
                        self.logger.info(f"Located element by XPath: {xpath}")
                        return element
                except Exception:
                    self.logger.info(f"Failed to locate by XPath: {xpath}")
            # 2. Try CSS selector
            css_selector = element_info.get('css_selector')
            if css_selector and css_selector != 'css_selector_unavailable':
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, css_selector)
                    for element in elements:
                        if element.is_displayed() and element.tag_name == element_info['tag_name']:
                            self.logger.info(f"Located element by CSS selector: {css_selector}")
                            return element
                except Exception:
                    self.logger.info(f"Failed to locate by CSS selector: {css_selector}")
            # 3. Try by tag, class, and text
            tag_name = element_info['tag_name']
            class_names = element_info['class_names'].strip().replace(' ', '.')
            text = element_info.get('text', '').strip()
            if tag_name and class_names:
                try:
                    selector = f"{tag_name}.{class_names}" if class_names else tag_name
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed() and (not text or el.text.strip() == text):
                            self.logger.info(f"Located element by tag+class+text: {selector}, text={text}")
                            return el
                except Exception:
                    self.logger.info(f"Failed to locate by tag+class+text: {selector}, text={text}")
            # 4. Try by ID
            el_id = element_info.get('id')
            if el_id:
                try:
                    element = driver.find_element(By.ID, el_id)
                    if element.is_displayed():
                        self.logger.info(f"Located element by ID: {el_id}")
                        return element
                except Exception:
                    self.logger.info(f"Failed to locate by ID: {el_id}")
            # 5. Try by partial text (for links/buttons)
            if tag_name and text:
                try:
                    text_xpath = f"//{tag_name}[contains(normalize-space(), \"{text}\")]"
                    elements = driver.find_elements(By.XPATH, text_xpath)
                    for el in elements:
                        if el.is_displayed():
                            self.logger.info(f"Located element by partial text: {text_xpath}")
                            return el
                except Exception:
                    self.logger.info(f"Failed to locate by partial text: {text}")
            # 6. Try by class only
            if class_names:
                try:
                    selector = f".{class_names}"
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            self.logger.info(f"Located element by class only: {selector}")
                            return el
                except Exception:
                    self.logger.info(f"Failed to locate by class only: {selector}")
            # 7. Try by data-testid
            data_testid = element_info.get('data_testid') or ''
            if data_testid:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, f"[data-testid='{data_testid}']")
                    if element.is_displayed():
                        self.logger.info(f"Located element by data-testid: {data_testid}")
                        return element
                except Exception:
                    self.logger.info(f"Failed to locate by data-testid: {data_testid}")
            # 8. Try by aria-label
            aria_label = element_info.get('aria_label') or ''
            if aria_label:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, f"[aria-label='{aria_label}']")
                    if element.is_displayed():
                        self.logger.info(f"Located element by aria-label: {aria_label}")
                        return element
                except Exception:
                    self.logger.info(f"Failed to locate by aria-label: {aria_label}")
            self.logger.warning(f"Could not locate element: {element_info}")
            return None
        except Exception as e:
            self.logger.error(f"Error in robust element location: {e}")
        return None

    def _make_carousel_element_clickable_with_driver(self, element, driver: webdriver.Chrome) -> None:
        try:
            driver.execute_script("""
                var element = arguments[0];
                var current = element;
                while (current && current !== document.body) {
                    current.style.display = 'block';
                    current.style.visibility = 'visible';
                    current.style.opacity = '1';
                    current.style.position = 'relative';
                    current.style.zIndex = 'auto';
                    current.style.transform = current.style.webkitTransform = 'none';
                    current = current.parentElement;
                }
            """, element)
            time.sleep(0.5)
        except Exception as e:
            self.logger.error(f"Error making carousel element clickable: {e}")

    def _handle_carousel_banner(self, element) -> List[Dict]:
        carousel_elements = []
        try:
            carousel_container = self.driver.execute_script("""
                var element = arguments[0];
                var current = element;
                var carouselSelectors = [
                    'carousel', 'slider', 'banner-slider', 'swiper', 'slick',
                    'owl-carousel', 'hero-banner', 'banner-container', 'slideshow'
                ];
                while (current && current !== document.body) {
                    var className = current.className || '';
                    var dataRide = current.getAttribute('data-ride') || '';
                    for (var i = 0; i < carouselSelectors.length; i++) {
                        if (className.includes(carouselSelectors[i]) || dataRide === 'carousel') {
                            return current;
                        }
                    }
                    current = current.parentElement;
                }
                return null;
            """, element)
            if carousel_container:
                self.logger.info("Found carousel container, attempting to pause auto-scroll")
                self._pause_carousel(carousel_container)
                slides = self._get_all_carousel_slides(carousel_container)
                for slide in slides:
                    carousel_elements.extend(self._extract_clickables_from_slide(slide))
        except Exception as e:
            self.logger.error(f"Error handling carousel: {e}")
        return carousel_elements

    def _pause_carousel(self, carousel_container) -> None:
        try:
            self.driver.execute_script("""
                var carousel = arguments[0];
                if (typeof jQuery !== 'undefined' && jQuery(carousel).carousel) {
                    jQuery(carousel).carousel('pause');
                }
                if (carousel.carousel && typeof carousel.carousel === 'function') {
                    carousel.carousel('pause');
                }
                carousel.style.animationPlayState = carousel.style.webkitAnimationPlayState = 'paused';
                var children = carousel.querySelectorAll('*');
                for (var i = 0; i < children.length; i++) {
                    children[i].style.animationPlayState = children[i].style.webkitAnimationPlayState = 'paused';
                }
                if (window.sliderIntervals) window.sliderIntervals.forEach(clearInterval);
                if (carousel.swiper) carousel.swiper.autoplay.stop();
                if (carousel.slick) jQuery(carousel).slick('slickPause');
            """, carousel_container)
            time.sleep(1)
        except Exception as e:
            self.logger.error(f"Could not pause carousel: {e}")

    def _get_all_carousel_slides(self, carousel_container) -> List[webdriver.remote.webelement.WebElement]:
        slide_selectors = [
            '.carousel-item', '.slide', '.slider-item', '.swiper-slide',
            '.slick-slide', '.banner-slide', '.owl-item', '[data-slide]',
            '.glide__slide', '.splide__slide', '.flickity-cell',
            '.keen-slider__slide', '.embla__slide', '.tns-item',
            '.carousel-cell', '.slider-slide', '.slide-item',
            '[class*="slide"]', '[data-slide-index]', '[data-slide-id]'
        ]
        slides = []
        for selector in slide_selectors:
            try:
                found_slides = carousel_container.find_elements(By.CSS_SELECTOR, selector)
                if found_slides:
                    slides.extend(found_slides)
                    break
            except Exception:
                continue
        if not slides:
            try:
                potential_slides = carousel_container.find_elements(By.CSS_SELECTOR, 'div, section, article, li')
                slides = [slide for slide in potential_slides if self._looks_like_slide(slide)]
            except Exception:
                pass
        if not slides:
            try:
                nested_containers = carousel_container.find_elements(By.CSS_SELECTOR,
                    '.swiper-wrapper, .slider-wrapper, .carousel-inner, .slides')
                for container in nested_containers:
                    nested_slides = container.find_elements(By.CSS_SELECTOR, 'div, li')
                    slides.extend(slide for slide in nested_slides if self._looks_like_slide(slide))
            except Exception:
                pass
        self.logger.info(f"Found {len(slides)} carousel slides")
        return slides

    def _looks_like_slide(self, element) -> bool:
        try:
            has_content = (
                len(element.find_elements(By.TAG_NAME, 'img')) > 0 or
                len(element.text.strip()) > 20 or
                len(element.find_elements(By.TAG_NAME, 'a')) > 0 or
                len(element.find_elements(By.TAG_NAME, 'button')) > 0
            )
            if has_content:
                return True
            style = element.get_attribute('style') or ''
            class_names = element.get_attribute('class') or ''
            computed_style = self.driver.execute_script("""
                var style = window.getComputedStyle(arguments[0]);
                return {
                    position: style.position,
                    float: style.float,
                    display: style.display
                };
            """, element)
            has_slide_styling = (
                'width:' in style.lower() or
                computed_style.get('position') in ['absolute', 'relative'] or
                computed_style.get('float') in ['left', 'right'] or
                computed_style.get('display') in ['flex', 'inline-block']
            )
            has_slide_class = any(keyword in class_names.lower() for keyword in
                                ['slide', 'item', 'cell', 'panel', 'tab'])
            return has_slide_styling or has_slide_class
        except Exception:
            return False

    def _extract_clickables_from_slide(self, slide) -> List[Dict]:
        clickables = []
        try:
            self.driver.execute_script("""
                var slide = arguments[0];
                slide.style.display = 'block';
                slide.style.visibility = 'visible';
                slide.style.opacity = '1';
                slide.style.transform = 'translateX(0px)';
                slide.style.position = 'relative';
                slide.style.zIndex = '1000';
            """, slide)
            time.sleep(1)
            clickable_selectors = [
                'a', 'button', '[onclick]', '[role="button"]', 'input[type="button"]',
                'input[type="submit"]', '.btn', '.button', '.link', '.cta', '.call-to-action',
                '[data-action]', '[data-click]', '[data-href]',
                '.carousel-control', '.slider-nav', '.slide-nav',
                '.prev', '.next', '.slide-btn', '.carousel-btn',
                '.thumbnail__overlay'
            ]
            for selector in clickable_selectors:
                try:
                    elements = slide.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_enabled():
                            element_info = self._extract_element_info_for_hidden(element)
                            if element_info:
                                clickables.append(element_info)
                except Exception:
                    continue
            action_words = [
                'WATCH VIDEO', 'PLAY', 'SUBMIT', 'APPLY', 'START', 'LEARN MORE', 'READ MORE',
                'VIEW', 'SEE MORE', 'CLICK HERE', 'DOWNLOAD', 'UPLOAD', 'NEXT', 'PREV', 'PREVIOUS'
            ]
            for word in action_words:
                try:
                    xpath = f".//*[contains(translate(text(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{word}')]"
                    elements = slide.find_elements(By.XPATH, xpath)
                    for element in elements:
                        if element.is_enabled():
                            element_info = self._extract_element_info_for_hidden(element)
                            if element_info:
                                clickables.append(element_info)
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Error extracting clickables from slide: {e}")
        return clickables

    def _extract_element_info_for_hidden(self, element) -> Optional[Dict]:
        try:
            original_style = self.driver.execute_script("""
                var el = arguments[0];
                var style = {
                    display: el.style.display,
                    visibility: el.style.visibility,
                    opacity: el.style.opacity
                };
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.opacity = '1';
                return style;
            """, element)
            href = element.get_attribute('href') or ''
            element_info = {
                'tag_name': element.tag_name,
                'text': element.text.strip()[:100] if element.text else '',
                'class_names': element.get_attribute('class') or '',
                'id': element.get_attribute('id') or '',
                'href': href,
                'status_code': get_status_code(href, self.url),
                'onclick': element.get_attribute('onclick') or '',
                'role': element.get_attribute('role') or '',
                'type': element.get_attribute('type') or '',
                'data_testid': element.get_attribute('data-testid') or '',
                'aria_label': element.get_attribute('aria-label') or '',
                'xpath': get_element_xpath(element, self.driver),
                'size': element.size,
                'is_displayed': True,
                'is_enabled': element.is_enabled(),
                'is_carousel_element': True
            }
            self.driver.execute_script("""
                var el = arguments[0];
                var style = arguments[1];
                el.style.display = style.display;
                el.style.visibility = style.visibility;
                el.style.opacity = style.opacity;
            """, element, original_style)
            element_info['unique_id'] = create_unique_id(element_info)
            return element_info
        except Exception as e:
            self.logger.error(f"Error extracting hidden element info: {e}")
            return None

    def _is_duplicate_element(self, element_info: Dict, existing_elements: List[Dict]) -> bool:
        return is_duplicate_element(element_info, existing_elements)

    def _scroll_to_bottom(self) -> None:
        self.logger.info("Scrolling to the bottom of the page to load all content...")
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while True:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        self.logger.info("Reached the bottom of the page.")
        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

    def find_clickable_elements(self, url: str) -> List[Dict]:
        self.url = url
        self.seen_elements.clear()
        self.logger.info(f"Loading URL: {url}")
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except TimeoutException:
            self.logger.warning("Page load timeout - proceeding with available elements")
        time.sleep(self.wait_time)
        self._scroll_to_bottom()
        # --- Deep scan: simulate user interactions to reveal more clickables ---
        self._deep_scan_interactions(self.driver)
        header_footer_selectors = [
            'header', 'nav', 'footer',
            '.header', '.nav', '.footer', '.navigation',
            '#header', '#nav', '#footer', '#navigation',
            '[role="banner"]', '[role="navigation"]', '[role="contentinfo"]',
            '.site-header', '.site-footer', '.page-header', '.page-footer',
            '.main-header', '.main-footer', '.top-nav', '.bottom-nav',
            '.navbar', '.nav-bar', '.site-nav', '.primary-nav'
        ]
        main_content_area = self._get_main_content_area()
        carousel_elements = self._find_carousel_elements(main_content_area, header_footer_selectors)
        clickable_elements = self._find_regular_clickables(main_content_area, header_footer_selectors)
        clickable_elements.extend(carousel_elements)
        # --- Additive DeepCrawler integration ---
        try:
            deep_crawler = DeepCrawler(self.driver, logger=self.logger.info, max_depth=2)
            deep_clickables = deep_crawler.crawl_page(url)
            # Only add elements not already in clickable_elements (by unique_id if possible)
            existing_ids = {e.get('unique_id') for e in clickable_elements if isinstance(e, dict) and e.get('unique_id')}
            for el in deep_clickables:
                # Try to extract element info if not already a dict
                if not isinstance(el, dict):
                    try:
                        el_info = self._extract_element_info(el)
                    except Exception:
                        continue
                else:
                    el_info = el
                if el_info and el_info.get('unique_id') not in existing_ids:
                    clickable_elements.append(el_info)
                    existing_ids.add(el_info.get('unique_id'))
        except Exception as e:
            self.logger.warning(f"DeepCrawler integration failed: {e}")
        # --- IFRAME SCAN ---
        iframe_clickables = []
        iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
        for idx, iframe in enumerate(iframes):
            try:
                self.logger.info(f"Switching to iframe {idx+1}/{len(iframes)}")
                self.driver.switch_to.frame(iframe)
                # Recursively scan inside iframe
                main_content_area_iframe = self._get_main_content_area()
                iframe_clickables.extend(self._find_regular_clickables(main_content_area_iframe, header_footer_selectors))
                iframe_clickables.extend(self._find_carousel_elements(main_content_area_iframe, header_footer_selectors))
                self.driver.switch_to.default_content()
            except Exception as e:
                self.logger.warning(f"Could not scan iframe {idx+1}: {e}")
                self.driver.switch_to.default_content()
        clickable_elements.extend(iframe_clickables)
        # --- SHADOW DOM SCAN ---
        shadow_clickables = []
        try:
            shadow_hosts = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('*')).filter(el => el.shadowRoot);
            """)
            for idx, host in enumerate(shadow_hosts):
                try:
                    self.logger.info(f"Scanning shadow DOM host {idx+1}/{len(shadow_hosts)}")
                    # Get all elements in shadow root
                    elements = self.driver.execute_script("""
                        let host = arguments[0];
                        let clickables = [];
                        let selectors = [
                            'a', 'button', '[onclick]', '[role="button"]', '[tabindex]',
                            'input[type="button"]', 'input[type="submit"]', 'input[type="reset"]',
                            '[data-action]', '[data-click]', '[data-href]', '[data-url]'
                        ];
                        selectors.forEach(sel => {
                            clickables.push(...host.shadowRoot.querySelectorAll(sel));
                        });
                        return clickables;
                    """, host)
                    for element in elements:
                        try:
                            if element.is_displayed() and element.is_enabled():
                                element_info = self._extract_element_info(element)
                                if element_info:
                                    shadow_clickables.append(element_info)
                        except Exception:
                            continue
                except Exception as e:
                    self.logger.warning(f"Could not scan shadow DOM host {idx+1}: {e}")
        except Exception as e:
            self.logger.warning(f"Error scanning for shadow DOMs: {e}")
        clickable_elements.extend(shadow_clickables)
        self.logger.info(f"Running advanced de-duplication on {len(clickable_elements)} elements...")
        deduplicated_elements = advanced_deduplication(clickable_elements)
        self.logger.info(f"Filtered {len(clickable_elements) - len(deduplicated_elements)} nested duplicate elements.")
        final_elements = []
        unique_ids = set()
        for element_info in deduplicated_elements:
            if element_info and element_info.get('unique_id') and element_info['unique_id'] not in unique_ids:
                unique_ids.add(element_info['unique_id'])
                final_elements.append(element_info)
        self.logger.info(f"Found {len(final_elements)} potentially clickable elements after deduplication.")
        # --- Fallback: If no elements found, scan the whole DOM for all possible clickables ---
        if len(final_elements) == 0:
            self.logger.warning("No clickable elements found with main detection. Running fallback DOM-wide scan.")
            fallback_selectors = [
                'a', 'button', '[onclick]', '[role="button"]', '[tabindex]',
                'input[type="button"]', 'input[type="submit"]', 'input[type="reset"]',
                '[data-action]', '[data-click]', '[data-href]', '[data-url]'
            ]
            fallback_elements = set()
            for selector in fallback_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            fallback_elements.add(element)
                except Exception:
                    continue
            # Add pointer cursor elements
            try:
                pointer_elements = self.driver.execute_script("""
                    return Array.from(document.querySelectorAll('*')).filter(el => {
                        return window.getComputedStyle(el).cursor === 'pointer' &&
                               el.offsetWidth > 0 &&
                               el.offsetHeight > 0;
                    });
                """)
                for element in pointer_elements:
                    if element.is_displayed() and element.is_enabled():
                        fallback_elements.add(element)
            except Exception:
                pass
            # Extract info
            for element in fallback_elements:
                try:
                    element_info = self._extract_element_info(element)
                    if element_info and element_info.get('unique_id') and element_info['unique_id'] not in unique_ids:
                        unique_ids.add(element_info['unique_id'])
                        final_elements.append(element_info)
                except Exception:
                    continue
            self.logger.info(f"Fallback scan found {len(final_elements)} clickable elements.")
        return final_elements

    def _find_carousel_elements(self, main_content_area, header_footer_selectors) -> List[Dict]:
        carousel_elements = []
        carousel_selectors = [
            '.carousel', '.slider', '.banner-slider', '.swiper', '.slick',
            '[data-ride="carousel"]', '.owl-carousel', '.hero-banner',
            '.banner-container', '.slideshow', '.image-slider',
            '.swiper-container', '.swiper-wrapper', '.glide', '.splide',
            '.flickity', '.keen-slider', '.embla', '.tiny-slider',
            '[data-carousel]', '[data-slider]', '[data-swiper]',
            '.slide-container', '.carousel-container', '.slider-wrapper',
            '.hero-slider', '.product-slider', '.testimonial-slider',
            '.gallery-slider', '.content-slider', '.banner-carousel',
            '.thumbnail__overlay'
        ]
        for selector in carousel_selectors:
            try:
                carousels = (main_content_area.find_elements(By.CSS_SELECTOR, selector)
                            if main_content_area
                            else self.driver.find_elements(By.CSS_SELECTOR, selector))
                for carousel in carousels:
                    try:
                        if carousel.is_displayed() and not self._is_in_header_or_footer(carousel, header_footer_selectors):
                            self.logger.info(f"Processing carousel with selector: {selector}")
                            carousel_elements.extend(self._handle_carousel_banner(carousel))
                    except StaleElementReferenceException:
                        continue
                    except Exception as e:
                        self.logger.error(f"Error processing carousel element: {e}")
            except Exception as e:
                self.logger.error(f"Error processing carousel selector '{selector}': {e}")
        return carousel_elements

    def _find_regular_clickables(self, main_content_area, header_footer_selectors) -> List[Dict]:
        clickable_selectors = [
            'a', 'button',
            'input[type="button"]', 'input[type="submit"]', 'input[type="reset"]',
            '[onclick]', '[onmousedown]', '[onmouseup]', '[ondblclick]',
            '.btn', '.button', '.link', '.clickable', '.click', '.calculator-button',
            '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
            '[role="option"]', '[role="treeitem"]', '[role="gridcell"]', '[role="group"]',
            '[tabindex="0"]', '[tabindex="-1"]', 'div[tabindex]', 'span[tabindex]',
            'li[tabindex]', 'td[tabindex]', 'th[tabindex]',
            '.cta', '.call-to-action', '.action', '.trigger',
            '.menu-item', '.nav-item', '.tab', '.accordion__toggle', '.tooltip-xaop--icon',
            '.dropdown', '.select', '.picker', '.toggle',
            '.card', '.tile', '.item', '.option', '.variant-tabs__variant-list__item',
            '.close', '.cancel', '.submit', '.save', '.edit', '.delete',
            '.expand', '.collapse', '.show', '.hide',
            '.play', '.pause', '.stop', '.next', '.prev', '.previous',
            '.like', '.share', '.favorite', '.bookmark',
            '.download', '.upload', '.search', '.filter', '.sort',
            '[data-action]', '[data-click]', '[data-href]', '[data-url]',
            '[data-toggle]', '[data-target]', '[data-dismiss]',
            '[data-testid*="button"]', '[data-testid*="link"]', '[data-testid*="click"]',
            '[data-cy*="button"]', '[data-cy*="link"]', '[data-cy*="click"]',
            'select', 'input[type="checkbox"]', 'input[type="radio"]',
            'input[type="file"]', 'input[type="image"]',
            '[class*="btn"]', '[class*="button"]', '[class*="link"]',
            '[class*="click"]', '[class*="action"]', '[class*="cta"]',
            '[id*="btn"]', '[id*="button"]', '[id*="link"]',
            'video[controls]', 'audio[controls]',
            'li[onclick]', 'td[onclick]', 'tr[onclick]',
            'li[role="button"]', 'td[role="button"]', 'tr[role="button"]',
            'svg[onclick]', 'svg[role="button"]',
            'div[role="button"]', 'span[role="button"]',
            'p[role="button"]', 'section[role="button"]',
            '.thumbnail__overlay'
        ]
        clickable_elements = []
        for selector in clickable_selectors:
            try:
                elements = (main_content_area.find_elements(By.CSS_SELECTOR, selector)
                          if main_content_area
                          else self.driver.find_elements(By.CSS_SELECTOR, selector))
                for element in elements:
                    try:
                        if (element.is_displayed() and element.is_enabled() and
                            not self._is_in_header_or_footer(element, header_footer_selectors) and
                            not self._is_carousel_element(element) and
                            not self._is_in_reviews_carousel(element)):
                            element_info = self._extract_element_info(element)
                            if element_info:
                                clickable_elements.append(element_info)
                    except StaleElementReferenceException:
                        continue
                    except Exception as e:
                        self.logger.error(f"Error processing element: {e}")
            except Exception as e:
                self.logger.error(f"Error finding elements with selector '{selector}': {e}")
        clickable_elements.extend(self._find_elements_by_pointer_cursor(header_footer_selectors))
        clickable_elements.extend(self._find_elements_by_event_listeners(header_footer_selectors))
        return clickable_elements

    def _find_elements_by_pointer_cursor(self, header_footer_selectors) -> List[Dict]:
        elements = []
        try:
            pointer_elements = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('*')).filter(el => {
                    return window.getComputedStyle(el).cursor === 'pointer' &&
                           el.offsetWidth > 0 &&
                           el.offsetHeight > 0;
                });
            """)
            for element in pointer_elements:
                try:
                    if (element.is_displayed() and element.is_enabled() and
                        element.tag_name.lower() != 'img' and
                        not self._is_in_header_or_footer(element, header_footer_selectors) and
                        not self._is_carousel_element(element)):
                        element_info = self._extract_element_info(element)
                        if element_info:
                            element_info['detection_method'] = 'pointer_cursor'
                            elements.append(element_info)
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Error finding pointer cursor elements: {e}")
        return elements

    def _find_elements_by_event_listeners(self, header_footer_selectors) -> List[Dict]:
        elements = []
        try:
            listener_elements = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('*')).filter(el => {
                    return el.onclick ||
                           el.onmousedown ||
                           el.onmouseup ||
                           el.getAttribute('onclick') ||
                           el.hasAttribute('data-action') ||
                           el.hasAttribute('data-click') ||
                           el.hasAttribute('data-href');
                });
            """)
            for element in listener_elements:
                try:
                    if (element.is_displayed() and element.is_enabled() and
                        not self._is_in_header_or_footer(element, header_footer_selectors) and
                        not self._is_carousel_element(element) and
                        not self._is_in_reviews_carousel(element)):
                        element_info = self._extract_element_info(element)
                        if element_info:
                            element_info['detection_method'] = 'event_listener'
                            elements.append(element_info)
                except Exception:
                    continue
        except Exception as e:
            self.logger.error(f"Error finding event listener elements: {e}")
        return elements

    def _get_main_content_area(self) -> Optional[webdriver.remote.webelement.WebElement]:
        main_content_selectors = [
            'main', '[role="main"]', '#main', '#content', '#main-content',
            '.main-content', '.content', '.page-content', '.site-content', '.xaop-main-content',
        ]
        for selector in main_content_selectors:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    self.logger.info(f"Found main content area using selector: {selector}")
                    return element
            except Exception:
                continue
        self.logger.info("No specific main content area found, will use exclusion method")
        return None

    def _is_in_header_or_footer(self, element, header_footer_selectors) -> bool:
        try:
            element_tag = element.tag_name.lower()
            if element_tag in ['header', 'nav', 'footer']:
                return True
            element_class = element.get_attribute('class') or ''
            element_id = element.get_attribute('id') or ''
            element_role = element.get_attribute('role') or ''
            header_footer_keywords = [
                'header', 'nav', 'navigation', 'navbar', 'nav-bar', 'footer',
                'site-header', 'site-footer', 'page-header', 'page-footer',
                'main-header', 'main-footer', 'top-nav', 'bottom-nav',
                'primary-nav', 'secondary-nav', 'breadcrumb'
            ]
            element_attributes = f"{element_class} {element_id}".lower()
            if any(keyword in element_attributes for keyword in header_footer_keywords):
                return True
            if element_role in ['banner', 'navigation', 'contentinfo']:
                return True
            return self.driver.execute_script("""
                var element = arguments[0];
                var current = element;
                var keywords = ['header', 'nav', 'navigation', 'navbar', 'nav-belt',
                               'footer', 'navfooter', 'site-header', 'site-footer',
                               'page-header', 'page-footer', 'main-header', 'main-footer'];
                while (current && current !== document.body) {
                    var tagName = current.tagName ? current.tagName.toLowerCase() : '';
                    var className = current.className || '';
                    var id = current.id || '';
                    var role = current.getAttribute('role') || '';
                    if (['header', 'nav', 'footer'].includes(tagName)) return true;
                    if (['banner', 'navigation', 'contentinfo'].includes(role)) return true;
                    var attributes = (className + ' ' + id).toLowerCase();
                    if (keywords.some(k => attributes.includes(k))) return true;
                    current = current.parentElement;
                }
                return false;
            """, element)
        except Exception as e:
            self.logger.error(f"Error checking if element is in header/footer: {e}")
            return False

    def _is_in_reviews_carousel(self, element) -> bool:
        try:
            return self.driver.execute_script(
                "return arguments[0].closest('.reviews-carousel-banner') !== null;",
                element
            )
        except Exception as e:
            self.logger.error(f"Error checking if element is in reviews carousel: {e}")
            return False

    def _is_carousel_element(self, element) -> bool:
        try:
            return self.driver.execute_script("""
                var element = arguments[0];
                var current = element;
                var carouselSelectors = [
                    'carousel', 'slider', 'banner-slider', 'swiper', 'slick',
                    'owl-carousel', 'hero-banner', 'banner-container', 'slideshow'
                ];
                while (current && current !== document.body) {
                    var className = current.className || '';
                    if (carouselSelectors.some(sel => className.includes(sel))) {
                        return true;
                    }
                    current = current.parentElement;
                }
                return false;
            """, element)
        except Exception:
            return False

    def _extract_element_info(self, element) -> Optional[Dict]:
        return extract_element_info(element, self.driver, self.url, self.seen_elements)

    def _generate_summary(self, test_results: Dict) -> Dict:
        total = test_results['elements_tested']
        return {
            'total_tested': total,
            'active_percentage': round((test_results['active_clicks'] / total) * 100, 2) if total > 0 else 0,
            'dead_percentage': round((test_results['dead_clicks'] / total) * 100, 2) if total > 0 else 0,
            'error_percentage': round((test_results['errors'] / total) * 100, 2) if total > 0 else 0,
            'most_common_classes': self._get_most_common_classes(test_results['results']),
            'click_status_breakdown': self._get_click_status_breakdown(test_results['results'])
        }

    def print_detailed_report(self, test_results: Dict) -> None:
        self.logger.info("\n" + "="*80)
        self.logger.info("DETAILED TEST REPORT")
        self.logger.info("="*80)
        if 'error' in test_results:
            self.logger.error(f"An error occurred: {test_results['error']}")
            return
        self.logger.info(f"\n📊 SUMMARY STATISTICS:")
        self.logger.info(f"   Total Elements Found: {test_results['total_elements_found']}")
        self.logger.info(f"   Elements Tested: {test_results['elements_tested']}")
        self.logger.info(f"   Active Clicks: {test_results['active_clicks']} ({test_results.get('summary', {}).get('active_percentage', 0)}%)")
        self.logger.info(f"   Dead Clicks: {test_results['dead_clicks']} ({test_results.get('summary', {}).get('dead_percentage', 0)}%)")
        self.logger.info(f"   Errors: {test_results['errors']} ({test_results.get('summary', {}).get('error_percentage', 0)}%)")
        self.logger.info(f"\n🏷️  MOST COMMON CLASSES:")
        for class_name, count in test_results.get('summary', {}).get('most_common_classes', [])[:5]:
            self.logger.info(f"   {class_name}: {count}")
        self.logger.info(f"\n📈 CLICK STATUS BREAKDOWN:")
        for status, count in test_results.get('summary', {}).get('click_status_breakdown', {}).items():
            self.logger.info(f"   {status}: {count}")
        self.logger.info(f"\n🔍 DETAILED RESULTS (showing first 10):")
        for i, result in enumerate(test_results.get('results', [])[:10], 1):
            element = result['element_info']
            self.logger.info(f"\n   [{i}] {element['tag_name'].upper()}")
            self.logger.info(f"       Class: {element['class_names'][:80]}")
            self.logger.info(f"       Text: {element['text'][:80]}")
            self.logger.info(f"       Status: {result['click_status']}")
            if result['error_message']:
                self.logger.info(f"       Error: {result['error_message']}")

    def save_results_to_file(self, test_results: Dict, filename: str = None) -> None:
        if not self.url:
            self.url = "unknown_url"
        if not filename:
            safe_url = self.url.replace('https://', '').replace('http://', '').replace('/', '_')
            filename = f"clickability_test_{safe_url}_4.json"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(test_results, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Results saved to: {filename}")
        except Exception as e:
            self.logger.error(f"Error saving results: {e}")

    def run_comprehensive_test_concurrent(self, url: str) -> Dict:
        self.logger.info(f"Starting Concurrent Comprehensive Clickability Test for URL: {url}")
        try:
            clickable_elements = self.find_clickable_elements(url)
            self.logger.info(f"Found {len(clickable_elements)} clickable elements")
            driver_pool = self._setup_driver_pool()
            if not driver_pool:
                raise Exception("Failed to initialize driver pool")
            batches = self._divide_elements_into_batches(clickable_elements, len(driver_pool))
            self.logger.info(f"Elements divided into {len(batches)} batches")
            for i, batch in enumerate(batches):
                self.logger.info(f"  Batch {i+1}: {len(batch)} elements")
            test_results = {
                'url': url,
                'total_elements_found': len(clickable_elements),
                'elements_tested': 0,
                'active_clicks': 0,
                'dead_clicks': 0,
                'errors': 0,
                'results': [],
                'concurrent_info': {
                    'max_workers': self.max_workers,
                    'batches_created': len(batches),
                    'batch_sizes': [len(batch) for batch in batches]
                },
                'summary': {},
                'timestamp': datetime.now().isoformat()
            }
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=len(driver_pool)) as executor:
                future_to_batch = {
                    executor.submit(self._test_element_batch, batch, driver_pool[i], i+1, url): i
                    for i, batch in enumerate(batches)
                }
                for future in as_completed(future_to_batch):
                    batch_id = future_to_batch[future]
                    try:
                        batch_results = future.result()
                        test_results['results'].extend(batch_results)
                        test_results['elements_tested'] += len(batch_results)
                        self.logger.info(f"Batch {batch_id + 1} results collected")
                    except Exception as e:
                        self.logger.error(f"Batch {batch_id + 1} failed: {e}")
            end_time = time.time()
            test_results['concurrent_info']['total_time'] = round(end_time - start_time, 2)
            for result in test_results['results']:
                if result['click_status'].startswith('active'):
                    test_results['active_clicks'] += 1
                elif result['click_status'] == 'dead_click':
                    test_results['dead_clicks'] += 1
                else:
                    test_results['errors'] += 1
            test_results['summary'] = self._generate_summary(test_results)
            self._close_driver_pool(driver_pool)
            self.logger.info(f"Concurrent testing completed in {test_results['concurrent_info']['total_time']} seconds")
            self.logger.info(f"Total elements tested: {test_results['elements_tested']}")
            self.logger.info(f"Active clicks: {test_results['active_clicks']}")
            self.logger.info(f"Dead clicks: {test_results['dead_clicks']}")
            self.logger.info(f"Errors: {test_results['errors']}")
            return test_results
        except Exception as e:
            self.logger.error(f"Error during concurrent comprehensive test: {e}")
            if 'driver_pool' in locals():
                self._close_driver_pool(driver_pool)
            return {'error': str(e)}

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.logger.info("Main browser closed.")

    # --- Carousel, banner, slide, and element finding helpers ---
    # (All methods from your original main.py, updated for Chrome and logging)
    # For brevity, if you want the full code for these helpers, let me know! 

    def _deep_scan_interactions(self, driver):
        import hashlib
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.keys import Keys
        import random
        # Site-specific selectors for bajajfinserv.in and more
        deep_selectors = [
            '.accordion__toggle', '.tab', '.menu-item', '.nav-item', '.expand', '.collapse',
            '[aria-expanded="false"]', '[aria-controls]', '[data-toggle]', '[data-target]',
            '.dropdown-toggle', '.dropdown', '.accordion-trigger', '.show-more', '.see-more',
            '.btn', '.button', '.cta', '.toggle', '.expander', '.panel', '.tab-link',
            '.sidebar-toggle', '.mobile-menu', '.hamburger', '.filter', '.sort', '.step',
            '.faq', '.faq-question', '.faq-toggle', '.read-more', '.read-less',
            '[role="tab"]', '[role="button"]', '[role="menuitem"]', '[role="option"]',
            '[data-menu]', '[data-panel]', '[data-accordion]', '[data-faq]', '[data-expand]',
        ]
        clicked = set()
        dom_hash_before = hashlib.md5(driver.execute_script("return document.body.innerHTML;").encode('utf-8')).hexdigest()
        for selector in deep_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        el_id = el.get_attribute('id') or el.get_attribute('class') or el.get_attribute('data-testid') or el.get_attribute('aria-controls') or el.get_attribute('data-target') or el.text
                        if not el.is_displayed() or not el.is_enabled() or el_id in clicked:
                            continue
                        # Scroll to element
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", el)
                        time.sleep(random.uniform(0.2, 0.5))
                        # Hover over element
                        ActionChains(driver).move_to_element(el).pause(0.2).perform()
                        time.sleep(random.uniform(0.1, 0.3))
                        # Click element
                        ActionChains(driver).move_to_element(el).pause(0.2).click(el).perform()
                        self.logger.info(f"Deep scan: clicked {selector} ({el_id})")
                        clicked.add(el_id)
                        # Wait for DOM change
                        try:
                            WebDriverWait(driver, 3).until(lambda d: hashlib.md5(d.execute_script("return document.body.innerHTML;").encode('utf-8')).hexdigest() != dom_hash_before)
                            dom_hash_before = hashlib.md5(driver.execute_script("return document.body.innerHTML;").encode('utf-8')).hexdigest()
                        except Exception:
                            pass
                        # Optionally, wait a bit for lazy content
                        time.sleep(random.uniform(0.2, 0.6))
                    except Exception as e:
                        self.logger.warning(f"Deep scan: error clicking {selector}: {e}")
            except Exception as e:
                self.logger.warning(f"Deep scan: error finding {selector}: {e}")
        # Simulate keyboard navigation (Tab, Enter, Arrow keys)
        try:
            body = driver.find_element(By.TAG_NAME, 'body')
            for key in [Keys.TAB, Keys.TAB, Keys.ENTER, Keys.SPACE, Keys.ARROW_DOWN, Keys.ARROW_RIGHT]:
                body.send_keys(key)
                time.sleep(random.uniform(0.1, 0.3))
            self.logger.info("Deep scan: simulated keyboard navigation")
        except Exception as e:
            self.logger.warning(f"Deep scan: keyboard navigation error: {e}")
        # Simulate scrolling to various points
        try:
            height = driver.execute_script("return document.body.scrollHeight")
            for y in [0, height//4, height//2, 3*height//4, height-1]:
                driver.execute_script(f"window.scrollTo(0, {y});")
                time.sleep(random.uniform(0.2, 0.5))
            self.logger.info("Deep scan: simulated scrolls")
        except Exception as e:
            self.logger.warning(f"Deep scan: scroll error: {e}")

    def _get_most_common_classes(self, results: List[Dict]) -> List[tuple]:
        class_counts = {}
        for result in results:
            classes = result['element_info']['class_names']
            if classes:
                for class_name in classes.split():
                    class_counts[class_name] = class_counts.get(class_name, 0) + 1
        return sorted(class_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    def _get_click_status_breakdown(self, results: List[Dict]) -> Dict:
        status_counts = {}
        for result in results:
            status = result['click_status']
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts 