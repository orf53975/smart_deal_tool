#coding=utf-8
import time
import _pickle
import datetime
from datetime import datetime
import const as ct
import pandas as pd
import tushare as ts
import cstock_info as cs_info
from cmysql import CMySQL
from log import getLogger
from common import trace_func,is_trading_time,df_delta,create_redis_obj,get_redis_name

logger = getLogger(__name__)

class CStock:
    def __init__(self, dbinfo, code):
        self.code = code
        self.redis = create_redis_obj()
        self.name = self.get('name')
        self.data_type_dict = {'D':"%s_D" % code}
        self.realtime_table = "%s_realtime" % self.code
        self.mysql_client = CMySQL(dbinfo)
        if not self.create(): raise Exception("create stock %s table failed" % self.code)

    def is_subnew(self, time2Market = None, timeLimit = 365):
        if time2Market == '0': return False #for stock has not been in market
        if time2Market == None: time2Market = self.get('timeToMarket')
        t = time.strptime(time2Market, "%Y%m%d")
        y,m,d = t[0:3]
        time2Market = datetime(y,m,d)
        return True if (datetime.today()-time2Market).days < timeLimit else False

    def create_static(self):
        for _, table_name in self.data_type_dict.items():
            if table_name not in self.mysql_client.get_all_tables():
                sql = 'create table if not exists %s(date varchar(10), open float, high float, close float, low float, volume float, code varchar(6))' % table_name 
                if not self.mysql_client.create(sql, table_name): return False
        return True

    def create_realtime(self):
        sql = 'create table if not exists %s(date varchar(25),\
                                              name varchar(20),\
                                              code varchar(10),\
                                              open float,\
                                              pre_close float,\
                                              price float,\
                                              high float,\
                                              low float,\
                                              bid float,\
                                              ask float,\
                                              volume float,\
                                              amount float,\
                                              b1_v int,\
                                              b1_p float,\
                                              b2_v int,\
                                              b2_p float,\
                                              b3_v int,\
                                              b3_p float,\
                                              b4_v int,\
                                              b4_p float,\
                                              b5_v int,\
                                              b5_p float,\
                                              a1_v int,\
                                              a1_p float,\
                                              a2_v int,\
                                              a2_p float,\
                                              a3_v int,\
                                              a3_p float,\
                                              a4_v int,\
                                              a4_p float,\
                                              a5_v int,\
                                              a5_p float,\
                                              time varchar(20),\
                                              turnover float,\
                                              p_change float,\
                                              outstanding float,\
                                              limit_down_time varchar(20),\
                                              limit_up_time varchar(20))' % self.realtime_table
        return True if self.realtime_table in self.mysql_client.get_all_tables() else self.mysql_client.create(sql, self.realtime_table)

    def create(self):
        return self.create_static() and self.create_realtime()

    def init(self):
        _today = datetime.now().strftime('%Y-%m-%d')
        for d_type,d_table_name in self.data_type_dict.items():
            new_data = ts.get_k_data(self.code, ktype=d_type, start=ct.START_DATE, end=_today, retry_count = ct.RETRY_TIMES)
            if not new_data.empty:
                df = new_data.reset_index(drop=True)
                self.mysql_client.set(df, d_table_name)

    def get(self, attribute):
        df_byte = self.redis.get(ct.STOCK_INFO)
        if df_byte is None: return None
        df = _pickle.loads(df_byte)
        return df.loc[df.code == self.code][attribute].values[0]

    def run(self, evt):
        all_info = evt.get()
        if all_info is not None:
            _info = all_info[all_info.code == self.code]
            _info['outstanding'] = self.get('outstanding')
            _info['turnover'] = _info['volume'].astype(float).divide(_info['outstanding'])
            self.redis.set(get_redis_name(self.code), _pickle.dumps(_info, 2))
            self.mysql_client.set(_info, self.realtime_table)

    def arun(self): 
        _info = ts.get_realtime_quotes(self.code)
        if _info is not None and not _info.empty:
            ############################
            ##### something to do  #####
            _info['limit_up_time'] = 0
            _info['limit_down_time'] = 0
            ############################
            convert_list = ['b1_v', 'b2_v', 'b3_v', 'b4_v', 'b5_v', 'a1_v', 'a2_v', 'a3_v', 'a4_v', 'a5_v']
            for conver_str in convert_list:
                _info[conver_str] = pd.to_numeric(_info[conver_str], errors='coerce')
            _info['outstanding'] = self.get('outstanding')
            _info['turnover'] = _info['volume'].astype(float).divide(_info['outstanding'])
            _info['p_change'] = 100 * (_info['price'].astype(float) - _info['pre_close'].astype(float)).divide(_info['pre_close'].astype(float))
            self.redis.set(get_redis_name(self.code), _pickle.dumps(_info, 2))
            self.mysql_client.set(_info, self.realtime_table)

    def get_k_data(self, date = None, dtype = 'D'):
        table_name = self.data_type_dict[dtype] 
        if date is not None:
            sql = "select * from %s where date=\"%s\"" %(table_name, date)
        else:
            sql = "select * from %s" % table_name
        return self.mysql_client.get(sql)

    def is_after_release(self, code_id, _date):
        time2Market = self.get('timeToMarket')
        t = time.strptime(str(time2Market), "%Y%m%d")
        y,m,d = t[0:3]
        time2Market = datetime(y,m,d)
        return (datetime.strptime(_date, "%Y-%m-%d") - time2Market).days > 0

if __name__ == '__main__':
    CStock(ct.DB_INFO, '300747')