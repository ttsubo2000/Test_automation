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

from ryu.lib.packet.bgp import BGP_ATTR_TYPE_ORIGIN
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_AS_PATH
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_NEXT_HOP
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_MULTI_EXIT_DISC
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_LOCAL_PREF
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_COMMUNITIES
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_MP_REACH_NLRI
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_MP_UNREACH_NLRI
from ryu.lib.packet.bgp import BGP_ATTR_TYPE_EXTENDED_COMMUNITIES
from ryu.lib.packet.bgp import BGP_ATTR_ORIGIN_IGP
from ryu.lib.packet.bgp import BGP_ATTR_ORIGIN_EGP
from ryu.lib.packet.bgp import BGP_ATTR_ORIGIN_INCOMPLETE


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
                    self.print_BMP(msg, addr, t)

                required_len = bmp.BMPMessage._HDR_LEN

        self.logger.debug("BMP client disconnected, ip=%s, port=%s", addr[0],
                          addr[1])

        sock.close()

    def print_BMP(self, msg, addr, t):
        if isinstance(msg, bmp.BMPInitiation):
            self.logger.info("%s | %s | BMPInitiation\n", t, addr[0])
        elif isinstance(msg, bmp.BMPPeerUpNotification):
            bmp_result = self.print_BMPPeerUpNotification(msg, addr)
            self.logger.info("%s | %s | %s,%s | BMPPeerUpNotification=%s\n",
                             t, addr[0], msg.peer_as, msg.peer_bgp_id,
                             bmp_result)
        elif isinstance(msg, bmp.BMPRouteMonitoring):
            bmp_result = self.print_BMPRouteMonitoring(msg, addr)
            self.logger.info("%s | %s | %s,%s | BMPRouteMonitoring=%s\n",
                             t, addr[0], msg.peer_as, msg.peer_bgp_id,
                             bmp_result)
        elif isinstance(msg, bmp.BMPPeerDownNotification):
            bmp_result = self.print_BMPPeerDownNotification(msg, addr)
            self.logger.info("%s | %s | %s,%s | BMPPeerDownNotification=%s\n",
                             t, addr[0], msg.peer_as, msg.peer_bgp_id,
                             bmp_result)

    def print_BMPPeerUpNotification(self, msg, addr):
        bmp_result = {}
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S",
                              time.localtime(int(msg.timestamp)))
        bmp_result['received_time'] = bgp_t
        bmp_result['message_type'] = "PeerUpNotification"
        return bmp_result

    def print_BMPPeerDownNotification(self, msg, addr):
        bmp_result = {}
        bgp_t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime())
        bmp_result['received_time'] = bgp_t
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
        bmp_result['message_type'] = "BGP_RouteRefresh"
        return bmp_result

    def extract_BGP_Update(self, msg, addr, bgp_t):
        bmp_result = {}
        bmp_result['received_time'] = bgp_t
        update_msg = msg.bgp_update
        if msg.bgp_update.withdrawn_routes:
            bmp_result = self.extract_bgp4_withdraw(update_msg, bmp_result)
        elif msg.bgp_update.nlri:
            bmp_result = self.extract_bgp4_nlri(update_msg, bmp_result)
        else:
            bmp_result = self.extract_PathAttributes(update_msg, bmp_result)

        return bmp_result

    def extract_bgp4_withdraw(self, update_msg, bmp_result):
        # Path Attributes #
        bmp_result = self.extract_PathAttributes(update_msg, bmp_result)

        # Withdrawn Routes #
        del_nlri_list = []
        for del_nlri in update_msg.withdrawn_routes:
            nlri = {}
            nlri['prefix'] = del_nlri.prefix
            del_nlri_list.append(nlri)
        bmp_result['Withdrawn Routes'] = del_nlri_list
        bmp_result['message_type'] = "BGP_Update(withdraw)"

        return bmp_result

    def extract_bgp4_nlri(self, update_msg, bmp_result):
        # Path Attributes #
        bmp_result = self.extract_PathAttributes(update_msg, bmp_result)

        # NLRI #
        add_nlri_list = []
        for add_nlri in update_msg.nlri:
            nlri = {}
            nlri['prefix'] = add_nlri.prefix
            add_nlri_list.append(nlri)
        bmp_result['NLRI'] = add_nlri_list
        bmp_result['message_type'] = "BGP_Update"

        return bmp_result

    def extract_PathAttributes(self, update_msg, bmp_result):
        path_attributes = {}
        # ORIGIN #
        origin = update_msg.get_path_attr(BGP_ATTR_TYPE_ORIGIN)
        if origin:
            if origin.value == BGP_ATTR_ORIGIN_IGP:
                origin_value = 'i'
            elif origin.value == BGP_ATTR_ORIGIN_EGP:
                origin_value = 'e'
            elif origin.value == BGP_ATTR_ORIGIN_INCOMPLETE:
                origin_value = '?'
            path_attributes['ORIGIN'] = origin_value

        # AS_PATH #
        aspath = update_msg.get_path_attr(BGP_ATTR_TYPE_AS_PATH)
        if aspath:
            path_attributes['AS_PATH'] = aspath.path_seg_list

        # NEXT_HOP #
        nexthop = update_msg.get_path_attr(BGP_ATTR_TYPE_NEXT_HOP)
        if nexthop:
            path_attributes['NEXT_HOP'] = nexthop.value

        # MULTI_EXIT_DISC #
        med = update_msg.get_path_attr(BGP_ATTR_TYPE_MULTI_EXIT_DISC)
        if med:
            path_attributes['MULTI_EXIT_DISC'] = med.value

        # LOCAL_PREF #
        localpref = update_msg.get_path_attr(BGP_ATTR_TYPE_LOCAL_PREF)
        if localpref:
            path_attributes['LOCAL_PREF'] = localpref.value

        # COMMUNITIES #
        communities = update_msg.get_path_attr(BGP_ATTR_TYPE_COMMUNITIES)
        if communities:
            path_attributes['COMMUNITIES'] = communities.value

        # MP_REACH_NLRI #
        mp_reach_nlri_attr = update_msg.get_path_attr(
            BGP_ATTR_TYPE_MP_REACH_NLRI
        )
        if mp_reach_nlri_attr:
            bmp_result['message_type'] = "BGP_Update"
            mp_reach_nlri = {}
            add_nlri_list = []
            for add_nlri in mp_reach_nlri_attr.nlri:
                nlri = {}
                nlri['prefix'] = add_nlri.prefix
                nlri['route_dist'] = add_nlri.route_dist
                nlri['label_list'] = add_nlri.label_list
                add_nlri_list.append(nlri)
            mp_reach_nlri['nexthop'] = mp_reach_nlri_attr.next_hop
            mp_reach_nlri['nlri'] = add_nlri_list
            path_attributes['MP_REACH_NLRI'] = mp_reach_nlri

        # MP_UNREACH_NLRI #
        mp_unreach_nlri_attr = update_msg.get_path_attr(
            BGP_ATTR_TYPE_MP_UNREACH_NLRI
        )
        if mp_unreach_nlri_attr:
            bmp_result['message_type'] = "BGP_Update(withdraw)"
            mp_unreach_nlri = {}
            del_nlri_list = []
            for del_nlri in mp_unreach_nlri_attr.withdrawn_routes:
                nlri = {}
                nlri['prefix'] = del_nlri.prefix
                nlri['route_dist'] = del_nlri.route_dist
                nlri['label_list'] = del_nlri.label_list
                del_nlri_list.append(nlri)
            mp_unreach_nlri['nlri'] = del_nlri_list
            path_attributes['MP_UNREACH_NLRI'] = mp_unreach_nlri

        # EXTENDED_COMMUNITIES #
        extComm = update_msg.get_path_attr(BGP_ATTR_TYPE_EXTENDED_COMMUNITIES)
        if extComm:
            path_attributes['EXTENDED_COMMUNITIES'] = extComm.rt_list

        bmp_result['path_attributes'] = path_attributes
        return bmp_result
