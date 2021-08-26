# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.


from builtins import ValueError, isinstance
from functools import lru_cache
import logging
from typing import List, Text, Union, Callable, Iterable, Dict
from collections import OrderedDict

import inspect
import bisect
import pandas as pd
import numpy as np

from ..utils.index_data import IndexData
from ..utils.resam import resam_ts_data, ts_data_last
from ..log import get_module_logger
from ..utils.time import if_single_data


class BaseQuote:
    def __init__(self, quote_df: pd.DataFrame):
        self.logger = get_module_logger("online operator", level=logging.INFO)

    def get_all_stock(self) -> Iterable:
        """return all stock codes

        Return
        ------
        Iterable
            all stock codes
        """

        raise NotImplementedError(f"Please implement the `get_all_stock` method")

    def get_data(
        self,
        stock_id: str,
        start_time: Union[pd.Timestamp, str],
        end_time: Union[pd.Timestamp, str],
        fields: Union[str, None] = None,
        method: Union[str, Callable, None] = None,
    ) -> Union[None, Union[int, float, bool], "IndexData"]:
        """get the specific fields of stock data during start time and end_time,
           and apply method to the data.

           Example:
            .. code-block::
                                        $close      $volume
                instrument  datetime
                SH600000    2010-01-04  86.778313   16162960.0
                            2010-01-05  87.433578   28117442.0
                            2010-01-06  85.713585   23632884.0
                            2010-01-07  83.788803   20813402.0
                            2010-01-08  84.730675   16044853.0

                SH600655    2010-01-04  2699.567383  158193.328125
                            2010-01-08  2612.359619   77501.406250
                            2010-01-11  2712.982422  160852.390625
                            2010-01-12  2788.688232  164587.937500
                            2010-01-13  2790.604004  145460.453125

                this function is used for three case:

                1. Both fields and method are not None. It returns int/float/bool.
                    print(get_data(stock_id="SH600000", start_time="2010-01-04", end_time="2010-01-06", fields="$close", method="last"))

                    85.713585

                2. Both fields and method are None. It returns np.ndarray.
                    print(get_data(stock_id="SH600000", start_time="2010-01-04", end_time="2010-01-06", fields=None, method=None))

                    [
                        [86.778313, 16162960.0],
                        [87.433578, 28117442.0],
                        [85.713585, 23632884.0],
                    ]

                3. fields is not None, and method is None. It returns IndexData.
                    print(get_data(stock_id="SH600000", start_time="2010-01-04", end_time="2010-01-06", fields="$close", method=None))

                    IndexData([86.778313, 87.433578, 85.713585], [2010-01-04, 2010-01-05, 2010-01-06])

        Parameters
        ----------
        stock_id: str
        start_time : Union[pd.Timestamp, str]
            closed start time for backtest
        end_time : Union[pd.Timestamp, str]
            closed end time for backtest
        fields : Union[str, None]
            the columns of data to fetch
        method : Union[str, Callable, None]
            the method apply to data.
            e.g [None, "last", "all", "sum", "mean", qlib/utils/resam.py/ts_data_last]

        Return
        ----------
        Union[None, Union[int, float, bool], IndexData]
            please refer to Example as following.
        """

        raise NotImplementedError(f"Please implement the `get_data` method")


class PandasQuote(BaseQuote):
    def __init__(self, quote_df: pd.DataFrame):
        super().__init__(quote_df=quote_df)
        quote_dict = {}
        for stock_id, stock_val in quote_df.groupby(level="instrument"):
            quote_dict[stock_id] = stock_val.droplevel(level="instrument")
        self.data = quote_dict

    def get_all_stock(self):
        return self.data.keys()

    def get_data(self, stock_id, start_time, end_time, fields=None, method=None):
        if fields is None and method is not None:
            raise ValueError(f"method must be None when fields is None")

        if fields is None:
            stock_data = resam_ts_data(self.data[stock_id], start_time, end_time, method=method)
        elif isinstance(fields, str):
            stock_data = resam_ts_data(self.data[stock_id][fields], start_time, end_time, method=method)
        else:
            raise ValueError(f"fields must be None, str")

        if stock_data is None:
            return None
        elif isinstance(stock_data, (bool, np.bool_, int, float, np.signedinteger, np.floating)):
            return stock_data
        elif isinstance(stock_data, pd.Series):
            return IndexData.Series(stock_data)
        elif isinstance(stock_data, pd.DataFrame):
            return stock_data.values
        else:
            raise ValueError(f"stock data from resam_ts_data must be a number, pd.Series or pd.DataFrame")


