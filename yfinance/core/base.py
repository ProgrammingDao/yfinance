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

from __future__ import print_function

from typing import Optional
import time
import datetime
import re
import requests
from copy import deepcopy
import json
import pandas as pd
import numpy as np

try:
    from urllib.parse import quote as urlencode
except ImportError:
    from urllib import quote as urlencode

from yfinance.utils.html import get_html
from yfinance.utils.string import camel2title
from yfinance.core.price_data import empty_price_history
from yfinance.core import price_data, shared
from yfinance.core.isin import is_isin, get_ticker_by_isin
from yfinance.core.parsing import parse_yahoo_html, parse_quotes, parse_actions

_BASE_URL_ = 'https://query2.finance.yahoo.com'
_SCRAPE_URL_ = 'https://finance.yahoo.com/quote'


class TickerBase:
    def __init__(self, ticker, session=None):
        self.ticker = ticker.upper()
        self.session = session
        self._history = None
        self._base_url = _BASE_URL_
        self._scrape_url = _SCRAPE_URL_

        self._fundamentals = False
        self._info = None
        self._analysis = None
        self._sustainability = None
        self._recommendations = None
        self._major_holders = None
        self._institutional_holders = None
        self._mutualfund_holders = None
        self._isin = None
        self._news = []
        self._shares = None

        self._calendar = None
        self._expirations = {}

        empty_df = empty_price_history()
        self._earnings = {
            "yearly": deepcopy(empty_df),
            "quarterly": deepcopy(empty_df)}
        self._financials = {
            "yearly": deepcopy(empty_df),
            "quarterly": deepcopy(empty_df)}
        self._balancesheet = {
            "yearly": deepcopy(empty_df),
            "quarterly": deepcopy(empty_df)}
        self._cashflow = {
            "yearly": deepcopy(empty_df),
            "quarterly": deepcopy(empty_df)}

        # accept isin as ticker
        if is_isin(self.ticker):
            self.ticker = get_ticker_by_isin(self.ticker, None, session)

    def stats(self, proxy=None):
        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}

        if self._fundamentals:
            return

        ticker_url = "{}/{}".format(self._scrape_url, self.ticker)

        # get info and sustainability
        data = parse_yahoo_html(get_html(ticker_url, proxy, self.session).text)
        return data

    def history(self, period="1mo", interval="1d",
                start=None, end=None, prepost=False, actions=True,
                auto_adjust=True, back_adjust=False,
                proxy=None, rounding=False, tz=None, timeout=None, **kwargs):
        """
        :Parameters:
            period : str
                Valid periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
                Either Use period parameter or use start and end
            interval : str
                Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
                Intraday data cannot extend last 60 days
            start: str
                Download start date string (YYYY-MM-DD) or _datetime.
                Default is 1900-01-01
            end: str
                Download end date string (YYYY-MM-DD) or _datetime.
                Default is now
            prepost : bool
                Include Pre and Post market data in results?
                Default is False
            auto_adjust: bool
                Adjust all OHLC automatically? Default is True
            back_adjust: bool
                Back-adjusted data to mimic true historical prices
            proxy: str
                Optional. Proxy server URL scheme. Default is None
            rounding: bool
                Round values to 2 decimal places?
                Optional. Default is False = precision suggested by Yahoo!
            tz: str
                Optional timezone locale for dates.
                (default data is returned as non-localized dates)
            timeout: None or float
                If not None stops waiting for a response after given number of
                seconds. (Can also be a fraction of a second e.g. 0.01)
                Default is None.
            **kwargs: dict
                debug: bool
                    Optional. If passed as False, will suppress
                    error message printing to console.
        """

        if start or period is None or period.lower() == "max":
            if start is None:
                start = -631159200
            elif isinstance(start, datetime.datetime):
                start = int(time.mktime(start.timetuple()))
            else:
                start = int(time.mktime(time.strptime(str(start), '%Y-%m-%d')))
            if end is None:
                end = int(time.time())
            elif isinstance(end, datetime.datetime):
                end = int(time.mktime(end.timetuple()))
            else:
                end = int(time.mktime(time.strptime(str(end), '%Y-%m-%d')))

            params = {"period1": start, "period2": end}
        else:
            period = period.lower()
            params = {"range": period}

        params["interval"] = interval.lower()
        params["includePrePost"] = prepost
        params["events"] = "div,splits"

        # 1) fix weired bug with Yahoo! - returning 60m for 30m bars
        if params["interval"] == "30m":
            params["interval"] = "15m"

        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}

        # Getting data from json
        url = "{}/v8/finance/chart/{}".format(self._base_url, self.ticker)

        data: Optional[dict] = None

        try:
            raw_data: requests.Response = get_html(
                url=url,
                params=params,
                proxy=proxy,
                timeout=timeout
            )
            if "Will be right back" in raw_data.text or raw_data is None:
                raise RuntimeError("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***\n"
                                   "Our engineers are working quickly to resolve "
                                   "the issue. Thank you for your patience.")

            data = raw_data.json()
        except Exception:
            pass

        # Work with errors
        debug_mode = True
        if "debug" in kwargs and isinstance(kwargs["debug"], bool):
            debug_mode = kwargs["debug"]

        err_msg = "No data found for this date range, symbol may be delisted"

        if data is None or not type(data) is dict or 'status_code' in data.keys():
            shared._DFS[self.ticker] = empty_price_history()
            shared._ERRORS[self.ticker] = err_msg
            if "many" not in kwargs and debug_mode:
                print('- %s: %s' % (self.ticker, err_msg))
            return empty_price_history()

        if "chart" in data and data["chart"]["error"]:
            err_msg = data["chart"]["error"]["description"]
            shared._DFS[self.ticker] = empty_price_history()
            shared._ERRORS[self.ticker] = err_msg
            if "many" not in kwargs and debug_mode:
                print('- %s: %s' % (self.ticker, err_msg))
            return shared._DFS[self.ticker]

        elif "chart" not in data or data["chart"]["result"] is None or \
                not data["chart"]["result"]:
            shared._DFS[self.ticker] = empty_price_history()
            shared._ERRORS[self.ticker] = err_msg
            if "many" not in kwargs and debug_mode:
                print('- %s: %s' % (self.ticker, err_msg))
            return shared._DFS[self.ticker]

        # parse quotes
        try:
            quotes = parse_quotes(data["chart"]["result"][0], tz)
        except Exception:
            shared._DFS[self.ticker] = empty_price_history()
            shared._ERRORS[self.ticker] = err_msg
            if "many" not in kwargs and debug_mode:
                print('- %s: %s' % (self.ticker, err_msg))
            return shared._DFS[self.ticker]

        # 2) fix weired bug with Yahoo! - returning 60m for 30m bars
        if interval.lower() == "30m":
            quotes2 = quotes.resample('30T')
            quotes = pd.DataFrame(index=quotes2.last().index, data={
                'Open': quotes2['Open'].first(),
                'High': quotes2['High'].max(),
                'Low': quotes2['Low'].min(),
                'Close': quotes2['Close'].last(),
                'Adj Close': quotes2['Adj Close'].last(),
                'Volume': quotes2['Volume'].sum()
            })
            try:
                quotes['Dividends'] = quotes2['Dividends'].max()
            except Exception:
                pass
            try:
                quotes['Stock Splits'] = quotes2['Dividends'].max()
            except Exception:
                pass

        try:
            if auto_adjust:
                quotes = price_data.auto_adjust(quotes)
            elif back_adjust:
                quotes = price_data.back_adjust(quotes)
        except Exception as e:
            if auto_adjust:
                err_msg = "auto_adjust failed with %s" % e
            else:
                err_msg = "back_adjust failed with %s" % e
            shared._DFS[self.ticker] = empty_price_history()
            shared._ERRORS[self.ticker] = err_msg
            if "many" not in kwargs and debug_mode:
                print('- %s: %s' % (self.ticker, err_msg))

        if rounding:
            quotes = np.round(quotes, data["chart"]["result"][0]["meta"]["priceHint"])
        quotes['Volume'] = quotes['Volume'].fillna(0).astype(np.int64)

        quotes.dropna(inplace=True)

        # actions
        dividends, splits = parse_actions(data["chart"]["result"][0], tz)

        # combine
        df = pd.concat([quotes, dividends, splits], axis=1, sort=True)
        df["Dividends"].fillna(0, inplace=True)
        df["Stock Splits"].fillna(0, inplace=True)

        # index eod/intraday
        df.index = df.index.tz_localize("UTC").tz_convert(
            data["chart"]["result"][0]["meta"]["exchangeTimezoneName"])

        if params["interval"][-1] == "m":
            df.index.name = "Datetime"
        elif params["interval"] == "1h":
            pass
        else:
            df.index = pd.to_datetime(df.index.date)
            if tz is not None:
                df.index = df.index.tz_localize(tz)
            df.index.name = "Date"

        # duplicates and missing rows cleanup
        df.dropna(how='all', inplace=True)
        df = df[~df.index.duplicated(keep='first')]

        self._history = df.copy()

        if not actions:
            df.drop(columns=["Dividends", "Stock Splits"], inplace=True)

        return df

    # ------------------------

    def _get_fundamentals(self, kind=None, proxy=None):
        def cleanup(data):
            df = pd.DataFrame(data).drop(columns=['maxAge'])
            for col in df.columns:
                df[col] = np.where(
                    df[col].astype(str) == '-', np.nan, df[col])

            df.set_index('endDate', inplace=True)
            try:
                df.index = pd.to_datetime(df.index, unit='s')
            except ValueError:
                df.index = pd.to_datetime(df.index)
            df = df.T
            df.columns.name = ''
            df.index.name = 'Breakdown'

            df.index = camel2title(df.index)
            return df

        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}

        if self._fundamentals:
            return

        ticker_url = "{}/{}".format(self._scrape_url, self.ticker)

        # get info and sustainability
        data = parse_yahoo_html(get_html(ticker_url, proxy, self.session).text)

        # holders
        try:
            resp: str = get_html(ticker_url + '/holders', proxy, self.session).text
            holders = pd.read_html(resp)
        except Exception:
            holders = []

        if len(holders) >= 3:
            self._major_holders = holders[0]
            self._institutional_holders = holders[1]
            self._mutualfund_holders = holders[2]
        elif len(holders) >= 2:
            self._major_holders = holders[0]
            self._institutional_holders = holders[1]
        elif len(holders) >= 1:
            self._major_holders = holders[0]

        # self._major_holders = holders[0]
        # self._institutional_holders = holders[1]

        if self._institutional_holders is not None:
            if 'Date Reported' in self._institutional_holders:
                self._institutional_holders['Date Reported'] = pd.to_datetime(
                    self._institutional_holders['Date Reported'])
            if '% Out' in self._institutional_holders:
                self._institutional_holders['% Out'] = self._institutional_holders[
                                                           '% Out'].str.replace('%', '').astype(float) / 100

        if self._mutualfund_holders is not None:
            if 'Date Reported' in self._mutualfund_holders:
                self._mutualfund_holders['Date Reported'] = pd.to_datetime(
                    self._mutualfund_holders['Date Reported'])
            if '% Out' in self._mutualfund_holders:
                self._mutualfund_holders['% Out'] = self._mutualfund_holders[
                                                        '% Out'].str.replace('%', '').astype(float) / 100

        # sustainability
        d = {}
        try:
            if isinstance(data.get('esgScores'), dict):
                for item in data['esgScores']:
                    if not isinstance(data['esgScores'][item], (dict, list)):
                        d[item] = data['esgScores'][item]

                s = pd.DataFrame(index=[0], data=d)[-1:].T
                s.columns = ['Value']
                s.index.name = '%.f-%.f' % (
                    s[s.index == 'ratingYear']['Value'].values[0],
                    s[s.index == 'ratingMonth']['Value'].values[0])

                self._sustainability = s[~s.index.isin(
                    ['maxAge', 'ratingYear', 'ratingMonth'])]
        except Exception:
            pass

        # info (be nice to python 2)
        self._info = {}
        try:
            items = ['summaryProfile', 'financialData', 'quoteType',
                     'defaultKeyStatistics', 'assetProfile', 'summaryDetail']
            for item in items:
                if isinstance(data.get(item), dict):
                    self._info.update(data[item])
        except Exception:
            pass

        # For ETFs, provide this valuable data: the top holdings of the ETF
        try:
            if 'topHoldings' in data:
                self._info.update(data['topHoldings'])
        except Exception:
            pass

        try:
            if not isinstance(data.get('summaryDetail'), dict):
                # For some reason summaryDetail did not give any results. The price dict usually has most of the same info
                self._info.update(data.get('price', {}))
        except Exception:
            pass

        try:
            # self._info['regularMarketPrice'] = self._info['regularMarketOpen']
            self._info['regularMarketPrice'] = data.get('price', {}).get(
                'regularMarketPrice', self._info.get('regularMarketOpen', None))
        except Exception:
            pass

        try:
            self._info['preMarketPrice'] = data.get('price', {}).get(
                'preMarketPrice', self._info.get('preMarketPrice', None))
        except Exception:
            pass

        self._info['logo_url'] = ""
        try:
            domain = self._info['website'].split(
                '://')[1].split('/')[0].replace('www.', '')
            self._info['logo_url'] = 'https://logo.clearbit.com/%s' % domain
        except Exception:
            pass

        # events
        try:
            cal = pd.DataFrame(
                data['calendarEvents']['earnings'])
            cal['earningsDate'] = pd.to_datetime(
                cal['earningsDate'], unit='s')
            self._calendar = cal.T
            self._calendar.index = camel2title(self._calendar.index)
            self._calendar.columns = ['Value']
        except Exception:
            pass

        # analyst recommendations
        try:
            rec = pd.DataFrame(
                data['upgradeDowngradeHistory']['history'])
            rec['earningsDate'] = pd.to_datetime(
                rec['epochGradeDate'], unit='s')
            rec.set_index('earningsDate', inplace=True)
            rec.index.name = 'Date'
            rec.columns = camel2title(rec.columns)
            self._recommendations = rec[[
                'Firm', 'To Grade', 'From Grade', 'Action']].sort_index()
        except Exception:
            pass

        # get fundamentals
        data = parse_yahoo_html(get_html(ticker_url + '/financials', proxy, self.session).text)

        # generic patterns
        for key in (
                (self._cashflow, 'cashflowStatement', 'cashflowStatements'),
                (self._balancesheet, 'balanceSheet', 'balanceSheetStatements'),
                (self._financials, 'incomeStatement', 'incomeStatementHistory')
        ):
            item = key[1] + 'History'
            if isinstance(data.get(item), dict):
                try:
                    key[0]['yearly'] = cleanup(data[item][key[2]])
                except Exception:
                    pass

            item = key[1] + 'HistoryQuarterly'
            if isinstance(data.get(item), dict):
                try:
                    key[0]['quarterly'] = cleanup(data[item][key[2]])
                except Exception:
                    pass

        # earnings
        if isinstance(data.get('earnings'), dict):
            try:
                earnings = data['earnings']['financialsChart']
                earnings['financialCurrency'] = 'USD' if 'financialCurrency' not in data['earnings'] else \
                data['earnings']['financialCurrency']
                self._earnings['financialCurrency'] = earnings['financialCurrency']
                df = pd.DataFrame(earnings['yearly']).set_index('date')
                df.columns = camel2title(df.columns)
                df.index.name = 'Year'
                self._earnings['yearly'] = df

                df = pd.DataFrame(earnings['quarterly']).set_index('date')
                df.columns = camel2title(df.columns)
                df.index.name = 'Quarter'
                self._earnings['quarterly'] = df
            except Exception:
                pass

        # shares outstanding
        try:
            shares = pd.DataFrame(data['annualBasicAverageShares'])
            shares['Year'] = shares['asOfDate'].agg(lambda x: int(x[:4]))
            shares.set_index('Year', inplace=True)
            shares.drop(columns=['dataId', 'asOfDate', 'periodType', 'currencyCode'], inplace=True)
            shares.rename(columns={'reportedValue': "BasicShares"}, inplace=True)
            self._shares = shares
        except Exception:
            pass

        # Analysis
        data = parse_yahoo_html(get_html(ticker_url + '/analysis', proxy, self.session).text)

        if isinstance(data.get('earningsTrend'), dict):
            try:
                analysis = pd.DataFrame(data['earningsTrend']['trend'])
                analysis['endDate'] = pd.to_datetime(analysis['endDate'])
                analysis.set_index('period', inplace=True)
                analysis.index = analysis.index.str.upper()
                analysis.index.name = 'Period'
                analysis.columns = camel2title(analysis.columns)

                dict_cols = []

                for idx, row in analysis.iterrows():
                    for colname, colval in row.items():
                        if isinstance(colval, dict):
                            dict_cols.append(colname)
                            for k, v in colval.items():
                                new_colname = str(colname) + ' ' + camel2title([k])[0]
                                analysis.loc[idx, new_colname] = v

                self._analysis = analysis[[c for c in analysis.columns if c not in dict_cols]]
            except Exception:
                pass

        # Complementary key-statistics (currently fetching the important trailingPegRatio which is the value shown in
        # the website)
        res = {}
        try:
            my_headers = {'user-agent': 'curl/7.55.1', 'accept': 'application/json', 'content-type': 'application/json',
                          'referer': 'https://finance.yahoo.com/', 'cache-control': 'no-cache', 'connection': 'close'}
            p = re.compile(r'root\.App\.main = (.*);')
            r = requests.session().get(
                'https://finance.yahoo.com/quote/{}/key-statistics?p={}'.format(self.ticker, self.ticker),
                headers=my_headers)
            q_results = {}
            my_qs_keys = ['pegRatio']  # QuoteSummaryStore
            my_ts_keys = ['trailingPegRatio']  # , 'quarterlyPegRatio']  # QuoteTimeSeriesStore

            # Complementary key-statistics
            data = json.loads(p.findall(r.text)[0])
            key_stats = data['context']['dispatcher']['stores']['QuoteTimeSeriesStore']
            q_results.setdefault(self.ticker, [])
            for i in my_ts_keys:
                # j=0
                try:
                    # res = {i: key_stats['timeSeries'][i][1]['reportedValue']['raw']}
                    # We need to loop over multiple items, if they exist: 0,1,2,..
                    zzz = key_stats['timeSeries'][i]
                    for j in range(len(zzz)):
                        if key_stats['timeSeries'][i][j]:
                            res = {i: key_stats['timeSeries'][i][j]['reportedValue']['raw']}
                            q_results[self.ticker].append(res)

                # print(res)
                # q_results[ticker].append(res)
                except:
                    q_results[self.ticker].append({i: np.nan})

            res = {'Company': self.ticker}
            q_results[self.ticker].append(res)
        except Exception:
            pass

        if 'trailingPegRatio' in res:
            self._info['trailingPegRatio'] = res['trailingPegRatio']

        self._fundamentals = True

    def get_recommendations(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._recommendations
        if as_dict:
            return data.to_dict()
        return data

    def get_calendar(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._calendar
        if as_dict:
            return data.to_dict()
        return data

    def get_major_holders(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._major_holders
        if as_dict:
            return data.to_dict()
        return data

    def get_institutional_holders(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._institutional_holders
        if data is not None:
            if as_dict:
                return data.to_dict()
            return data

    def get_mutualfund_holders(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._mutualfund_holders
        if data is not None:
            if as_dict:
                return data.to_dict()
            return data

    def get_info(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._info
        if as_dict:
            return data.to_dict()
        return data

    def get_sustainability(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._sustainability
        if as_dict:
            return data.to_dict()
        return data

    def get_earnings(self, proxy=None, as_dict=False, freq="yearly"):
        self._get_fundamentals(proxy=proxy)
        data = self._earnings[freq]
        if as_dict:
            dict_data = data.to_dict()
            dict_data['financialCurrency'] = 'USD' if 'financialCurrency' not in self._earnings else self._earnings[
                'financialCurrency']
            return dict_data
        return data

    def get_analysis(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._analysis
        if as_dict:
            return data.to_dict()
        return data

    def get_financials(self, proxy=None, as_dict=False, freq="yearly"):
        self._get_fundamentals(proxy=proxy)
        data = self._financials[freq]
        if as_dict:
            return data.to_dict()
        return data

    def get_balancesheet(self, proxy=None, as_dict=False, freq="yearly"):
        self._get_fundamentals(proxy=proxy)
        data = self._balancesheet[freq]
        if as_dict:
            return data.to_dict()
        return data

    def get_balance_sheet(self, proxy=None, as_dict=False, freq="yearly"):
        return self.get_balancesheet(proxy, as_dict, freq)

    def get_cashflow(self, proxy=None, as_dict=False, freq="yearly"):
        self._get_fundamentals(proxy=proxy)
        data = self._cashflow[freq]
        if as_dict:
            return data.to_dict()
        return data

    def get_dividends(self, proxy=None):
        if self._history is None:
            self.history(period="max", proxy=proxy)
        if self._history is not None and "Dividends" in self._history:
            dividends = self._history["Dividends"]
            return dividends[dividends != 0]
        return []

    def get_splits(self, proxy=None):
        if self._history is None:
            self.history(period="max", proxy=proxy)
        if self._history is not None and "Stock Splits" in self._history:
            splits = self._history["Stock Splits"]
            return splits[splits != 0]
        return []

    def get_actions(self, proxy=None):
        if self._history is None:
            self.history(period="max", proxy=proxy)
        if self._history is not None and "Dividends" in self._history and "Stock Splits" in self._history:
            actions = self._history[["Dividends", "Stock Splits"]]
            return actions[actions != 0].dropna(how='all').fillna(0)
        return []

    def get_shares(self, proxy=None, as_dict=False, *args, **kwargs):
        self._get_fundamentals(proxy=proxy)
        data = self._shares
        if as_dict:
            return data.to_dict()
        return data

    def get_isin(self, proxy=None):
        # *** experimental ***
        if self._isin is not None:
            return self._isin

        ticker = self.ticker.upper()

        if "-" in ticker or "^" in ticker:
            self._isin = '-'
            return self._isin

        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}

        q = ticker
        self.get_info(proxy=proxy)
        if "shortName" in self._info:
            q = self._info['shortName']

        url = 'https://markets.businessinsider.com/ajax/' \
              'SearchController_Suggest?max_results=25&query=%s' \
              % urlencode(q)
        data = get_html(
            url=url,
            proxy=proxy
        ).text

        search_str = '"{}|'.format(ticker)
        if search_str not in data:
            if q.lower() in data.lower():
                search_str = '"|'
                if search_str not in data:
                    self._isin = '-'
                    return self._isin
            else:
                self._isin = '-'
                return self._isin

        self._isin = data.split(search_str)[1].split('"')[0].split('|')[0]
        return self._isin

    def get_news(self, proxy=None):
        if self._news:
            return self._news

        # setup proxy in requests format
        if proxy is not None:
            if isinstance(proxy, dict) and "https" in proxy:
                proxy = proxy["https"]
            proxy = {"https": proxy}

        # Getting data from json
        url = "{}/v1/finance/search?q={}".format(self._base_url, self.ticker)
        data = get_html(
            url=url,
            proxy=proxy
        )
        if "Will be right back" in data.text:
            raise RuntimeError("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***\n"
                               "Our engineers are working quickly to resolve "
                               "the issue. Thank you for your patience.")
        data = data.json()

        # parse news
        self._news = data.get("news", [])
        return self._news
