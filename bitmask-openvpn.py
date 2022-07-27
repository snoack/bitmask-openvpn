#!/usr/bin/env python3

import argparse
import json
import logging
import math
import os
import re
import signal
import ssl
import subprocess
import sys
import time
import threading
import urllib.request
from datetime import datetime, timedelta

API_URL = "https://api.black.riseup.net/3/"
COUNTRY_CODES = {"US"}
OVPN_CONFIG_FILENAME = "bitmask.ovpn"
CERT_FILENAME = "cert.pem"
CA_FILENAME = "ca.pem"
PID_FILENAME = "pid"
ALLOWED_OPTIONS = {"auth", "cipher", "keepalive", "tls-cipher", "tun-ipv6", "float"}

def check_ca():
    if not os.access(CA_FILENAME, os.R_OK):
        print("Please obtain CA certificate and store it in", CA_FILENAME, file=sys.stderr)
        sys.exit(1)

def api_request(endpoint):
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(CA_FILENAME)
    req = urllib.request.Request(API_URL + endpoint, method="POST")
    return urllib.request.urlopen(req, context=ctx)

def generate_openvpn_config():
    with api_request("config/eip-service.json") as response:
        bitmask_config = json.load(response)

    ovpn_config = []
    for opt, val in bitmask_config["openvpn_configuration"].items():
        if opt not in ALLOWED_OPTIONS:
            logging.warning("Ignoring unsafe OpenVPN setting %r", opt)
            continue
        if val and val is not True:
            opt = "{} {}".format(opt, val)
        ovpn_config.append(opt)

    ovpn_config.extend([
        "cert " + CERT_FILENAME,
        "key " + CERT_FILENAME,
        "ca " + CA_FILENAME,
        "persist-tun",
        "nobind",
        "client",
        "dev tun",
        "tls-client",
        "remote-cert-tls server",
        "tls-version-min 1.0",
        "dhcp-option DNS 10.41.0.1",
        "writepid " + PID_FILENAME,
    ])

    for gw in bitmask_config["gateways"]:
        if bitmask_config["locations"][gw["location"]]["country_code"] not in COUNTRY_CODES:
            continue
        for tp in gw["capabilities"]["transport"]:
            if tp["type"] != "openvpn":
                continue
            for port in tp["ports"]:
                if int(port) == 53:
                    continue
                ovpn_config.append("remote {} {}".format(gw["ip_address"], port))

    return ovpn_config

def sort_remotes_by_ping(options):
    threads = []
    stats = {}

    def is_remote(opt): return opt.startswith("remote ")
    def extract_host(opt): return opt.split()[1]

    def run_in_thread(host):
        cmd = ["ping", host, "-c", "3"]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, encoding="ascii")
        paket_loss = latency = math.inf
        if p.returncode == 0:
            m = re.search(r"([\d.]+)% packet loss.*" +
                          r"min/avg/max\S* = [\d.]+/([\d.]+)", p.stdout, re.S)
            if m:
                packet_loss, latency = map(float, m.groups())
            else:
                logging.warning("Failed to parse output of %s", cmd)
        else:
            logging.warning("Failed to run %s", cmd)
        stats[host] = (paket_loss, latency)

    for host in {extract_host(opt) for opt in options if is_remote(opt)}:
        thread = threading.Thread(target=run_in_thread, args=(host,))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    options.sort(key=lambda o: stats[extract_host(o)] if is_remote(o) else (0, 0))

def update_openvpn_config(force=False):
    try:
        new_config = generate_openvpn_config()
    except urllib.request.URLError:
        logging.error("HTTP request loading the Bitmask configuration failed")
        return False

    if not force:
        try:
            with open(OVPN_CONFIG_FILENAME, "r") as file:
                old_config = file.read().splitlines()
                old_config.sort()
        except FileNotFoundError:
            old_config = None

        if old_config == sorted(new_config):
            logging.info("Reusing cached OpenVPN configuration")
            return False

    sort_remotes_by_ping(new_config)
    logging.info("Writing new OpenVPN configuration to %s", OVPN_CONFIG_FILENAME)
    with open(OVPN_CONFIG_FILENAME, "w") as file:
        for line in new_config:
            print(line, file=file)

    return True

def update_cert(force=False):
    if not force and os.path.exists(CERT_FILENAME):
        p = subprocess.run(
            ["openssl", "x509", "-in", CERT_FILENAME, "-noout", "-enddate"],
            stdout=subprocess.PIPE, encoding="ascii", check=True
        )
        expires = datetime.strptime(p.stdout.strip(), "notAfter=%b %d %H:%M:%S %Y %Z")
        if expires > datetime.now() + timedelta(weeks=1):
            logging.info("Reusing cached certifacte")
            return False

    try:
        with api_request("cert") as response: pem = response.read()
    except urllib.request.URLError:
        logging.error("HTTP request downloading the certificate failed")
        return False

    logging.info("Writing new certificate to %s", CERT_FILENAME)
    with open(CERT_FILENAME, "wb") as file: file.write(pem)
    return True

def restart_openvpn():
    logging.info("Restarting OpenVPN")
    try:
        with open(PID_FILENAME, "r") as file:
            os.kill(int(file.read()), signal.SIGHUP)
    except FileNotFoundError:
        logging.info("PID file does not exist, OpenVPN doesn't seem to be running")
    except ProcessLookupError:
        logging.warning("No such process, cannot restart OpenVPN")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", default="WARNING")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    logging.getLogger().setLevel(args.log_level)
    check_ca()
    if update_openvpn_config(args.force) | update_cert(args.force):
        restart_openvpn()