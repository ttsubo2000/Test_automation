# Copyright (c) 2014-2015 ttsubo
# This software is released under the MIT License.
# http://opensource.org/licenses/mit-license.php

import json
import logging
import datetime
import time
import getpass
import paramiko
import telnetlib

from bgpMonitor import BgpMonitor
from webob import Response
from httplib import HTTPConnection
from ryu.base import app_manager
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.lib import hub

LOG = logging.getLogger('TestAutomation')
LOG.setLevel(logging.INFO)

PING_OK = "5 received, 0% packet loss"
PING_NG = "0 received, 100% packet loss"

class TargetTable(object):
    def __init__(self, peer_as, ping_srcip, ping_destip, ssh_host, ssh_user,
                 ssh_pass, show_type):
        self.targetInfo = {}
        self.targetInfo['peer_as'] = peer_as
        self.targetInfo['ping_srcip'] = ping_srcip
        self.targetInfo['ping_destip'] = ping_destip
        self.targetInfo['ssh_host'] = ssh_host
        self.targetInfo['ssh_user'] = ssh_user
        self.targetInfo['ssh_pass'] = ssh_pass
        self.targetInfo['show_type'] = show_type

    def get_all(self):
        return self.targetInfo

class EventResult(object):
    def __init__(self, received_time, peer_bgp_id, event_type, peer_as,
                 vpnv4_prefix, nexthop, event_time, event_id):
        self.EventResult = {}
        self.EventResult['received_time'] = received_time
        self.EventResult['peer_bgp_id'] = peer_bgp_id
        self.EventResult['event_type'] = event_type
        self.EventResult['peer_as'] = peer_as
        self.EventResult['vpnv4_prefix'] = vpnv4_prefix
        self.EventResult['nexthop'] = nexthop
        self.EventResult['event_time'] = event_time
        self.EventResult['event_id'] = str(event_id)

    def add_ping_recv(self, ping_recv):
        self.EventResult['ping_recv'] = ping_recv

    def add_ping_result(self, ping_result):
        self.EventResult['ping_result'] = ping_result

    def add_show_neighbor_result(self, show_neighbor_result):
        self.EventResult['show_neighbor_result'] = show_neighbor_result

    def add_show_rib_result(self, show_rib_result):
        self.EventResult['show_rib_result'] = show_rib_result

    @property
    def event_time(self):
        return self.EventResult['event_time']

    @property
    def event_type(self):
        return self.EventResult['event_type']


    def get_all(self):
        return self.EventResult

