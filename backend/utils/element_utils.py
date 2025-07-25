# utils/element_utils.py
import logging
import hashlib
import requests
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from typing import Dict, List, Optional, Set
from datetime import datetime

def extract_element_info(element, driver, url, seen_elements: Set) -> Optional[Dict]:
    try:
        tag_name = element.tag_name.lower()
        text = element.text.strip()[:100] if element.text else ''
        class_names = element.get_attribute('class') or ''
        href = element.get_attribute('href') or ''
        element_id = element.get_attribute('id') or ''
        role = element.get_attribute('role') or ''
        tabindex = element.get_attribute('tabindex')
        onclick = element.get_attribute('onclick') or ''
        style_cursor = driver.execute_script('return window.getComputedStyle(arguments[0]).cursor;', element)
        data_testid = element.get_attribute('data-testid') or ''
        # Only consider as clickable if truly interactive
        is_clickable = (
            tag_name in ['a', 'button', 'input'] or
            onclick or
            role == 'button' or
            (tabindex is not None and tabindex != '' and tabindex != '-1') or
            style_cursor == 'pointer'
        )
        if not is_clickable:
            return None
        element_info = {
            'tag_name': tag_name,
            'text': text,
            'class_names': class_names,
            'id': element_id,
            'status_code': get_status_code(href, url),
            'role': role,
            'aria_label': element.get_attribute('aria-label') or '',
            'alt': element.get_attribute('alt') or '',
            'xpath': get_element_xpath(element, driver),
            'css_selector': get_element_css_selector(element, driver),
            'is_displayed': element.is_displayed(),
            'is_enabled': element.is_enabled(),
            'data_testid': data_testid,
        }
        element_info['unique_id'] = create_unique_id(element_info)
        if element_info['unique_id'] in seen_elements:
            return None
        seen_elements.add(element_info['unique_id'])
        return element_info
    except Exception as e:
        logging.error(f"Error extracting element info: {e}")
        return None

