# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Role-owned public web access policy, independent of composition tools."""
import re


def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'enabled', 'allowed_domains'}:
        raise ValueError('網頁搜尋設定不正確')
    enabled = value.get('enabled', False)
    domains = value.get('allowed_domains', [])
    if not isinstance(enabled, bool) or not isinstance(domains, list) or len(domains) > 30:
        raise ValueError('網頁搜尋開關或網域清單不正確')
    normalized = []
    for domain in domains:
        if not isinstance(domain, str):
            raise ValueError('請填寫網域名稱，不含網址或路徑')
        domain = domain.strip().lower()
        if len(domain) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
            raise ValueError('請填寫公開網域名稱，例如 gov.tw，不含網址或路徑')
        if domain not in normalized:
            normalized.append(domain)
    return {'enabled': enabled, 'allowed_domains': normalized}
