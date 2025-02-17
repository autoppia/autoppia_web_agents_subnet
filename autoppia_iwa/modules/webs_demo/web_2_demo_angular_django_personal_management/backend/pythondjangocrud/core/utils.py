import re
from collections import namedtuple
from datetime import date, datetime, timedelta


def date_range(start_date: date, end_date: date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)


def str_to_datetime(date_time_str, format='%Y-%m-%d %H:%M:%S.%f', default=datetime.now()):
    """ Conviente de str a datetime desde un formato o retorna default

    :param date_time_str: String que se dese convertir
    :param format: Formato del string
    :param default: En caso el formato no corresponda
    :return: datetime
    """
    try:
        date_time_obj = datetime.strptime(date_time_str, format)
    except (ValueError, TypeError, Exception):
        date_time_obj = default
    return date_time_obj


def camel_to_snake_str(camel_str):
    upper_snake_str = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', camel_str)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', upper_snake_str).lower()


def camel_to_snake_object_keys(obj):
    return dict([(camel_to_snake_str(key), obj.get(key, None)) for key in obj.keys()])


def choices_to_list(choices):
    return [{'id': id, 'name': name} for (id, name) in choices]


def named_tuple_fetch_all(cursor):
    """
    Return all rows from a cursor as a namedtuple.
    """
    desc = cursor.description
    nt_result = namedtuple('Result', [col[0] for col in desc])
    return [nt_result(*row) for row in cursor.fetchall()]


def try_or(item, keys, default):
    temp = item

    try:
        for key in keys:
            temp = temp.get(key)
        return temp or default
    except:
        return default


def group_days(total_days):
    YEAR = 365
    MONTH = 30
    years = int(total_days / YEAR)
    months = int((total_days % YEAR) / MONTH)
    days = (total_days % YEAR) % MONTH
    return years, months, days
