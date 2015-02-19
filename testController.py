# Copyright (c) 2014-2015 ttsubo
# This software is released under the MIT License.
# http://opensource.org/licenses/mit-license.php

import sys
import json
import logging
import datetime
import time
import getpass
import paramiko

from ryu.base import app_manager
from bgpMonitor import BgpMonitor
from webob import Response
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.lib import hub

LOG = logging.getLogger('TestAutomation')
LOG.setLevel(logging.DEBUG)


class TargetTable(object):
    def __init__(self, peer_as, ping_srcip, ping_destip, ssh_host, ssh_user, ssh_pass):
        self.targetInfo = {}
        self.targetInfo['peer_as'] = peer_as
        self.targetInfo['ping_srcip'] = ping_srcip
        self.targetInfo['ping_destip'] = ping_destip
        self.targetInfo['ssh_host'] = ssh_host
        self.targetInfo['ssh_user'] = ssh_user
        self.targetInfo['ssh_pass'] = ssh_pass

    def get_all(self):
        return self.targetInfo


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
        self.targetInfoList = {}
        self.target_q = hub.Queue()

    def regist_pingTarget(self, peer_as, vpnv4_prefix, ping_srcip, ping_destip,
                          ssh_host, ssh_user, ssh_pass):
        self.targetInfoList[vpnv4_prefix] = TargetTable(peer_as, ping_srcip,
                                                        ping_destip, ssh_host,
                                                        ssh_user, ssh_pass)

    def lookup_bmp_result(self):
        while True:
            if not self.bmp.bmp_q.empty():
                bmp_result = self.bmp.bmp_q.get()
                LOG.debug("bmp_result=%s"%bmp_result)
                for vpnv4_prefix, target in self.targetInfoList.items():
                    if vpnv4_prefix == bmp_result['vpnv4_prefix']:
                        target_info = target.get_all()
                        if target_info['peer_as'] == str(bmp_result['peer_as']):
                            self.target_q.put(target_info)
            hub.sleep(1)

    def loop_ping(self):
        port = 22
        while True:
            if not self.target_q.empty():
                target_info = self.target_q.get()
                username = target_info['ssh_user']
                password = target_info['ssh_pass']
                ipaddress = target_info['ssh_host']
                srcip = target_info['ping_srcip']
                destip = target_info['ping_destip']
                command = "ping -c 5 " + destip + " -I " + srcip

                tp = paramiko.Transport((ipaddress, int(port)))

                try:
                    tp.connect(username=username, password=password,
                               hostkey=None)
                except:
                    tp.close()
                    raise SystemExit("Bad username or password.")
                ch = tp.open_channel("session")
                ch.exec_command(command)

                while not ch.closed:
                    if ch.recv_stderr_ready:
                        LOG.info(ch.recv_stderr(1024))
                    if ch.recv_ready:
                        LOG.info(ch.recv(1024))
            hub.sleep(1)


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

    def pingTarget(self, pingTarget_param):
        testCtrl = self.test_spp
        peer_as = pingTarget_param['target']['peer_as']
        vpnv4_prefix = pingTarget_param['target']['vpnv4_prefix']
        ping_srcip = pingTarget_param['target']['ping_srcip']
        ping_destip = pingTarget_param['target']['ping_destip']
        ssh_host = pingTarget_param['target']['ssh_host']
        ssh_user = pingTarget_param['target']['ssh_user']
        ssh_pass = pingTarget_param['target']['ssh_pass']
        testCtrl.regist_pingTarget(peer_as, vpnv4_prefix, ping_srcip,
                                   ping_destip, ssh_host, ssh_user, ssh_pass)
        return {
            'target': {
                'peer_as': '%s' % peer_as,
                'vpnv4_prefix': '%s' % vpnv4_prefix,
                'ping_srcip': '%s' % ping_srcip,
                'ping_destip': '%s' % ping_destip,
                'ssh_host': '%s' % ssh_host,
                'ssh_user': '%s' % ssh_user,
                'ssh_pass': '%s' % ssh_pass,
            }
        }
