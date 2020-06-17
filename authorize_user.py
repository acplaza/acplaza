#!/usr/bin/env python3

import secrets
import sys
from app import app
from utils import encode_token, pg, queries

username = sys.argv[1]
with app.app_context():
	secret = secrets.token_bytes()
	user_id = pg().fetchval(queries.authorize_user(), secret, username)
	print(encode_token(user_id, secret))
