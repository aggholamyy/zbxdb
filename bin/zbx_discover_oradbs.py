#!/usr/bin/env python3
"""call request listener sid list from all listeners given in config file
   to generate discovery array for oradb.lld
   config file csv format is:
   'site;[cluster];alert_group;protocol;[user];[password];[password_enc];machine[,]...'
   site         - somesite
   cluster      - in case of RAC
   alert_group
   protocol     - ssh or rdp
   user         - optional for ssh
   password     - plain text form of rdp password (removed during encryption)
   password_enc - encrypted form of rdp password
   machine[s]   - list of cluster members or single machine name

   run lsnrctl status on all machines and form the oradb.lld array
   """

import base64
import csv
import json
import os
import pwd
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from tempfile import NamedTemporaryFile

from pypsrp.client import Client


def encrypted(plain):
    """encrypt plaintext password"""

    return base64.b64encode(bytes(plain, 'utf-8'))


def decrypted(pw_enc):
    """return decrypted password"""

    return base64.b64decode(pw_enc).decode("utf-8", "ignore")


def get_config(filename, _me):
    """read the specified configuration file"""
    user = pwd.getpwuid(os.geteuid())
    home = user.pw_dir

    if os.path.isabs(filename):
        c_file = filename
    else:
        c_file = os.path.join(home, filename)

    if not os.path.exists(c_file):
        raise ValueError("Configfile " + c_file + " does not exist")

    encryptedF = False
    tempfile = NamedTemporaryFile(mode='w', delete=False)
    with open(c_file, 'r') as _inif, tempfile:
        reader = csv.DictReader(_inif, delimiter=';')
        writer = csv.DictWriter(tempfile, delimiter=';',
                                fieldnames=reader.fieldnames)

        writer.writeheader()

        for row in reader:

            if row['password']:
                # print("encrypting pwd for {} on {}".format(row['user'], row['members']))
                row['password_enc'] = encrypted(row['password']).decode()
                row['password'] = ''
                # print("decrypted {}".format(decrypted(row['password_enc'])))
                encryptedF = True
            writer.writerow(row)

    if encryptedF:
        shutil.move(tempfile.name, c_file)
    else:
        os.remove(tempfile.name)

    config = []
    with open(c_file, 'r') as _inif:
        reader = csv.DictReader(_inif, delimiter=';')

        for row in reader:

            if row['password_enc']:
                # print("decrypting pwd for {} on {}".format(row['user'], row['members']))
                row['password'] = decrypted(row['password_enc'])
            config.append(row)

    return config


def get_ssh(config):
    commands = """
tns=`ps -ef|grep tnslsnr|grep -v grep|awk '{print $8}'|sort|uniq|tail -1`
echo tns=$tns
dir=$(dirname $tns)
echo "dir=$dir"
export ORACLE_HOME=$(dirname $dir)
$ORACLE_HOME/bin/lsnrctl status
    """
    results = []
    for member in config['members'].split(','):
        ssh = subprocess.Popen(["ssh", "-q", member],
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        std_data, std_err = ssh.communicate(commands.encode())
        res = std_data.decode()
        err = std_err.decode()
        if err:
            print("get_ssh: {} -> err: {}".format(config, err), file=sys.stderr)
        results.append(res)
    return config, results


def get_rdp(config):

    results = []
    for member in config['members'].split(','):
        client = Client(member, ssl=False, auth="ntlm",
                        cert_validation=False,
                        username=config['user'], password=config['password'])
        stdout, stderr, _rc = client.execute_cmd("lsnrctl status".encode())
        res = stdout.decode()
        err = stderr.decode()
        if err:
            print("get_rdp: {} -> err: {}".format(config, err), file=sys.stderr)
        results.append(res)

    return config, results


def main():
    """the entry point"""
    _me = os.path.splitext(os.path.basename(__file__))[0]
    _output = _me + ".lld"

    _parser = ArgumentParser()
    _parser.add_argument("-c", "--cfile", dest="configfile", default=_me+".cfg",
                         help="Configuration file", metavar="FILE", required=False)
    _parser.add_argument("-v", "--verbosity", action="count", default=0,
                         help="increase output verbosity")
    _parser.add_argument("-l", "--lld_key", action="store", default="oradb.lld",
                         help="key to use for zabbix_host lld")
    _parser.add_argument("-z", "--zabbix_host", action="store",
                         help="zabbix hostname that has the oradb.lld rule")
    _parser.add_argument("-s", "--server", action="store",
                         help="zabbix server or proxy name")
    _parser.add_argument("-p", "--port", action="store", default="10050",
                         help="port of zabbix server of proxy to send to")
    _args = _parser.parse_args()

    config = get_config(_args.configfile, _me)

    if _args.verbosity:
        print(config)
        print(_args)

    lsnrstats = []

    for row in config:
        if row['protocol'] == "ssh":
            lsnrstats.append(get_ssh(row))
        elif row['protocol'] == 'rdp':
            lsnrstats.append(get_rdp(row))
        else:
            print("unknown/implemented protocol {}".format(row['protocol']),
                  file=sys.stderr)
            sys.exit(1)

    if _args.verbosity > 1:
        print(lsnrstats)

    databases = []

    for member in lsnrstats:
        if _args.verbosity > 1:
            print("member config {}".format(member[0]))
        instances = []

        for lines in member[1]:
            for line in lines.split('\n'):
                if "Instance" in line:
                    if "READY" in line:
                        if _args.verbosity > 2:
                            print("line: {}".format(line))
                        instance = line.split('"')[1]

                        if _args.verbosity > 2:
                            print(instance)
                        instances.append(instance)
        sorti = sorted(list(set(instances)))

        if member[0]['cluster']:
            if _args.verbosity > 1:
                print("cluster {} {}".format(member[0]['cluster'], sorti))
            dbs = set([i.rstrip('0123456789') for i in sorti])

        else:
            if _args.verbosity > 1:
                print("node {} {}".format(member[0]['members'], sorti))
            dbs = sorti

        dbs = [i.lstrip('-+') for i in dbs]

        for db in dbs:
            _e = {"{#DB_NAME}": member[0]['site']+"_"+db}

            if member[0]['cluster']:
                _e.update(
                    {"{#GROUP}": member[0]['site']+"_"+member[0]['cluster']})
            else:
                _e.update({"{#GROUP}": member[0]['site']})

            if member[0]['alert_group']:
                _e.update({"{#ALERT}": member[0]['alert_group']})
            databases.append(_e)

    if _args.verbosity > 1:
        print(databases)

    OUTPUT = _me + ".lld"

    if _args.zabbix_host:
        array = str(_args.zabbix_host) + ' ' + _args.lld_key + \
            ' ' + '{\"data\":' + json.dumps(databases) + '}'
        F = open(OUTPUT, "w")
        F.write(array)
        F.close()
        CMD = "zabbix_sender -z {} -p {} -i {} -r  -vv".format(
            _args.server, _args.port, OUTPUT)
        os.system(CMD)
    else:
        print('{\"data\":' + json.dumps(databases) + '}')


if __name__ == "__main__":
    main()
