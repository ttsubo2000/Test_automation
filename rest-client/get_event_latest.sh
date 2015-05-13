#!/usr/bin/env python
#-*- coding: utf-8 -*-

import json
import sys
from common_func import request_info

##################
# get_event
##################

def start_get_event():
    operation = "get_event_latest"
    url_path = "/apgw/event/latest"
    method = "GET"

    event_result = request_info(operation, url_path, method, "")

    if event_result:
        print_event_result(event_result)

def print_event_result(event_result):
    event_id = event_result['event']['event_id']
    event_time = event_result['event']['event_time']
    event_type = event_result['event']['event_type']
    peer_bgp_id = event_result['event']['peer_bgp_id']
    peer_as = event_result['event']['peer_as']
    received_time = event_result['event']['received_time']
    vpnv4_prefix = event_result['event']['vpnv4_prefix']
    nexthop = event_result['event']['nexthop']
    ping_result = event_result['event']['ping_result']
    ping_recv = event_result['event']['ping_recv']
    show_neighbor_result = event_result['event']['show_neighbor_result']
    show_rib_result = event_result['event']['show_rib_result']

    print "-------------------------------------"
    print "Event Infomation"
    print "-------------------------------------"
    print "event_id      [%s]"%event_id
    print "event_time    [%s]"%event_time
    print "event_type    [%s]"%event_type
    print "peer_bgp_id   [%s]"%peer_bgp_id
    print "peer_as       [%s]"%peer_as
    print "received_time [%s]"%received_time
    print "vpnv4_prefix  [%s]"%vpnv4_prefix
    print "nexthop       [%s]"%nexthop
    print ""
    print "-------------------------------------"
    print "Ping Result [%s]"%ping_result
    print "-------------------------------------"
    print ping_recv
    print ""
    print "-------------------------------------"
    print "show Neighbor Result"
    print "-------------------------------------"
    print show_neighbor_result
    print ""
    print "-------------------------------------"
    print "show Rib Result"
    print "-------------------------------------"
    print show_rib_result




##############
# main
##############

def main():
    start_get_event()

if __name__ == "__main__":
    main()
