# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.


from __future__ import division
from __future__ import print_function

import copy
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr


from ..data import D

from collections import OrderedDict


def _get_position_value_from_df(evaluate_date, position, close_data_df):
    """Get position value by existed close data df
    close_data_df:
        pd.DataFrame
        multi-index
        close_data_df['$close'][stock_id][evaluate_date]: close price for (stock_id, evaluate_date)
    position:
        same in get_position_value()
    """
    value = sum(
        report["amount"] * close_data_df["$close"][stock_id][evaluate_date]
        for stock_id, report in position.items()
        if stock_id != "cash"
    )
    if "cash" in position:
        value += position["cash"]
    return value


def get_position_value(evaluate_date, position):
    """sum of close*amount

    get value of postion

    use close price

        postions:
        {
            Timestamp('2016-01-05 00:00:00'):
            {
                'SH600022':
                {
                    'amount':100.00,
                    'price':12.00
                },

                'cash':100000.0
            }
        }

    It means Hold 100.0 'SH600022' and 100000.0 RMB in '2016-01-05'
    """
    # load close price for position
    # position should also consider cash
    instruments = list(position.keys())
    instruments = list(set(instruments) - {"cash"})  # filter 'cash'
    fields = ["$close"]
    close_data_df = D.features(
        instruments,
        fields,
        start_time=evaluate_date,
        end_time=evaluate_date,
        freq="day",
        disk_cache=0,
    )
    return _get_position_value_from_df(evaluate_date, position, close_data_df)


def get_position_list_value(positions):
    # generate instrument list and date for whole poitions
    instruments = set()
    for day, position in positions.items():
        instruments.update(position.keys())
    instruments = sorted(set(instruments) - {"cash"})
    day_list = sorted(positions.keys())
    start_date, end_date = day_list[0], day_list[-1]
    # load data
    fields = ["$close"]
    close_data_df = D.features(
        instruments,
        fields,
        start_time=start_date,
        end_time=end_date,
        freq="day",
        disk_cache=0,
    )
    # generate value
    # return dict for time:position_value
    value_dict = OrderedDict()
    for day, position in positions.items():
        value = _get_position_value_from_df(evaluate_date=day, position=position, close_data_df=close_data_df)
        value_dict[day] = value
    return value_dict


def get_daily_return_series_from_positions(positions, init_asset_value):
    """Parameters
    generate daily return series from  position view
    positions: positions generated by strategy
    init_asset_value : init asset value
    return: pd.Series of daily return , return_series[date] = daily return rate
    """
    value_dict = get_position_list_value(positions)
    value_series = pd.Series(value_dict)
    value_series = value_series.sort_index()  # check date
    return_series = value_series.pct_change()
    return_series[value_series.index[0]] = (
        value_series[value_series.index[0]] / init_asset_value - 1
    )  # update daily return for the first date
    return return_series


def get_annual_return_from_positions(positions, init_asset_value):
    """Annualized Returns

    p_r = (p_end / p_start)^{(250/n)} - 1

    p_r     annual return
    p_end   final value
    p_start init value
    n       days of backtest

    """
    date_range_list = sorted(list(positions.keys()))
    end_time = date_range_list[-1]
    p_end = get_position_value(end_time, positions[end_time])
    p_start = init_asset_value
    n_period = len(date_range_list)
    return pow((p_end / p_start), (250 / n_period)) - 1


def get_annaul_return_from_return_series(r, method="ci"):
    """Risk Analysis from daily return series

    Parameters
    ----------
    r : pandas.Series
        daily return series
    method : str
        interest calculation method, ci(compound interest)/si(simple interest)
    """
    mean = r.mean()
    return (1 + mean) ** 250 - 1 if method == "ci" else mean * 250


def get_sharpe_ratio_from_return_series(r, risk_free_rate=0.00, method="ci"):
    """Risk Analysis

    Parameters
    ----------
    r : pandas.Series
        daily return series
    method : str
        interest calculation method, ci(compound interest)/si(simple interest)
    risk_free_rate : float
        risk_free_rate, default as 0.00, can set as 0.03 etc
    """
    std = r.std(ddof=1)
    annual = get_annaul_return_from_return_series(r, method=method)
    return (annual - risk_free_rate) / std / np.sqrt(250)


def get_max_drawdown_from_series(r):
    """Risk Analysis from asset value

    cumprod way

    Parameters
    ----------
    r : pandas.Series
        daily return series
    """
    return (
        ((1 + r).cumprod() - (1 + r).cumprod().cummax())
        / ((1 + r).cumprod().cummax())
    ).min()


def get_turnover_rate():
    # in backtest
    pass


def get_beta(r, b):
    """Risk Analysis  beta

    Parameters
    ----------
    r : pandas.Series
        daily return series of strategy
    b : pandas.Series
        daily return series of baseline
    """
    cov_r_b = np.cov(r, b)
    var_b = np.var(b)
    return cov_r_b / var_b


def get_alpha(r, b, risk_free_rate=0.03):
    beta = get_beta(r, b)
    annaul_r = get_annaul_return_from_return_series(r)
    annaul_b = get_annaul_return_from_return_series(b)

    return annaul_r - risk_free_rate - beta * (annaul_b - risk_free_rate)


def get_volatility_from_series(r):
    return r.std(ddof=1)


def get_rank_ic(a, b):
    """Rank IC

    Parameters
    ----------
    r : pandas.Series
        daily score series of feature
    b : pandas.Series
        daily return series

    """
    return spearmanr(a, b).correlation


def get_normal_ic(a, b):
    return pearsonr(a, b).correlation
