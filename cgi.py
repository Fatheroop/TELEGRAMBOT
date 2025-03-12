# cgi.py - Minimal shim for Python 3.13 compatibility

import re

_headerre = re.compile(r';\s*')

def parse_header(line):
    """
    Parse a header line (e.g. a Content-Type header).
    Returns a tuple: (main_value, params_dict)
    """
    parts = _headerre.split(line)
    key = parts[0].strip()
    pdict = {}
    for item in parts[1:]:
        if '=' in item:
            k, v = item.split('=', 1)
            pdict[k.strip()] = v.strip().strip('"')
    return key, pdict
