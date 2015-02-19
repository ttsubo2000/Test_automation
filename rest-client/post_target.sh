#!/usr/bin/env python
#-*- coding: utf-8 -*-

import json
import sys
from common_func import request_info

##################
# create_target
##################

def start_create_target(peer_as, vpnv4_prefix, ping_scrip, ping_destip, ssh_host, ssh_user, ssh_pass):
    operation = "create_target"
    url_path = "/apgw/test"
    method = "POST"
    request = '''
{
"target": {
"peer_as": "%s",
"vpnv4_prefix": "%s",
"ping_srcip": "%s",
"ping_destip": "%s",
"ssh_host": "%s",
"ssh_user": "%s",
"ssh_pass": "%s"
}
}'''%(peer_as, vpnv4_prefix, ping_scrip, ping_destip, ssh_host, ssh_user, ssh_pass)

    target_result = request_info(operation, url_path, method, request)
    print "----------"
    print json.dumps(target_result, sort_keys=False, indent=4)
    print ""



##############
# main
##############

def main(argv):
    peer_as = argv[1]
    vpnv4_prefix = argv[2]
    ping_srcip = argv[3]
    ping_destip = argv[4]
    ssh_host = argv[5]
    ssh_user = argv[6]
    ssh_pass = argv[7]
    start_create_target(peer_as, vpnv4_prefix, ping_srcip, ping_destip, ssh_host, ssh_user, ssh_pass)

if __name__ == "__main__":
    if (len(sys.argv) != 8):
        print "Usage: post_target.sh [peer_as] [vpnv4_prefix] [ping_srcip] [destip] [ssh_host] [ssh_user] [ssh_pass]"
        sys.exit()
    else:
        main(sys.argv)