class CN1min_NumpyQuote(BaseQuote):
    def __init__(self, quote_df: pd.DataFrame):
        """CN1min_NumpyQuote

        Parameters
        ----------
        quote_df : pd.DataFrame
            the init dataframe from qlib.
        self.data : Dict(stock_id, IndexData.DataFrame)
        """
        super().__init__(quote_df=quote_df)
        quote_dict = {}
        for stock_id, stock_val in quote_df.groupby(level="instrument"):
            quote_dict[stock_id] = IndexData.DataFrame(stock_val.droplevel(level="instrument"))
        self.data = quote_dict
        self.freq = np.timedelta64(1, "m")

    def get_all_stock(self):
        return self.data.keys()

    def get_data(self, stock_id, start_time, end_time, fields=None, method=None):
        if fields is None and method is not None:
            raise ValueError(f"method must be None when fields is None")

        # check stock id
        if stock_id not in self.get_all_stock():
            return None

        # single data
        # If it don't consider the classification of single data, it will consume a lot of time.
        if if_single_data(start_time, end_time, self.freq):
            now_index_map = self.data[stock_id].index_map
            now_columns_map = self.data[stock_id].columns_map
            if start_time not in now_index_map:
                return None
            if fields is None:
                return self.data[stock_id].values[now_index_map[start_time]]
            else:
                return self.data[stock_id].values[now_index_map[start_time], now_columns_map[fields]]

        # multi data
        else:
            if fields is None and method is None:
                stock_data = self.data[stock_id].loc(start_time, end_time)
                if stock_data.empty:
                    return None
                else:
                    return stock_data.values
            elif fields is not None and method is None:
                stock_data = self.data[stock_id].loc(start_time, end_time, fields)
                if stock_data.empty:
                    return None
                else:
                    return stock_data
            elif fields is not None and method is not None:
                stock_data = self.data[stock_id].loc(start_time, end_time, fields)
                if stock_data.empty:
                    return None
                elif len(stock_data) == 1:
                    return stock_data[0]
                else:
                    return self._agg_data(stock_data.values, method)

    def _agg_data(self, data, method):
        """Agg data by specific method."""
        if method == "sum":
            return np.nansum(data)
        elif method == "mean":
            return np.nanmean(data)
        elif method == "last":
            return data[-1]
        elif method == "all":
            return data.all()
        elif method == "any":
            return data.any()
        elif method == ts_data_last:
            valid_data = data[data != np.NaN]
            if len(valid_data) == 0:
                return None
            else:
                return valid_data[0]
        else:
            raise ValueError(f"{method} is not supported")


