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

import re
import json
import pandas as pd


def parse_yahoo_html(yahoo_html: str) -> dict:
    """
    Parse html result produced by querying https://finance.yahoo.com/quote.

    :param yahoo_html: string for the html query of yahoo finance.
    :return: parsed yahoo query.
    """
    json_str: str = yahoo_html.split('root.App.main =')[1].split('(this)')[0].split(';\n}')[0].strip()
    yahoo_stores: dict = json.loads(json_str)['context']['dispatcher']['stores']
    data: dict = yahoo_stores['QuoteSummaryStore']
    # add data about Shares Outstanding for companies' tickers if they are available
    try:
        data['annualBasicAverageShares'] = \
            yahoo_stores['QuoteTimeSeriesStore']['timeSeries']['annualBasicAverageShares']
    except Exception:
        pass

    # return data
    new_data: str = json.dumps(data).replace('{}', 'null')
    new_data = re.sub(
        r'{[\'|\"]raw[\'|\"]:(.*?),(.*?)}', r'\1', new_data)

    return json.loads(new_data)


def parse_quotes(data: dict, tz=None) -> pd.DataFrame:
    timestamps = data["timestamp"]
    ohlc = data["indicators"]["quote"][0]
    volumes = ohlc["volume"]
    opens = ohlc["open"]
    closes = ohlc["close"]
    lows = ohlc["low"]
    highs = ohlc["high"]

    adjclose = closes
    if "adjclose" in data["indicators"]:
        adjclose = data["indicators"]["adjclose"][0]["adjclose"]

    quotes = pd.DataFrame({"Open": opens,
                            "High": highs,
                            "Low": lows,
                            "Close": closes,
                            "Adj Close": adjclose,
                            "Volume": volumes})

    quotes.index = pd.to_datetime(timestamps, unit="s")
    quotes.sort_index(inplace=True)

    if tz is not None:
        quotes.index = quotes.index.tz_localize(tz)

    return quotes


def parse_actions(data, tz=None):
    dividends = pd.DataFrame(columns=["Dividends"], index=pd.DatetimeIndex([]))
    splits = pd.DataFrame(columns=["Stock Splits"], index=pd.DatetimeIndex([]))

    if "events" in data:
        if "dividends" in data["events"]:
            dividends = pd.DataFrame(
                data=list(data["events"]["dividends"].values()))
            dividends.set_index("date", inplace=True)
            dividends.index = pd.to_datetime(dividends.index, unit="s")
            dividends.sort_index(inplace=True)
            if tz is not None:
                dividends.index = dividends.index.tz_localize(tz)

            dividends.columns = ["Dividends"]

        if "splits" in data["events"]:
            splits = pd.DataFrame(
                data=list(data["events"]["splits"].values()))
            splits.set_index("date", inplace=True)
            splits.index = pd.to_datetime(splits.index, unit="s")
            splits.sort_index(inplace=True)
            if tz is not None:
                splits.index = splits.index.tz_localize(tz)
            splits["Stock Splits"] = splits["numerator"] / \
                splits["denominator"]
            splits = splits["Stock Splits"]

    return dividends, splits
