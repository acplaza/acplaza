#!/usr/bin/env python3

import sys

from app import app
from utils import pg, encode_token, queries

with app.app_context():
	user_id = int(sys.argv[1])
	secret = pg().fetchval(queries.secret(), user_id)
	if secret is None:
		print('Secret not found', file=sys.stderr)
		sys.exit(1)
	print(encode_token(user_id, secret))