class BaseSingleMetric:
    """
    The data structure of the single metric.
    The following methods are used for computing metrics in one indicator.
    """

    def __init__(self, metric: Union[dict, pd.Series]):
        raise NotImplementedError(f"Please implement the `__init__` method")

    def __add__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__add__` method")

    def __radd__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        return self + other

    def __sub__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__sub__` method")

    def __rsub__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__rsub__` method")

    def __mul__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__mul__` method")

    def __truediv__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__truediv__` method")

    def __eq__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__eq__` method")

    def __gt__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__gt__` method")

    def __lt__(self, other: Union["BaseSingleMetric", int, float]) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `__lt__` method")

    def __len__(self) -> int:
        raise NotImplementedError(f"Please implement the `__len__` method")

    def sum(self) -> float:
        raise NotImplementedError(f"Please implement the `sum` method")

    def mean(self) -> float:
        raise NotImplementedError(f"Please implement the `mean` method")

    def count(self) -> int:
        """Return the count of the single metric, NaN is not included."""

        raise NotImplementedError(f"Please implement the `count` method")

    def abs(self) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `abs` method")

    def astype(self, type: type) -> "BaseSingleMetric":
        raise NotImplementedError(f"Please implement the `astype` method")

    @property
    def empty(self) -> bool:
        """If metric is empty, return True."""

        raise NotImplementedError(f"Please implement the `empty` method")

    def add(self, other: "BaseSingleMetric", fill_value: float = None) -> "BaseSingleMetric":
        """Replace np.NaN with fill_value in two metrics and add them."""

        raise NotImplementedError(f"Please implement the `add` method")

    def replace(self, replace_dict: dict) -> "BaseSingleMetric":
        """Replace the value of metric according to replace_dict."""

        raise NotImplementedError(f"Please implement the `replace` method")

    def apply(self, func: dict) -> "BaseSingleMetric":
        """Replace the value of metric with func(metric).
        Currently, the func is only qlib/backtest/order/Order.parse_dir.
        """

        raise NotImplementedError(f"Please implement the 'apply' method")


class BaseOrderIndicator:
    """
    The data structure of order indicator.
    !!!NOTE: There are two ways to organize the data structure. Please choose a better way.
        1. One way is using BaseSingleMetric to represent each metric. For example, the data
        structure of PandasOrderIndicator is Dict[str, PandasSingleMetric]. It uses
        PandasSingleMetric based on pd.Series to represent each metric.
        2. The another way doesn't use BaseSingleMetric to represent each metric. The data
        structure of PandasOrderIndicator is a whole matrix. It means you are not necessary
        to inherit the BaseSingleMetric.
    """

    def __init__(self):
        self.logger = get_module_logger("online operator")

    def assign(self, col: str, metric: Union[dict, pd.Series]):
        """assign one metric.

        Parameters
        ----------
        col : str
            the metric name of one metric.
        metric : Union[dict, pd.Series]
            one metric with stock_id index, such as deal_amount, ffr, etc.
            for example:
                SH600068    NaN
                SH600079    1.0
                SH600266    NaN
                           ...
                SZ300692    NaN
                SZ300719    NaN,
        """

        raise NotImplementedError(f"Please implement the 'assign' method")

    def transfer(self, func: Callable, new_col: str = None) -> Union[None, BaseSingleMetric]:
        """compute new metric with existing metrics.

        Parameters
        ----------
        func : Callable
            the func of computing new metric.
            the kwargs of func will be replaced with metric data by name in this function.
            e.g.
                def func(pa):
                    return (pa > 0).astype(int).sum() / pa.count()
        new_col : str, optional
            New metric will be assigned in the data if new_col is not None, by default None.

        Return
        ----------
        BaseSingleMetric
            new metric.
        """

        raise NotImplementedError(f"Please implement the 'transfer' method")

    def get_metric_series(self, metric: str) -> pd.Series:
        """return the single metric with pd.Series format.

        Parameters
        ----------
        metric : str
            the metric name.

        Return
        ----------
        pd.Series
            the single metric.
            If there is no metric name in the data, return pd.Series().
        """

        raise NotImplementedError(f"Please implement the 'get_metric_series' method")

    def get_index_data(self, metric) -> IndexData.Series:
        """get one metric with the format of IndexData.Series

        Parameters
        ----------
        metric : str
            the metric name.

        Return
        ------
        IndexData.Series
            one metric with the format of IndexData.Series
        """

        raise NotImplementedError(f"Please implement the 'get_index_data' method")

    @staticmethod
    def sum_all_indicators(order_indicator, indicators: list, metrics: Union[str, List[str]], fill_value: float = None):
        """sum indicators with the same metrics.
        and assign to the order_indicator(BaseOrderIndicator).
        NOTE: indicators could be a empty list when orders in lower level all fail.

        Parameters
        ----------
        order_indicator : BaseOrderIndicator
            the order indicator to assign.
        indicators : List[BaseOrderIndicator]
            the list of all inner indicators.
        metrics : Union[str, List[str]]
            all metrics needs ot be sumed.
        fill_value : float, optional
            fill np.NaN with value. By default None.
        """

        raise NotImplementedError(f"Please implement the 'sum_all_indicators' method")

    def to_series(self) -> Dict[Text, pd.Series]:
        """return the metrics as pandas series

        for example: { "ffr":
                SH600068    NaN
                SH600079    1.0
                SH600266    NaN
                           ...
                SZ300692    NaN
                SZ300719    NaN,
                ...
         }
        """
        raise NotImplementedError(f"Please implement the `to_series` method")


class SingleMetric(BaseSingleMetric):
    def __add__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric + other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric + other.metric)
        else:
            return NotImplemented

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric - other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric - other.metric)
        else:
            return NotImplemented

    def __rsub__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(other - self.metric)
        elif isinstance(other, self.__class__):
            return self.__class__(other.metric - self.metric)
        else:
            return NotImplemented

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric * other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric * other.metric)
        else:
            return NotImplemented

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric / other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric / other.metric)
        else:
            return NotImplemented

    def __eq__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric == other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric == other.metric)
        else:
            return NotImplemented

    def __gt__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric > other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric > other.metric)
        else:
            return NotImplemented

    def __lt__(self, other):
        if isinstance(other, (int, float)):
            return self.__class__(self.metric < other)
        elif isinstance(other, self.__class__):
            return self.__class__(self.metric < other.metric)
        else:
            return NotImplemented

    def __len__(self):
        return len(self.metric)


class PandasSingleMetric(SingleMetric):
    """Each SingleMetric is based on pd.Series."""

    def __init__(self, metric: Union[dict, pd.Series]):
        if isinstance(metric, dict):
            self.metric = pd.Series(metric)
        elif isinstance(metric, pd.Series):
            self.metric = metric
        else:
            raise ValueError(f"metric must be dict or pd.Series")

    def sum(self):
        return self.metric.sum()

    def mean(self):
        return self.metric.mean()

    def count(self):
        return self.metric.count()

    def abs(self):
        return self.__class__(self.metric.abs())

    def astype(self, type):
        return self.__class__(self.metric.astype(type))

    @property
    def empty(self):
        return self.metric.empty

    def add(self, other, fill_value=None):
        return self.__class__(self.metric.add(other.metric, fill_value=fill_value))

    def replace(self, replace_dict: dict):
        return self.__class__(self.metric.replace(replace_dict))

    def apply(self, func: Callable):
        return self.__class__(self.metric.apply(func))


class PandasOrderIndicator(BaseOrderIndicator):
    """
    The data structure is OrderedDict(str: PandasSingleMetric).
    Each PandasSingleMetric based on pd.Series is one metric.
    Str is the name of metric.
    """

    def __init__(self):
        self.data: Dict[str, PandasSingleMetric] = OrderedDict()

    def assign(self, col: str, metric: Union[dict, pd.Series]):
        self.data[col] = PandasSingleMetric(metric)

    def transfer(self, func: Callable, new_col: str = None) -> Union[None, PandasSingleMetric]:
        func_sig = inspect.signature(func).parameters.keys()
        func_kwargs = {sig: self.data[sig] for sig in func_sig}
        tmp_metric = func(**func_kwargs)
        if new_col is not None:
            self.data[new_col] = tmp_metric
        else:
            return tmp_metric

    def get_index_data(self, metric):
        if metric in self.data:
            return IndexData.Series(self.data[metric].metric)
        else:
            return IndexData.Series()

    def get_metric_series(self, metric: str) -> Union[pd.Series]:
        if metric in self.data:
            return self.data[metric].metric
        else:
            return pd.Series()

    def to_series(self):
        return {k: v.metric for k, v in self.data.items()}

    @staticmethod
    def sum_all_indicators(order_indicator, indicators: list, metrics: Union[str, List[str]], fill_value=None):
        if isinstance(metrics, str):
            metrics = [metrics]
        for metric in metrics:
            tmp_metric = PandasSingleMetric({})
            for indicator in indicators:
                tmp_metric = tmp_metric.add(indicator.data[metric], fill_value)
            order_indicator.assign(metric, tmp_metric.metric)


class NumpyOrderIndicator(BaseOrderIndicator):
    """
    The data structure is OrderedDict(str: IndexData.Series).
    Each IndexData.Series is one metric.
    Str is the name of metric.
    """

    def __init__(self):
        self.data: Dict[str, IndexData.Series] = OrderedDict()

    def assign(self, col: str, metric: dict):
        self.data[col] = IndexData.Series(metric)

    def transfer(self, func: Callable, new_col: str = None) -> Union[None, IndexData.Series]:
        func_sig = inspect.signature(func).parameters.keys()
        func_kwargs = {sig: self.data[sig] for sig in func_sig}
        tmp_metric = func(**func_kwargs)
        if new_col is not None:
            self.data[new_col] = tmp_metric
        else:
            return tmp_metric

    def get_index_data(self, metric):
        if metric in self.data:
            return self.data[metric]
        else:
            return IndexData.Series()

    def get_metric_series(self, metric: str) -> Union[pd.Series]:
        return self.data[metric].to_pd_series()

    def to_series(self) -> Dict[str, pd.Series]:
        tmp_metric_dict = {}
        for metric in self.data:
            tmp_metric_dict[metric] = self.get_metric_series(metric)
        return tmp_metric_dict

    @staticmethod
    def sum_all_indicators(order_indicator, indicators: list, metrics: Union[str, List[str]], fill_value=0):
        if isinstance(metrics, str):
            metrics = [metrics]
        for metric in metrics:
            tmp_metric = IndexData.Series()
            for indicator in indicators:
                tmp_metric = tmp_metric.add(indicator.data[metric], fill_value)
            order_indicator.data[metric] = tmp_metric