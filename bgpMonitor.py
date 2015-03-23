# Copyright (c) 2014-2015 ttsubo
# This software is released under the MIT License.
# http://opensource.org/licenses/mit-license.php

import logging
import socket
import time
import subprocess

from datetime import datetime
from ryu.base import app_manager
from ryu.lib import hub
from ryu.lib.hub import StreamServer
from ryu.lib.packet import bmp
from ryu.lib.packet import bgp
from oslo.config import cfg

LOG = logging.getLogger('BgpMonitor')
LOG.setLevel(logging.DEBUG)
logging.basicConfig()

HOST = '0.0.0.0'
PORT = 11019
ADDR = (HOST, PORT)


class BgpMonitor(app_manager.RyuApp):
    def __init__(self):
        super(BgpMonitor, self).__init__()
        self.bmp_q = hub.Queue()
        self.name = 'bmp'

    def start(self):
        self.targetInfo = {}
        super(BgpMonitor, self).start()
        return hub.spawn(StreamServer(ADDR, self.handler).serve_forever)

    def handler(self, sock, addr):
        self.logger.debug("BMP client connected, ip=%s, port=%s" % addr)
        is_active = True
        buf = bytearray()
        required_len = bmp.BMPMessage._HDR_LEN

        while is_active:
            ret = sock.recv(required_len)
            if len(ret) == 0:
                is_active = False
                break
            buf += ret
            while len(buf) >= required_len:
                version, len_, _ = bmp.BMPMessage.parse_header(buf)
                if version != bmp.VERSION:
                    self.logger.error("unsupported bmp version: %d" % version)
                    is_active = False
                    break

                required_len = len_
                if len(buf) < required_len:
                    break

                try:
                    msg, rest = bmp.BMPMessage.parser(buf)
                except Exception, e:
                    pkt = buf[:len_]
                    buf = buf[len_:]
                    self.failed_pkt_count += 1
                    self.logger.error("failed to parse: %s"
                                      " (total fail count: %d)" %
                                      (e, self.failed_pkt_count))
                else:
                    buf = rest
                    if isinstance(msg, bmp.BMPInitiation):
                        LOG.info("Start BMP session!! [%s]"%addr[0])
                    elif isinstance(msg, bmp.BMPPeerUpNotification):
                        self.print_BMPPeerUpNotification(msg, addr)
                    elif isinstance(msg, bmp.BMPRouteMonitoring):
                        self.print_BMPRouteMonitoring(msg, addr)
                    elif isinstance(msg, bmp.BMPPeerDownNotification):
                        self.print_BMPPeerDownNotification(msg, addr)

                required_len = bmp.BMPMessage._HDR_LEN

        self.logger.debug("BMP client disconnected, ip=%s, port=%s" % addr)
        sock.close()

    def print_BMPPeerUpNotification(self, msg, addr):
        if msg.timestamp == 0:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
            self.print_BGP_PeerUpNotification(msg, addr, bgp_t)
        else:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                                   time.localtime(int(msg.timestamp)))
            time1 = time.mktime(time.localtime(int(msg.timestamp)))
            time2 = time.mktime(time.localtime())
            time_delta = time2 - time1
            if time_delta < 30:
                self.print_BGP_PeerUpNotification(msg, addr, bgp_t)

    def print_BGP_PeerUpNotification(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['event_type'] = "adj_up"
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['prefix'] = None
        bmp_result['route_dist'] = None
        bmp_result['vpnv4_prefix'] = None
        bmp_result['nexthop'] = None
        self.bmp_q.put(bmp_result)
        LOG.debug("bmp_result=%s"%bmp_result)

    def print_BMPPeerDownNotification(self, msg, addr):
        bmp_result = {}
        peer_as = msg.peer_as
        peer_bgp_id = msg.peer_bgp_id
        now_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        bmp_result['received_time'] = now_t
        bmp_result['received_host'] = addr[0]
        bmp_result['event_type'] = "adj_down"
        bmp_result['peer_as'] = peer_as
        bmp_result['peer_bgp_id'] = peer_bgp_id
        bmp_result['prefix'] = None
        bmp_result['route_dist'] = None
        bmp_result['vpnv4_prefix'] = None
        bmp_result['nexthop'] = None
        self.bmp_q.put(bmp_result)
        LOG.debug("bmp_result=%s"%bmp_result)

    def print_BMPRouteMonitoring(self, msg, addr):
        if msg.peer_type == bmp.BMP_PEER_TYPE_GLOBAL:
            self.print_global(msg, addr)
        elif msg.peer_type == bmp.BMP_PEER_TYPE_L3VPN:
            self.print_l3vpn(msg, addr)

    def print_global(self, msg, addr):
        if msg.timestamp == 0:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
            if isinstance(msg.bgp_update, bgp.BGPRouteRefresh):
                self.print_BGP_RouteRefresh(bmp_result)
            elif isinstance(msg.bgp_update, bgp.BGPUpdate):
                self.print_BGP_Update(msg, addr, bgp_t)
        else:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                                   time.localtime(int(msg.timestamp)))
            now_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
            time1 = time.mktime(time.localtime(int(msg.timestamp)))
            time2 = time.mktime(time.localtime())
            time_delta = time2 - time1
            if time_delta < 60:
                if isinstance(msg.bgp_update, bgp.BGPRouteRefresh):
                    self.print_BGP_RouteRefresh(msg, addr, bgp_t)
                elif isinstance(msg.bgp_update, bgp.BGPUpdate):
                    self.print_BGP_Update(msg, addr, bgp_t)

    def print_BGP_RouteRefresh(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['event_type'] = "route_refresh"
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['route_dist'] = None
        bmp_result['vpnv4_prefix'] = None
        bmp_result['nexthop'] = None
        self.bmp_q.put(bmp_result)
        LOG.debug("bmp_result=%s"%bmp_result)

    def print_BGP_Update(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        if msg.bgp_update.withdrawn_routes:
            for del_nlri in msg.bgp_update.withdrawn_routes:
                bmp_result['event_type'] = "adj_rib_in_changed(withdraw)"
                bmp_result['prefix'] = del_nlri.prefix
                bmp_result['route_dist'] = None
                bmp_result['vpnv4_prefix'] = None
                bmp_result['nexthop'] = None
                self.bmp_q.put(bmp_result)
                LOG.debug("bmp_result=%s"%bmp_result)
        else:
            for nlri in msg.bgp_update.nlri:
                bmp_result['event_type'] = "adj_rib_in_changed"
                bmp_result['prefix'] = nlri.prefix
                bmp_result['route_dist'] = None
                bmp_result['vpnv4_prefix'] = None
                for data in msg.bgp_update.path_attributes:
                    if isinstance(data, bgp.BGPPathAttributeNextHop):
                        bmp_result['nexthop'] = data.value
                self.bmp_q.put(bmp_result)
                LOG.debug("bmp_result=%s"%bmp_result)

    def print_l3vpn(self, msg, addr):
        bmp_result = {}
        peer_as = msg.peer_as
        peer_bgp_id = msg.peer_bgp_id
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                               time.localtime(int(msg.timestamp)))
        now_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        time1 = time.mktime(time.localtime(int(msg.timestamp)))
        time2 = time.mktime(time.localtime())
        time_delta = time2 - time1
        if time_delta < 60:
            for data in msg.bgp_update.path_attributes:
                bmp_result['received_time'] = bgp_t
                bmp_result['received_host'] = addr[0]
                bmp_result['peer_as'] = peer_as
                bmp_result['peer_bgp_id'] = peer_bgp_id
                if isinstance(data, bgp.BGPPathAttributeMpUnreachNLRI):
                    del_nlri = data.withdrawn_routes[0]
                    bmp_result['event_type'] = "adj_rib_in_changed(withdraw)"
                    bmp_result['prefix'] = del_nlri.prefix
                    bmp_result['route_dist'] = del_nlri.route_dist
                    bmp_result['vpnv4_prefix'] = del_nlri.formatted_nlri_str
                    bmp_result['nexthop'] = None
                    self.bmp_q.put(bmp_result)
                    LOG.debug("bmp_result=%s"%bmp_result)
                elif isinstance(data, bgp.BGPPathAttributeMpReachNLRI):
                    nlri = data.nlri[0]
                    bmp_result['event_type'] = "adj_rib_in_changed"
                    bmp_result['prefix'] = nlri.prefix
                    bmp_result['route_dist'] = nlri.route_dist
                    bmp_result['vpnv4_prefix'] = nlri.formatted_nlri_str
                    bmp_result['nexthop'] = data.next_hop
                    self.bmp_q.put(bmp_result)
                    LOG.debug("bmp_result=%s"%bmp_result)

