# Used under the following license, thanks to ImRock:

# you can use this code
# :)

# Original: https://gist.github.com/3fab02d25b11fd475513109123258501
# TODO clean-room exorcise this curse

from PIL import Image, ImageDraw
import math
import io
import tarfile_stream

SIZE = (32, 32)
WIDTH, HEIGHT = SIZE

def render_layers(data):
	palette = {}
	for i, c in data['mPalette'].items():
		palette[int(i)] = (c >> 24, c >> 16 & 0xFF, c >> 8 & 0xFF, c & 0xFF)
	palette[15] = (0, 0, 0, 0)

	for i, d in data['mData'].items():
		im = Image.new('RGBA', SIZE, 0)
		pix = im.load()
		pixi = 0
		for b in list(d):
			# the bytes are little endian so the later nybble renders first
			x2, y2 = (pixi % WIDTH), math.floor(pixi / HEIGHT)
			pixi += 1
			x1, y1 = (pixi % WIDTH), math.floor(pixi / HEIGHT)
			pixi += 1

			pix[x1, y1] = palette[b >> 0x4]
			pix[x2, y2] = palette[b & 0xF]

		out = io.BytesIO()
		im.save(out, format='png')
		out.seek(0)
		yield i, out
