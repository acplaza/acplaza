# © 2020 Nick Wanninger, io mintz

# ACNH API is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# ACNH API is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with ACNH API. If not, see <https://www.gnu.org/licenses/>.

import io
from PIL import Image

SIZE = (32, 32)
WIDTH, HEIGHT = SIZE

def render_layers(raw_image):
	palette = {}
	for ind, color in raw_image['mPalette'].items():
		r = (color >> 24) & 0xFF
		g = (color >> 16) & 0xFF
		b = (color >>  8) & 0xFF
		a = (color >>  0) & 0xFF
		palette[int(ind)] = (r, g, b, a)
	# implicit transparent
	palette[0xF] = (0, 0, 0, 0)

	# idk there's probably some python nerd `map` thing you can do here I'm a
	# C programmer so I like the word `for` more than that functional nonsense
	images = {}
	for layer_i, layer in raw_image['mData'].items():
		# create a 32x32 image for this layer
		im = Image.new('RGBA', SIZE)

		# grab them pixels
		pixels = im.load()

		for pixi, byte in zip(range(0, WIDTH * HEIGHT, 2), layer):
			b1 = byte & 0xF
			b2 = (byte >> 4) & 0xF

			# each byte of input supplies two pixels, so use `enumerate` to
			# get an offset so we handle both pixels using one block of code
			# woot! no code duplication!
			for offset, nibble in enumerate([b1, b2]):
				# calculate the x and y using a smarter method than division (1 cycle vs 30)
				# you could divide and mod by HEIGHT-1 here instead, but this is ***FASTER***
				# NOTE: dependent on HEIGHT being a power of two
				x = (pixi + offset) & (HEIGHT - 1)
				y = (pixi + offset) >> 5
				pixels[x, y] = palette[nibble]

		out = io.BytesIO()
		im.save(out, format='PNG')
		out.seek(0)
		im.close()
		yield layer_i, out