def extract_element_info_for_hidden(element, driver, url) -> Optional[Dict]:
    try:
        original_style = driver.execute_script("""
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
            'status_code': get_status_code(href, url),
            'onclick': element.get_attribute('onclick') or '',
            'role': element.get_attribute('role') or '',
            'type': element.get_attribute('type') or '',
            'data_testid': element.get_attribute('data-testid') or '',
            'aria_label': element.get_attribute('aria-label') or '',
            'xpath': get_element_xpath(element, driver),
            'size': element.size,
            'is_displayed': True,
            'is_enabled': element.is_enabled(),
            'is_carousel_element': True
        }
        driver.execute_script("""
            var el = arguments[0];
            var style = arguments[1];
            el.style.display = style.display;
            el.style.visibility = style.visibility;
            el.style.opacity = style.opacity;
        """, element, original_style)
        element_info['unique_id'] = create_unique_id(element_info)
        return element_info
    except Exception as e:
        logging.error(f"Error extracting hidden element info: {e}")
        return None

def advanced_deduplication(elements: List[Dict]) -> List[Dict]:
    elements_to_discard = set()
    sorted_elements = sorted(elements, key=lambda x: len(x.get('xpath', '')))
    for i in range(len(sorted_elements)):
        for j in range(i + 1, len(sorted_elements)):
            parent_candidate = sorted_elements[i]
            child_candidate = sorted_elements[j]
            parent_id = parent_candidate.get('unique_id')
            child_id = child_candidate.get('unique_id')
            if parent_id in elements_to_discard or child_id in elements_to_discard:
                continue
            parent_xpath = parent_candidate.get('xpath', '')
            child_xpath = child_candidate.get('xpath', '')
            if not parent_xpath or not child_xpath:
                continue
            parent_classes = parent_candidate.get('class_names', '')
            is_special_container = 'variant-tabs__variant-list__item' in parent_classes
            if is_special_container and child_xpath.startswith(parent_xpath) and child_xpath != parent_xpath:
                elements_to_discard.add(child_id)
                continue
            if child_xpath.startswith(parent_xpath) and child_xpath.count('/') == parent_xpath.count('/') + 1:
                has_same_text = (parent_candidate.get('text') and parent_candidate.get('text') == child_candidate.get('text'))
                has_same_class = (parent_candidate.get('class_names') and parent_candidate.get('class_names') == child_candidate.get('class_names'))
                if has_same_text or has_same_class:
                    elements_to_discard.add(child_id)
    final_list = [elem for elem in elements if elem.get('unique_id') not in elements_to_discard]
    return final_list

def get_status_code(href: str, base_url: str = None) -> Optional[List[int]]:
    if not href or href.startswith(('#', 'javascript:')):
        return None
    try:
        if href.startswith('/') and base_url:
            href = urljoin(base_url, href)
        response = requests.head(href, allow_redirects=True, timeout=5)
        return [r.status_code for r in response.history] + [response.status_code]
    except Exception:
        return None

def get_element_xpath(element, driver) -> str:
    try:
        return driver.execute_script("""
            function getXPath(element) {
                if (element.id !== '') return '//*[@id="' + element.id + '"]';
                if (element === document.body) return '/html/body';
                var ix = 0;
                var siblings = element.parentNode.childNodes;
                for (var i = 0; i < siblings.length; i++) {
                    var sibling = siblings[i];
                    if (sibling === element) return getXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                    if (sibling.nodeType === 1 && sibling.tagName === element.tagName) ix++;
                }
            }
            return getXPath(arguments[0]);
        """, element)
    except Exception:
        return "xpath_unavailable"

def get_element_css_selector(element, driver) -> str:
    try:
        return driver.execute_script("""
            function getCssSelector(el) {
                if (!(el instanceof Element)) return '';
                var path = [];
                while (el.nodeType === Node.ELEMENT_NODE) {
                    var selector = el.nodeName.toLowerCase();
                    if (el.id) {
                        selector += '#' + el.id;
                        path.unshift(selector);
                        break;
                    } else {
                        var sib = el, nth = 1;
                        while (sib = sib.previousElementSibling) {
                            if (sib.nodeName.toLowerCase() == selector)
                                nth++;
                        }
                        if (nth != 1)
                            selector += ":nth-of-type(" + nth + ")";
                    }
                    path.unshift(selector);
                    el = el.parentNode;
                }
                return path.join(" > ");
            }
            return getCssSelector(arguments[0]);
        """, element)
    except Exception:
        return "css_selector_unavailable"

def create_unique_id(element_info: Dict) -> int:
    components = [
        element_info.get('tag_name', ''),
        element_info.get('id', ''),
        element_info.get('class_names', ''),
        element_info.get('text', '')[:50],
    ]
    return hash('|'.join(str(c) for c in components))

def is_duplicate_element(element_info: Dict, existing_elements: List[Dict]) -> bool:
    for existing in existing_elements:
        if (
            existing['xpath'] == element_info['xpath'] or
            (existing['unique_id'] == element_info['unique_id'] and
             existing['tag_name'] == element_info['tag_name'] and
             existing['text'] == element_info['text'])
        ):
            return True
    return False

def is_dead_click_by_href(element_info: Dict) -> bool:
    href = (element_info.get('href') or '').replace(' ', '').lower()
    onclick = (element_info.get('onclick') or '').replace(' ', '').lower()
    dead_patterns = [
        '', '#', 'javascript:void(0)', 'javascript:void(0);', 'javascript:',
        'javascript::void(0)', 'void(0)', 'undefined', 'null', 'about:blank',
    ]
    if href in dead_patterns:
        return True
    if href.startswith('javascript:') or href.startswith('void(0)'):
        return True
    if onclick in ['void(0)', 'javascript:void(0)', '']:
        return True
    if onclick.startswith('javascript:'):
        return True
    return False 