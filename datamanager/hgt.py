#coding=utf-8
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))
import _pickle
import const as ct
from log import getLogger
from cmysql import CMySQL
from datetime import datetime
from ccalendar import CCalendar
from common import get_day_nday_ago, create_redis_obj, get_dates_array
from datamanager.hk_crawl import MCrawl 
logger = getLogger(__name__)
class StockConnect(object):
    def __init__(self, market_from = ct.SH_MARKET_SYMBOL, market_to = ct.HK_MARKET_SYMBOL, dbinfo = ct.DB_INFO, redis_host = None):
        self.market_from  = market_from
        self.market_to    = market_to
        self.balcklist    = ["2018-10-17", "2018-09-25", "2018-07-02", "2018-05-22", "2018-04-02", "2018-03-30"] if market_from in [ct.SH_MARKET_SYMBOL, ct.SZ_MARKET_SYMBOL] else list()
        self.crawler      = MCrawl(market_from)
        self.dbname       = self.get_dbname(market_from, market_to)
        self.redis        = create_redis_obj() if redis_host is None else create_redis_obj(host = redis_host)
        self.mysql_client = CMySQL(dbinfo, self.dbname, iredis = self.redis)
        if not self.mysql_client.create_db(self.dbname): raise Exception("init stock connect database failed")

    @staticmethod
    def get_dbname(mfrom, mto):
        return "%s2%s" % (mfrom,mto)

    def get_table_name(self, cdate):
        cdates = cdate.split('-')
        return "%s_stock_day_%s_%s" % (self.dbname, cdates[0], (int(cdates[1])-1)//3 + 1)

    def is_date_exists(self, table_name, cdate):
        if self.redis.exists(table_name):
            return cdate in set(str(tdate, encoding = "utf8") for tdate in self.redis.smembers(table_name))
        return False

    def create_table(self, table):
        sql = 'create table if not exists %s(date varchar(10) not null,\
                                             code varchar(10) not null,\
                                             name varchar(90),\
                                             volume int,\
                                             percent float,\
                                             PRIMARY KEY (date, code))' % table
        return True if table in self.mysql_client.get_all_tables() else self.mysql_client.create(sql, table)

    def get_k_data_in_range(self, start_date, end_date):
        ndays = delta_days(start_date, end_date)
        date_dmy_format = time.strftime("%m/%d/%Y", time.strptime(start_date, "%Y-%m-%d"))
        data_times = pd.date_range(date_dmy_format, periods=ndays, freq='D')
        date_only_array = np.vectorize(lambda s: s.strftime('%Y-%m-%d'))(data_times.to_pydatetime())
        data_dict = OrderedDict()
        for _date in date_only_array:
            if CCalendar.is_trading_day(_date, redis = self.redis):
                table_name = self.get_table_name(_date)
                if table_name not in data_dict: data_dict[table_name] = list()
                data_dict[table_name].append(str(_date))
        all_df = pd.DataFrame()
        for key in data_dict:
            table_list = sorted(data_dict[key], reverse=False)
            if len(table_list) == 1:
                df = self.get_k_data(table_list[0])
                if df is not None: all_df = all_df.append(df)
            else:
                start_date = table_list[0]
                end_date = table_list[len(table_list) - 1]
                df = self.get_data_between(start_date, end_date)
                if df is not None: all_df = all_df.append(df)
        return all_df

    def get_data_between(self, start_date, end_date):
        #start_date and end_date should be in the same table
        sql = "select * from %s where date between \"%s\" and \"%s\"" % (self.get_table_name(start_date), start_date, end_date)
        return self.mysql_client.get(sql)

    def get_k_data(self, cdate):
        cdate = datetime.now().strftime('%Y-%m-%d') if cdate is None else cdate
        sql = "select * from %s where date=\"%s\"" % (self.get_table_name(cdate), cdate)
        return self.mysql_client.get(sql)

    def update(self):
        #end_date   = datetime.now().strftime('%Y-%m-%d')
        #start_date = get_day_nday_ago(end_date, num = 9, dformat = "%Y-%m-%d")
        start_date = '2017-10-31'
        end_date   = '2018-10-30'
        for mdate in get_dates_array(start_date, end_date):
            if mdate in self.balcklist: continue
            if CCalendar.is_trading_day(mdate, redis = self.redis):
                res = self.set_data(mdate)
                if not res:
                    logger.error("%s get data failed" % mdate)
                else:
                    logger.info("%s get data success" % mdate)

    def is_table_exists(self, table_name):
        if self.redis.exists(self.dbname):
            return table_name in set(str(table, encoding = "utf8") for table in self.redis.smembers(self.dbname))
        return False

    def set_data(self, cdate = datetime.now().strftime('%Y-%m-%d')):
        table_name = self.get_table_name(cdate)
        if not self.is_table_exists(table_name):
            if not self.create_table(table_name):
                logger.error("create tick table failed")
                return False
            self.redis.sadd(self.dbname, table_name)
        if self.is_date_exists(table_name, cdate): 
            logger.debug("existed table:%s, date:%s" % (table_name, cdate))
            return True
        ret, df = self.crawler.crawl(cdate)
        if ret != 0: return False
        df = df.reset_index(drop = True)
        df['date'] = cdate
        if self.mysql_client.set(df, table_name):
            self.redis.sadd(table_name, cdate)
            return True
        return False

if __name__ == '__main__':
    sc = StockConnect(market_from = "SZ", market_to = "HK", redis_host = '127.0.0.1')
    sc.update()
