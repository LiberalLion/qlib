# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import os
import pickle
import yaml
import pathlib
import pandas as pd
import shutil
from ..backtest.account import Account
from ..backtest.exchange import Exchange
from .user import User
from .utils import load_instance
from ...utils import save_instance, init_instance_by_config


class UserManager:
    def __init__(self, user_data_path, save_report=True):
        """
        This module is designed to manager the users in online system
        all users' data were assumed to be saved in user_data_path
            Parameter
                user_data_path : string
                    data path that all users' data were saved in

        variables:
            data_path : string
                data path that all users' data were saved in
            users_file : string
                A path of the file record the add_date of users
            save_report : bool
                whether to save report after each trading process
            users : dict{}
                [user_id]->User()
                the python dict save instances of User() for each user_id
            user_record : pd.Dataframe
                user_id(string), add_date(string)
                indicate the add_date for each users
        """
        self.data_path = pathlib.Path(user_data_path)
        self.users_file = self.data_path / "users.csv"
        self.save_report = save_report
        self.users = {}
        self.user_record = None

    def load_users(self):
        """
        load all users' data into manager
        """
        self.users = {}
        self.user_record = pd.read_csv(self.users_file, index_col=0)
        for user_id in self.user_record.index:
            self.users[user_id] = self.load_user(user_id)

    def load_user(self, user_id):
        """
        return a instance of User() represents a user to be processed
            Parameter
                user_id : string
            :return
                user : User()
        """
        account_path = self.data_path / user_id
        strategy_file = self.data_path / user_id / f"strategy_{user_id}.pickle"
        model_file = self.data_path / user_id / f"model_{user_id}.pickle"
        cur_user_list = list(self.users)
        if user_id in cur_user_list:
            raise ValueError(f"User {user_id} has been loaded")
        trade_account = Account(0)
        trade_account.load_account(account_path)
        strategy = load_instance(strategy_file)
        model = load_instance(model_file)
        return User(account=trade_account, strategy=strategy, model=model)

    def save_user_data(self, user_id):
        """
        save a instance of User() to user data path
            Parameter
                user_id : string
        """
        if user_id not in self.users:
            raise ValueError(f"Cannot find user {user_id}")
        self.users[user_id].account.save_account(self.data_path / user_id)
        save_instance(
            self.users[user_id].strategy,
            self.data_path / user_id / f"strategy_{user_id}.pickle",
        )
        save_instance(
            self.users[user_id].model,
            self.data_path / user_id / f"model_{user_id}.pickle",
        )

    def add_user(self, user_id, config_file, add_date):
        """
        add the new user {user_id} into user data
        will create a new folder named "{user_id}" in user data path
            Parameter
                user_id : string
                init_cash : int
                config_file : str/pathlib.Path()
                   path of config file
        """
        config_file = pathlib.Path(config_file)
        if not config_file.exists():
            raise ValueError(f"Cannot find config file {config_file}")
        user_path = self.data_path / user_id
        if user_path.exists():
            raise ValueError(f"User data for {user_id} already exists")

        with config_file.open("r") as fp:
            config = yaml.safe_load(fp)
        # load model
        model = init_instance_by_config(config["model"])

        # load strategy
        strategy = init_instance_by_config(config["strategy"])
        init_args = strategy.get_init_args_from_model(model, add_date)
        strategy.init(**init_args)

        # init Account
        trade_account = Account(init_cash=config["init_cash"])

        # save user
        user_path.mkdir()
        save_instance(model, self.data_path / user_id / f"model_{user_id}.pickle")
        save_instance(
            strategy, self.data_path / user_id / f"strategy_{user_id}.pickle"
        )
        trade_account.save_account(self.data_path / user_id)
        user_record = pd.read_csv(self.users_file, index_col=0)
        user_record.loc[user_id] = [add_date]
        user_record.to_csv(self.users_file)

    def remove_user(self, user_id):
        """
        remove user {user_id} in current user dataset
        will delete the folder "{user_id}" in user data path
            :param
                user_id : string
        """
        user_path = self.data_path / user_id
        if not user_path.exists():
            raise ValueError(f"Cannot find user data {user_id}")
        shutil.rmtree(user_path)
        user_record = pd.read_csv(self.users_file, index_col=0)
        user_record.drop([user_id], inplace=True)
        user_record.to_csv(self.users_file)
