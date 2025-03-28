#!/usr/bin/env python

import subprocess
import importlib
import asyncio
import sys

async def gen_subprocess(module_name, func_name, in_data):
	p = await asyncio.create_subprocess_exec(
		sys.executable, '-m', 'gen_subprocess', module_name, func_name,
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
	)
	p.stdin.write(in_data)
	await p.stdin.drain()
	async for chunk in p.stdout:
		yield chunk
	stdout, stderr = await p.communicate()
	if stderr and p.returncode:
		raise RuntimeError(stderr.decode('utf-8'))

def main():
	module_name, func_name = sys.argv[1:]
	gen_func = getattr(importlib.import_module(module_name), func_name)
	for x in gen_func():
		sys.stdout.buffer.write(x)

if __name__ == '__main__':
	main()
