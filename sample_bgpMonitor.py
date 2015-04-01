# Copyright (c) 2014-2015 ttsubo
# This software is released under the MIT License.
# http://opensource.org/licenses/mit-license.php

import logging
import socket
import time
import subprocess

from ryu.base import app_manager
from ryu.lib import hub
from ryu.lib.hub import StreamServer
from ryu.lib.packet import bmp
from ryu.lib.packet import bgp

LOG = logging.getLogger('BgpMonitor')
LOG.setLevel(logging.DEBUG)
logging.basicConfig()

HOST = '0.0.0.0'
PORT = 11019
ADDR = (HOST, PORT)


class BgpMonitor(app_manager.RyuApp):
    def __init__(self):
        super(BgpMonitor, self).__init__()

    def start(self):
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
        bmp_result = {}
        if msg.timestamp == 0:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        else:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                                   time.localtime(int(msg.timestamp)))
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['message_type'] = "PeerUpNotification"
        LOG.info("bmp_result=%s"%bmp_result)

    def print_BMPPeerDownNotification(self, msg, addr):
        bmp_result = {}
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['message_type'] = "PeerDownNotification"
        LOG.info("bmp_result=%s"%bmp_result)

    def print_BMPRouteMonitoring(self, msg, addr):
        if msg.timestamp == 0:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        else:
            bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                                   time.localtime(int(msg.timestamp)))
        if isinstance(msg.bgp_update, bgp.BGPRouteRefresh):
            self.extract_BGP_RouteRefresh(msg, addr, bgp_t)
        elif isinstance(msg.bgp_update, bgp.BGPUpdate):
            self.extract_BGP_Update(msg, addr, bgp_t)

    def extract_BGP_RouteRefresh(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['message_type'] = "BGP_RouteRefresh"
        LOG.info("bmp_result=%s"%bmp_result)

    def extract_BGP_Update(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        if msg.bgp_update.withdrawn_routes:
            self.extract_bgp4_withdraw(msg, bmp_result)
        elif msg.bgp_update.nlri:
            self.extract_bgp4_nlri(msg, bmp_result)
        else:
            self.extract_mpbgp(msg, bmp_result)

    def extract_bgp4_withdraw(self, msg, bmp_result):
        nlri_list = []
        bmp_result['message_type'] = "BGP_Update(withdraw)"
        for data in msg.bgp_update.path_attributes:
            if isinstance(data, bgp.BGPPathAttributeNextHop):
                bmp_result['nexthop'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MultiExitDisc'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['Origin'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LocalPref'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['OriginatorId'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['ClusterList'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeCommunities):
                bmp_result['Communities'] = data.value
        for del_nlri in msg.bgp_update.withdrawn_routes:
            nlri = {}
            nlri['prefix'] = del_nlri.prefix
            nlri_list.append(nlri)
        bmp_result['ReachNLRI'] = nlri_list
        LOG.info("bmp_result=%s"%bmp_result)

    def extract_bgp4_nlri(self, msg, bmp_result):
        nlri_list = []
        bmp_result['message_type'] = "BGP_Update"
        for data in msg.bgp_update.path_attributes:
            if isinstance(data, bgp.BGPPathAttributeNextHop):
                bmp_result['nexthop'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MultiExitDisc'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['Origin'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LocalPref'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['OriginatorId'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['ClusterList'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeCommunities):
                bmp_result['Communities'] = data.value
        for add_nlri in msg.bgp_update.nlri:
            nlri = {}
            nlri['prefix'] = add_nlri.prefix
            nlri_list.append(nlri)
        bmp_result['ReachNLRI'] = nlri_list
        LOG.info("bmp_result=%s"%bmp_result)

    def extract_mpbgp(self, msg, bmp_result):
        nlri_list = []
        for data in msg.bgp_update.path_attributes:
            nlri = {}
            if isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MultiExitDisc'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['Origin'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LocalPref'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['OriginatorId'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['ClusterList'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeExtendedCommunities):
                bmp_result['ExtendedCommunities'] = data.rt_list
            elif isinstance(data, bgp.BGPPathAttributeMpUnreachNLRI):
                bmp_result['message_type'] = "BGP_Update(withdraw)"
                for del_nlri in data.withdrawn_routes:
                    nlri['prefix'] = del_nlri.prefix
                    nlri['route_dist'] = del_nlri.route_dist
                    nlri_list.append(nlri)
                bmp_result['MP_UNREACH_NLRI'] = nlri_list
            elif isinstance(data, bgp.BGPPathAttributeMpReachNLRI):
                bmp_result['message_type'] = "BGP_Update"
                for add_nlri in data.nlri:
                    nlri['prefix'] = add_nlri.prefix
                    nlri['route_dist'] = add_nlri.route_dist
                    nlri['label_list'] = add_nlri.label_list
                    nlri['nexthop'] = data.next_hop
                    nlri_list.append(nlri)
                bmp_result['MP_REACH_NLRI'] = nlri_list
        LOG.info("bmp_result=%s"%bmp_result)
