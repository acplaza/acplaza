#!/usr/bin/env python

import sys

try:
	baas_path = sys.argv[1]
except IndexError:
	exit('Usage: dump_baas_creds.py <path/to/su/baas/<...>.dat>')

with open(baas_path, 'rb') as f:
	profile_id = int.from_bytes(f.read(8), byteorder='little')
	f.seek(0x20)
	user_id = int.from_bytes(f.read(8), byteorder='little')
	f.seek(0x28)
	password = f.read(0x28).decode('ascii')

print(f"""\
baas-profile-id = 0x{profile_id:x}
baas-user-id = 0x{user_id:x}
baas-password = {password!r}\
""")
