#!/usr/bin/env python

import sys
import asyncpg
from app import app
from utils import pg, encode_token, queries, config

async def main():
	user_id = int(sys.argv[1])
	pg = await asyncpg.connect(**config['postgres-db'])
	secret = await pg.fetchval(queries.secret(), user_id)
	if secret is None:
		sys.exit('Secret not found')
	print(encode_token(user_id, secret))

import anyio
anyio.run(main)
