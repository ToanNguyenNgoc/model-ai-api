import datetime

def format_time(date_time):
    return datetime.datetime.strptime(date_time, "%Y-%m-%d %H:%M:%S")