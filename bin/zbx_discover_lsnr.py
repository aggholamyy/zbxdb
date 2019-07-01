#!/usr/bin/env python3
"""read list containing all required listener, convert to json lld array
   and send to zabbix"""
import json
import os
from argparse import ArgumentParser

# input file (no header)
# DNSNAME:PORT
# name1:1521
# name2:1521
#
# output:
# {"data":[{"{#DNSNAME}": "name1", "{#PORT}": "1521"}, {"{#DNSNAME}": "name2", "{#PORT}": "1521"}]}
ME = os.path.splitext(os.path.basename(__file__))[0]
CONFIG = ME + ".cfg"
OUTPUT = ME + ".lld"
_parser = ArgumentParser()
_parser.add_argument("-c", "--cfile", dest="configfile", default=ME+".cfg",
                     help="Configuration file", metavar="FILE")
_parser.add_argument("-s", "--servername", dest="servername", default="localhost", required=False,
                     help="zabbix server or proxy name")
_parser.add_argument("-p", "--port", dest="port", default=10051, required=False,
                     help="zabbix server or proxy name")
_parser.add_argument("-H", "--hostname", dest="hostname", required=True,
                     help="hostname to receive the discovery array")
_parser.add_argument("-k", "--key", dest="key", required=True,
                     help="key for the discovery array")
ARGS = _parser.parse_args()

L = []
with open(CONFIG, 'rt') as _f:
    for line in _f:
        c = line.rstrip()
        dns, port = c.split(':')
        _e = {"{#DNSNAME}": dns, "{#PORT}": port}
        L.append(_e)

LLD = ARGS.hostname + " " + ARGS.key + \
    " " + '{\"data\":' + json.dumps(L) + '}'

F = open(OUTPUT, "w")
F.write(LLD)
F.close()

cmd = "zabbix_sender -z {} -p {} -i {} -r  -vv".format(
    ARGS.servername, ARGS.port, OUTPUT)
os.system(cmd)
