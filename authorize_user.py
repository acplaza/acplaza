#!/usr/bin/env python

import secrets
import sys
import asyncpg
from quart import current_app
from utils import config, encode_token, queries

async def main():
	username = sys.argv[1]
	secret = secrets.token_bytes()
	pg = await asyncpg.connect(**config['postgres-db'])
	user_id = await pg.fetchval(queries.authorize_user(), secret, username)
	print(encode_token(user_id, secret))

import anyio
anyio.run(main)
