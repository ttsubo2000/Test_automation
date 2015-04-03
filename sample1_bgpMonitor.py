# Copyright (C) 2014 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import socket
import time

from ryu.base import app_manager

from ryu.lib import hub
from ryu.lib.hub import StreamServer
from ryu.lib.packet import bmp
from ryu.lib.packet import bgp


class BMPStation(app_manager.RyuApp):
    def __init__(self):
        super(BMPStation, self).__init__()
        self.name = 'bmpstation'
        self.server_host = os.environ.get('RYU_BMP_SERVER_HOST', '0.0.0.0')
        self.server_port = int(os.environ.get('RYU_BMP_SERVER_PORT', 11019))
        output_file = os.environ.get('RYU_BMP_OUTPUT_FILE', 'ryu_bmp.log')
        failed_dump = os.environ.get('RYU_BMP_FAILED_DUMP',
                                     'ryu_bmp_failed.dump')

        self.output_fd = open(output_file, 'w')
        self.failed_dump_fd = open(failed_dump, 'w')

        self.failed_pkt_count = 0

    def start(self):
        super(BMPStation, self).start()
        self.logger.debug("listening on %s:%s", self.server_host,
                          self.server_port)

        return hub.spawn(StreamServer((self.server_host, self.server_port),
                                      self.loop).serve_forever)

    def loop(self, sock, addr):
        self.logger.debug("BMP client connected, ip=%s, port=%s", addr[0],
                          addr[1])
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
                    self.logger.error("unsupported bmp version: %d", version)
                    is_active = False
                    break

                required_len = len_
                if len(buf) < required_len:
                    break

                try:
                    msg, rest = bmp.BMPMessage.parser(buf)
                except Exception, e:
                    pkt = buf[:len_]
                    self.failed_dump_fd.write(pkt)
                    self.failed_dump_fd.flush()
                    buf = buf[len_:]
                    self.failed_pkt_count += 1
                    self.logger.error("failed to parse: %s"
                                      " (total fail count: %d)",
                                      e, self.failed_pkt_count)
                else:
                    t = time.strftime("%Y %b %d %H:%M:%S", time.localtime())
                    self.logger.debug("%s | %s | %s\n", t, addr[0], msg)
                    self.output_fd.write("%s | %s | %s\n\n" % (t, addr[0],
                                                               msg))
                    self.output_fd.flush()
                    buf = rest

                    if isinstance(msg, bmp.BMPInitiation):
                        self.logger.info("Start BMP session!! [%s]"%addr[0])
                    elif isinstance(msg, bmp.BMPPeerUpNotification):
                        result = self.print_BMPPeerUpNotification(msg, addr)
                        self.logger.info("%s | BMPPeerUpNotification = %s\n",
                                         t, result)
                    elif isinstance(msg, bmp.BMPRouteMonitoring):
                        result = self.print_BMPRouteMonitoring(msg, addr)
                        self.logger.info("%s | BMPRouteMonitoring = %s\n",
                                         t, result)
                    elif isinstance(msg, bmp.BMPPeerDownNotification):
                        result = self.print_BMPPeerDownNotification(msg, addr)
                        self.logger.info("%s | BMPPeerDownNotification = %s\n",
                                         t, result)

                required_len = bmp.BMPMessage._HDR_LEN

        self.logger.debug("BMP client disconnected, ip=%s, port=%s", addr[0],
                          addr[1])

        sock.close()


    def print_BMPPeerUpNotification(self, msg, addr):
        bmp_result = {}
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                              time.localtime(int(msg.timestamp)))
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['peer_type'] = msg.peer_type
        bmp_result['message_type'] = "PeerUpNotification"
        return bmp_result

    def print_BMPPeerDownNotification(self, msg, addr):
        bmp_result = {}
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['peer_type'] = msg.peer_type
        bmp_result['message_type'] = "PeerDownNotification"
        return bmp_result

    def print_BMPRouteMonitoring(self, msg, addr):
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                              time.localtime(int(msg.timestamp)))
        if isinstance(msg.bgp_update, bgp.BGPRouteRefresh):
            result = self.extract_BGP_RouteRefresh(msg, addr, bgp_t)
        elif isinstance(msg.bgp_update, bgp.BGPUpdate):
            result = self.extract_BGP_Update(msg, addr, bgp_t)
        return result

    def extract_BGP_RouteRefresh(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['peer_type'] = msg.peer_type
        bmp_result['message_type'] = "BGP_RouteRefresh"
        return bmp_result

    def extract_BGP_Update(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        bmp_result['received_host'] = addr[0]
        bmp_result['peer_as'] = msg.peer_as
        bmp_result['peer_bgp_id'] = msg.peer_bgp_id
        bmp_result['peer_type'] = msg.peer_type
        if msg.bgp_update.withdrawn_routes:
            result = self.extract_bgp4_withdraw(msg, bmp_result)
        elif msg.bgp_update.nlri:
            result = self.extract_bgp4_nlri(msg, bmp_result)
        else:
            result = self.extract_mpbgp(msg, bmp_result)
        return result

    def extract_bgp4_withdraw(self, msg, bmp_result):
        nlri_list = []
        bmp_result['message_type'] = "BGP_Update(withdraw)"
        for data in msg.bgp_update.path_attributes:
            if isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MULTI_EXIT_DISC'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeAsPath):
                bmp_result['AS_PATH'] = data.path_seg_list
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['ORIGIN'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LOCAL_PREF'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['ORIGINATOR_ID'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['CLUSTER_LIST'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeCommunities):
                bmp_result['COMMUNITIES'] = data.value
        for del_nlri in msg.bgp_update.withdrawn_routes:
            nlri = {}
            nlri['prefix'] = del_nlri.prefix
            nlri_list.append(nlri)
        bmp_result['Withdrawn Routes'] = nlri_list
        return bmp_result

    def extract_bgp4_nlri(self, msg, bmp_result):
        nlri_list = []
        bmp_result['message_type'] = "BGP_Update"
        for data in msg.bgp_update.path_attributes:
            if isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MULTI_EXIT_DISC'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeAsPath):
                bmp_result['AS_PATH'] = data.path_seg_list
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['ORIGIN'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LOCAL_PREF'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['ORIGINATOR_ID'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['CLUSTER_LIST'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeCommunities):
                bmp_result['COMMUNITIES'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeNextHop):
                bmp_result['NEXT_HOP'] = data.value
        for add_nlri in msg.bgp_update.nlri:
            nlri = {}
            nlri['prefix'] = add_nlri.prefix
            nlri_list.append(nlri)
        bmp_result['NLRI'] = nlri_list
        return bmp_result

    def extract_mpbgp(self, msg, bmp_result):
        for data in msg.bgp_update.path_attributes:
            if isinstance(data, bgp.BGPPathAttributeMultiExitDisc):
                bmp_result['MULTI_EXIT_DISC'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeAsPath):
                bmp_result['AS_PATH'] = data.path_seg_list
            elif isinstance(data, bgp.BGPPathAttributeOrigin):
                bmp_result['ORIGIN'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeLocalPref):
                bmp_result['LOCAL_PREF'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeOriginatorId):
                bmp_result['ORIGINATOR_ID'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeClusterList):
                bmp_result['CLUSTER_LIST'] = data.value
            elif isinstance(data, bgp.BGPPathAttributeExtendedCommunities):
                bmp_result['EXTENDED_COMMUNITIES'] = data.rt_list
            elif isinstance(data, bgp.BGPPathAttributeMpReachNLRI):
                bmp_result['message_type'] = "BGP_Update"
                mp_reach_nlri = {}
                add_nlri_list = []
                for add_nlri in data.nlri:
                    nlri = {}
                    nlri['prefix'] = add_nlri.prefix
                    nlri['route_dist'] = add_nlri.route_dist
                    nlri['label_list'] = add_nlri.label_list
                    add_nlri_list.append(nlri)
                mp_reach_nlri['nexthop'] = data.next_hop
                mp_reach_nlri['nlri'] = add_nlri_list
                bmp_result['MP_REACH_NLRI'] = mp_reach_nlri
            elif isinstance(data, bgp.BGPPathAttributeMpUnreachNLRI):
                bmp_result['message_type'] = "BGP_Update(withdraw)"
                mp_unreach_nlri = {}
                del_nlri_list = []
                for del_nlri in data.withdrawn_routes:
                    nlri = {}
                    nlri['prefix'] = del_nlri.prefix
                    nlri['route_dist'] = del_nlri.route_dist
                    nlri['label_list'] = del_nlri.label_list
                    del_nlri_list.append(nlri)
                mp_unreach_nlri['nlri'] = del_nlri_list
                bmp_result['MP_UNREACH_NLRI'] = mp_unreach_nlri

        return bmp_result
