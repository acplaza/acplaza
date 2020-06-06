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

from PIL import Image

from .common import ACNHError

class InvalidLayerIndexError(ACNHError):
	code = 31
	message = 'invalid image layer'

	def __init__(self, *, num_layers):
		self.num_layers = num_layers

	def to_dict(self):
		d = super().to_dict()
		d['num_layers'] = self.num_layers

SIZE = (32, 32)
WIDTH, HEIGHT = SIZE

def gen_palette(raw_image):
	palette = {}
	for ind, color in raw_image['mPalette'].items():
		r = (color >> 24) & 0xFF
		g = (color >> 16) & 0xFF
		b = (color >>  8) & 0xFF
		a = (color >>  0) & 0xFF
		palette[int(ind)] = (r, g, b, a)
	# implicit transparent
	palette[0xF] = (0, 0, 0, 0)
	return palette

def _render_layer(raw_image, palette, layer) -> Image.Image:
	palette = gen_palette(raw_image)

	# create a new image for this layer
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

	return im

def render_layer(raw_image, layer_i: int) -> Image.Image:
	try:
		layer = raw_image['mData'][str(layer_i)]
	except KeyError:
		raise InvalidLayerIndexError(num_layers=len(raw_image['mData']))

	return _render_layer(raw_image, gen_palette(raw_image), layer)

def render_layers(raw_image):
	palette = gen_palette(raw_image)
	# idk there's probably some python nerd `map` thing you can do here I'm a
	# C programmer so I like the word `for` more than that functional nonsense
	for layer_i, layer in raw_image['mData'].items():
		yield int(layer_i), _render_layer(raw_image, palette, layer)
