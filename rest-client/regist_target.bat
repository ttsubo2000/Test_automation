#!/bin/sh
#./post_target.sh 65000 192.168.1.0/24 192.168.3.2 192.168.1.1 192.168.10.5 tsubo tsubo1011 cli
#./post_target.sh 65010 65010:101:192.168.201.101/32 192.168.100.1 192.168.201.101 192.168.10.6 tsubo tsubo1011 cli
./post_target.sh 65010 65010:101:192.168.201.101/32 192.168.100.1 192.168.201.101 192.168.0.6 root ryubgp rest
