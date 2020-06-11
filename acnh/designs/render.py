# © 2020 io mintz
# Based on code provided by Nick Wanninger, however io mintz retains all copyright ownership.

import io
import wand.image

from ..common import ACNHError
from .format import WIDTH, HEIGHT

class InvalidLayerIndexError(ACNHError):
	code = 31
	message = 'invalid image layer'

	def __init__(self, *, num_layers):
		self.num_layers = num_layers

	def to_dict(self):
		d = super().to_dict()
		d['num_layers'] = self.num_layers

def gen_palette(raw_image):
	palette = {}
	for ind, color in raw_image['mPalette'].items():
		palette[int(ind)] = color
	# implicit transparent
	palette[0xF] = 0
	return palette

def _render_layer(raw_image, palette, layer) -> wand.image.Image:
	palette = gen_palette(raw_image)

	im = wand.image.Image(width=STANDARD_WIDTH, height=STANDARD_HEIGHT)

	out = io.BytesIO()

	for pixi, byte in zip(range(0, STANDARD_WIDTH * STANDARD_HEIGHT, 2), layer):
		b1 = byte & 0xF
		b2 = (byte >> 4) & 0xF

		for nibble in b1, b2:
			out.write(palette[nibble].to_bytes(4, byteorder='big'))

	out.seek(0)
	im.import_pixels(channel_map='RGBA', data=out.getbuffer())
	return im

def render_layer(raw_image, layer_i: int) -> wand.image.Image:
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