class TestAutomation(app_manager.RyuApp):
    _CONTEXTS = {
        'bmp' : BgpMonitor,
        'wsgi': WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        super(TestAutomation, self).__init__(*args, **kwargs)
        self.bmp = kwargs['bmp']
        wsgi = kwargs['wsgi']
        wsgi.register(TestController, {'TestAutomation' : self})
        self.bmp_thread = hub.spawn(self.lookup_bmp_result)
        self.ping_thread = hub.spawn(self.loop_ping)
        self.show_thread = hub.spawn(self.loop_show)
        self.targetInfoList = {}
        self.eventList = {}
        self.ping_target_q = hub.Queue()
        self.show_target_q = hub.Queue()
        self.test_result = open("Test_result.txt", 'w')

    def regist_pingTarget(self, peer_as, vpnv4_prefix, ping_srcip, ping_destip,
                          ssh_host, ssh_user, ssh_pass, show_type):
        self.targetInfoList[vpnv4_prefix] = TargetTable(peer_as, ping_srcip,
                                                        ping_destip, ssh_host,
                                                        ssh_user, ssh_pass, show_type)
    def show_eventDetail(self, search_event_id=0):
        if search_event_id == 0:
            eventResult = max(self.eventList.items())[1]
            LOG.info("match_event_id=[%s]"%max(self.eventList.items())[0])
            search_info = eventResult.get_all()
        else:
            for event_id, eventResult in self.eventList.items():
                if str(event_id) == search_event_id:
                    search_info = eventResult.get_all()
                    break
        return search_info

    def lookup_bmp_result(self):
        event_id = 0
        while True:
            if not self.bmp.bmp_q.empty():
                bmp_result = self.bmp.bmp_q.get()
                LOG.debug("bmp_result=[%s]"%bmp_result)
                if bmp_result['vpnv4_prefix'] == None:
                    target_prefix = bmp_result['prefix']
                else:
                    target_prefix = bmp_result['vpnv4_prefix']

                for vpnv4_prefix, target in self.targetInfoList.items():
                    if vpnv4_prefix == target_prefix:
                        target_info = target.get_all()
                        if target_info['peer_as'] == str(bmp_result['peer_as']):
                            buf_info1 = []
                            buf_info2 = []
                            event_id += 1
                            buf_info1.append(event_id)
                            buf_info1.append(target_info)
                            self.ping_target_q.put(buf_info1)
                            buf_info2.append(event_id)
                            buf_info2.append(bmp_result)
                            buf_info2.append(target_info['show_type'])
                            self.show_target_q.put(buf_info2)
                            event_time = time.strftime("%Y/%m/%d %H:%M:%S",
                                                       time.localtime())
                            self.eventList[event_id] = EventResult(
                                                   bmp_result['received_time'],
                                                   bmp_result['peer_bgp_id'],
                                                   bmp_result['event_type'],
                                                   bmp_result['peer_as'],
                                                   bmp_result['vpnv4_prefix'],
                                                   bmp_result['nexthop'],
                                                   event_time,
                                                   event_id)
                            LOG.debug("eventList=[%s]"%self.eventList[event_id].get_all())
            hub.sleep(1)

    def loop_ping(self):
        port = 22
        while True:
            buf_info = []
            if not self.ping_target_q.empty():
                buf_info = self.ping_target_q.get()
                event_id = buf_info[0]
                target_info = buf_info[1]
                username = target_info['ssh_user']
                password = target_info['ssh_pass']
                ipaddress = target_info['ssh_host']
                srcip = target_info['ping_srcip']
                destip = target_info['ping_destip']
                ping_cmd = "ping -c 5 " + destip + " -I " + srcip

                tp = paramiko.Transport((ipaddress, int(port)))

                try:
                    tp.connect(username=username, password=password,
                               hostkey=None)
                except:
                    tp.close()
                    raise SystemExit("Bad username or password.")
                ch = tp.open_channel("session")
                ch.exec_command(ping_cmd)
                ping_recv = None
                ping_result = None

                while not ch.closed:
                    if ch.recv_stderr_ready:
                        ping_recv = ch.recv_stderr(1024)
                        ping_result = "internal test error"
                    if ch.recv_ready:
                        ping_recv = ch.recv(1024)
                        ping_recv = "$ " + ping_cmd + '\n' + ping_recv
                        if (PING_OK in ping_recv):
                            ping_result = "OK"
                        elif (PING_NG in ping_recv):
                            ping_result = "NG"
                        else:
                            ping_result = "??"
                        LOG.info(ping_recv)
                        self.eventList[event_id].add_ping_recv(ping_recv)
                        self.eventList[event_id].add_ping_result(ping_result)
                        event_time = self.eventList[event_id].event_time
                        event_type = self.eventList[event_id].event_type
                        output = "%s [%s] [%s] [%s]\n"%(event_time, event_id,
                                  ping_result, event_type)
                        self.test_result.write(output)
                        self.test_result.flush()
                        LOG.info("EventResult: [%s]"%output)
                        tp.close()
            hub.sleep(1)

    def loop_show(self):
        while True:
            if not self.show_target_q.empty():
                buf_info = self.show_target_q.get()
                event_id = buf_info[0]
                bmp_result = buf_info[1]
                show_type = buf_info[2]
                target_host = bmp_result['received_host']
                neighbor_address = bmp_result['nexthop']
                if neighbor_address:
                    self.show_neighbor(show_type, target_host, neighbor_address,                    event_id)
                else:
                    self.eventList[event_id].add_show_neighbor_result("N/A")
                    
                self.show_rib(show_type, target_host, event_id)
            hub.sleep(1)

    def show_neighbor(self, show_type, target_host, neighbor_address, event_id):
        if show_type == "rest":
            show_cmd = "bgpd> show neighbor received-routes " + \
                       neighbor_address + " all\n" 
            show_neighbor_result = self.rest_get_neighbor(target_host,
                                                          neighbor_address)
            show_neighbor_result = show_cmd + show_neighbor_result
        elif show_type == "cli":
            show_neighbor_result = self.cli_get_neighbor(target_host,
                                                         neighbor_address)
        else:
            show_neighbor_result = "N/A"

        LOG.info("------------------")
        LOG.info(show_neighbor_result)
        LOG.info("------------------")
        self.eventList[event_id].add_show_neighbor_result(show_neighbor_result)

    def show_rib(self, show_type, target_host, event_id):
        if show_type == "rest":
            show_cmd = "bgpd> show rib vpnv4\n" 
            show_rib_result = self.rest_get_rib(target_host)
            show_rib_result = show_cmd + show_rib_result
        elif show_type == "cli":
            show_rib_result = self.cli_get_rib(target_host)
        else:
            show_rib_result = "N/A"

        LOG.info("------------------")
        LOG.info(show_rib_result)
        LOG.info("------------------")
        self.eventList[event_id].add_show_rib_result(show_rib_result)

    def rest_get_neighbor(self, rest_host, address):
        dpid = "0000000000000001"
        operation = "get_neighbor"
        url_path = "/openflow/" + dpid + "/neighbor"
        method = "GET"
        request = {}
        param = {}

        routetype = "received-routes"
        param["routetype"] = routetype
        param["address"] = address
        request["neighbor"] = param
        neighbor_result = self.request_info(operation, url_path, method,
                                            str(request), rest_host)
        result = neighbor_result['neighbor']
        return result

    def cli_get_neighbor(self, cli_host, address):
        return "N/A"

    def rest_get_rib(self, rest_host):
        dpid = "0000000000000001"
        operation = "get_rib"
        url_path = "/openflow/" + dpid + "/rib"
        method = "GET"

        rib_result = self.request_info(operation, url_path, method, "",
                                       rest_host)
        result = rib_result['rib']
        return result

    def cli_get_rib(self, cli_host):
        session = telnetlib.Telnet(cli_host)
        cli_content = "show bgp vpnv4 unicast all\n"
        session.write(cli_content)
        session.write("exit\n")
        return session.read_all()

    def request_info(self, operator, url_path, method, request, host):
        port = "8080"
        LOG.info("=" *70)
        LOG.info("%s" % operator)
        LOG.info("=" *70)
        session = HTTPConnection("%s:%s" % (host, port))

        header = {
            "Content-Type": "application/json"
            }
        if method == "GET":
            if request:
                LOG.info(url_path)
                LOG.info(request)
                session.request("GET", url_path, request, header)
            else:
                LOG.info(url_path)
                session.request("GET", url_path, "", header)
        session.set_debuglevel(4)
        LOG.info("----------")
        return json.load(session.getresponse())


class TestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(TestController, self).__init__(req, link, data, **config)
        self.test_spp = data['TestAutomation']

    @route('router', '/apgw/test', methods=['POST'])
    def test_ping(self, req, **kwargs):
        pingTarget_param = eval(req.body)
        result = self.pingTarget(pingTarget_param)
        message = json.dumps(result)
        return Response(status=200,
                        content_type = 'application/json',
                        body = message)

    @route('router', '/apgw/event', methods=['POST'])
    def show_event(self, req, **kwargs):
        event_param = eval(req.body)

        result = self.showEvent(event_param)
        message = json.dumps(result)
        return Response(status=200,
                        content_type = 'application/json',
                        body = message)

    @route('router', '/apgw/event/latest', methods=['GET'])
    def show_event_latest(self, req, **kwargs):
        result = self.showEventLatest()
        message = json.dumps(result)
        return Response(status=200,
                        content_type = 'application/json',
                        body = message)

    def pingTarget(self, pingTarget_param):
        testCtrl = self.test_spp
        peer_as = pingTarget_param['target']['peer_as']
        vpnv4_prefix = pingTarget_param['target']['vpnv4_prefix']
        ping_srcip = pingTarget_param['target']['ping_srcip']
        ping_destip = pingTarget_param['target']['ping_destip']
        ssh_host = pingTarget_param['target']['ssh_host']
        ssh_user = pingTarget_param['target']['ssh_user']
        ssh_pass = pingTarget_param['target']['ssh_pass']
        show_type = pingTarget_param['target']['show_type']
        testCtrl.regist_pingTarget(peer_as, vpnv4_prefix, ping_srcip,
                                   ping_destip, ssh_host, ssh_user, ssh_pass, show_type)
        return {
            'target': {
                'peer_as': '%s' % peer_as,
                'vpnv4_prefix': '%s' % vpnv4_prefix,
                'ping_srcip': '%s' % ping_srcip,
                'ping_destip': '%s' % ping_destip,
                'ssh_host': '%s' % ssh_host,
                'ssh_user': '%s' % ssh_user,
                'ssh_pass': '%s' % ssh_pass,
                'show_type': '%s' % show_type,
            }
        }

    def showEvent(self, event_param):
        testCtrl = self.test_spp
        event_id = event_param['event']['event_id']
        search_info = testCtrl.show_eventDetail(event_id)

        if search_info:
            event_id = search_info['event_id']
            event_time = search_info['event_time']
            event_type = search_info['event_type']
            peer_bgp_id = search_info['peer_bgp_id']
            peer_as = search_info['peer_as']
            received_time = search_info['received_time']
            vpnv4_prefix = search_info['vpnv4_prefix']
            nexthop = search_info['nexthop']
            ping_result = search_info['ping_result']
            ping_recv = search_info['ping_recv']
            show_neighbor_result = search_info['show_neighbor_result']
            show_rib_result = search_info['show_rib_result']

            return {
                'event': {
                    'event_id': '%s' % event_id,
                    'event_time': '%s' % event_time,
                    'event_type': '%s' % event_type,
                    'peer_bgp_id': '%s' % peer_bgp_id,
                    'peer_as': '%s' % peer_as,
                    'received_time': '%s' % received_time,
                    'vpnv4_prefix': '%s' % vpnv4_prefix,
                    'nexthop': '%s' % nexthop,
                    'ping_result': '%s' % ping_result,
                    'ping_recv': '%s' % ping_recv,
                    'show_neighbor_result': '%s' % show_neighbor_result,
                    'show_rib_result': '%s' % show_rib_result,
                }
            }


    def showEventLatest(self):
        testCtrl = self.test_spp
        search_info = testCtrl.show_eventDetail()

        if search_info:
            event_id = search_info['event_id']
            event_time = search_info['event_time']
            event_type = search_info['event_type']
            peer_bgp_id = search_info['peer_bgp_id']
            peer_as = search_info['peer_as']
            received_time = search_info['received_time']
            vpnv4_prefix = search_info['vpnv4_prefix']
            nexthop = search_info['nexthop']
            ping_result = search_info['ping_result']
            ping_recv = search_info['ping_recv']
            show_neighbor_result = search_info['show_neighbor_result']
            show_rib_result = search_info['show_rib_result']

            return {
                'event': {
                    'event_id': '%s' % event_id,
                    'event_time': '%s' % event_time,
                    'event_type': '%s' % event_type,
                    'peer_bgp_id': '%s' % peer_bgp_id,
                    'peer_as': '%s' % peer_as,
                    'received_time': '%s' % received_time,
                    'vpnv4_prefix': '%s' % vpnv4_prefix,
                    'nexthop': '%s' % nexthop,
                    'ping_result': '%s' % ping_result,
                    'ping_recv': '%s' % ping_recv,
                    'show_neighbor_result': '%s' % show_neighbor_result,
                    'show_rib_result': '%s' % show_rib_result,
                }
            }
