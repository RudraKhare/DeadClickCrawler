# models/element.py
from dataclasses import dataclass, field
from typing import Optional, Dict, List

@dataclass
class ElementInfo:
    tag_name: str
    text: str
    class_names: str
    id: str
    status_code: Optional[List[int]] = None
    role: str = ''
    aria_label: str = ''
    alt: str = ''
    xpath: str = ''
    css_selector: str = ''
    is_displayed: bool = True
    is_enabled: bool = True
    unique_id: int = 0
    is_carousel_element: bool = False

@dataclass
class TestResult:
    element_info: ElementInfo
    click_status: str
    error_message: str = ''
    page_changed: bool = False
    url_before: str = ''
    url_after: str = ''
    new_elements_appeared: bool = False
    timestamp: str = '' 