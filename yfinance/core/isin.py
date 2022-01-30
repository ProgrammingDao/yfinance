#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# yfinance - market data downloader
# https://github.com/ranaroussi/yfinance
#
# Copyright 2017-2019 Ran Aroussi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from typing import Dict, Any
import re
from requests import Response


from yfinance.utils.html import get_html


def is_isin(string: str) -> bool:
    return bool(re.match("^([A-Z]{2})([A-Z0-9]{9})([0-9]{1})$", string))


def get_all_by_isin(isin: str, proxy=None, session=None) -> Dict[str, Any]:
    if not is_isin(isin):
        raise ValueError("Invalid ISIN number")

    from .base import _BASE_URL_
    url = "{}/v1/finance/search?q={}".format(_BASE_URL_, isin)
    raw_data: Response = get_html(url, proxy, session)
    try:
        data: dict = raw_data.json()
        ticker: dict = data.get('quotes', [{}])[0]
        return {
            'ticker': {
                'symbol': ticker['symbol'],
                'shortname': ticker['shortname'],
                'longname': ticker['longname'],
                'type': ticker['quoteType'],
                'exchange': ticker['exchDisp'],
            },
            'news': data.get('news', [])
        }
    except Exception:
        return {}


def get_ticker_by_isin(isin: str, proxy=None, session=None):
    data = get_all_by_isin(isin, proxy, session)
    return data.get('ticker', {}).get('symbol', '')


def get_info_by_isin(isin: str, proxy=None, session=None):
    data = get_all_by_isin(isin, proxy, session)
    return data.get('ticker', {})


def get_news_by_isin(isin: str, proxy=None, session=None):
    data = get_all_by_isin(isin, proxy, session)
    return data.get('news', {})
