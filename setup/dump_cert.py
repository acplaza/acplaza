#!/usr/bin/env python

# https://github.com/kinnay/NintendoClients/issues/32#issuecomment-1409919863

from nintendo import switch
from anynet import tls
import sys

try:
	# prod.keys
	keys = switch.load_keys(sys.argv[1])
	# PRODINFO.bin
	# get it by opening your rawnand.bin dump from Hekate,
	# then opening it in a tool like HacDiskMount
	prodinfo = switch.ProdInfo(keys, sys.argv[2])
except IndexError:
	exit('Usage: dump_keys.py <path/to/prod.keys> <path/to/PRODINFO.bin>')

prodinfo.get_tls_cert().save('device_cert.pem', tls.TYPE_PEM)
prodinfo.get_tls_key().save('device_cert.key', tls.TYPE_PEM)
