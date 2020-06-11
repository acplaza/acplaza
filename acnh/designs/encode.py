# © 2020 io mintz <io@mintz.cc>

import io
import itertools
import re
import random
import struct
from dataclasses import dataclass, field
from typing import List, Dict, Type, ClassVar, Tuple, Optional
from http import HTTPStatus

import wand.image
import wand.color
import msgpack

from .api import DesignError
from .. import utils
from .format import PALETTE_SIZE, SIZE as STANDARD, WIDTH as STANDARD_WIDTH, HEIGHT as STANDARD_HEIGHT

class InvalidLayerNameError(DesignError):
	code = 37
	message = 'Invalid image layer name.'
	valid_layer_names: List[str]

	def __init__(self, design):
		self.valid_layer_names = list(design.external_layers)

	def to_dict(self):
		d = super().to_dict()
		d['valid_layer_names'] = self.valid_layer_names
		return d

@dataclass
class Layer:
	name: str
	size: Tuple[int, int]
	# None means "to be filled in later"
	position: int = field(default=None)

	def as_wand(self) -> wand.image.Image:
		im = wand.image.Image(width=self.size[0], height=self.size[1])
		im.background_color = wand.color.Color('rgba(0,0,0,0)')
		return im

	def validate(self, image):
		if image.size != self.size:
			raise InvalidLayerSizeError(self.name)

class Design:
	design_types: ClassVar[Dict[str, Type['Design']]] = {}
	design_type_codes: ClassVar[Dict[int, Type['Design']]] = {}
	type_code: ClassVar[int]
	# the layers that are presented to the user
	external_layers: ClassVar[List[Layer]]
	external_layer_names: ClassVar[Dict[str, Layer]]
	# the layers that are sent to the API
	internal_layers: ClassVar[List[Optional[Layer]]]

	island_name: str
	design_name: str
	layer_images: Dict[str, wand.image.Image]

	def __init_subclass__(cls):
		# CamelCase to kebab-case for the API
		cls.name = re.sub('([a-z0-9])([A-Z])', r'\1-\2', cls.__name__).lower()
		cls.design_types[cls.name] = cls
		cls.design_type_codes[cls.type_code] = cls

		if not hasattr(cls, 'internal_layers'):
			cls.internal_layers = [Layer(str(i), l.size) for i, l in enumerate(cls.external_layers)]

		external_layer_names = cls.external_layer_names = {}
		for i, layer in enumerate(cls.external_layers):
			if layer is not None:
				external_layer_names[layer.name] = layer
				layer.position = i

	def __new__(cls, type=None, **kwargs):
		# this is really two constructors:
		# 1) Design(101) → <class 'acnh.designs.api.ShortSleeveTee'>
		# 2) ShortSleeveTee(island_name='foo', design_name='bar', layers=[...])
		#    -> <acnh.designs.api.ShortSleeveTee object at ...>

		# constructor #1: type object lookup
		if cls is Design:
			if type is None:
				raise TypeError('Design expected 1 positional argument, 0 were passed')

			subcls = [cls.design_types, cls.design_type_codes][isinstance(type, int)][type]
			if not kwargs:
				return subcls
			return subcls(**kwargs)

		# constructor #2: instance variables
		self = object.__new__(cls)
		author_name, island_name, design_name, layers = cls._parse_subclass_init_kwargs(**kwargs)
		self.author_name = author_name
		self.island_name = island_name
		self.design_name = design_name
		self.layer_images = layers
		return self

	@classmethod
	def _parse_subclass_init_kwargs(cls, *, author_name, island_name, design_name, layers):
		return author_name, island_name, design_name, layers

	def internalize(self) -> List[wand.image.Image]:
		return list(self.layer_images.values())

	@classmethod
	def externalize(cls, *, internal_layers: List[wand.image.Image], **kwargs) -> 'Design':
		return cls(
			layers={cls.external_layers[i].name: img for i, img in enumerate(internal_layers)},
			**kwargs,
		)

	def validate(self):
		for layer_name, layer in self.external_layer_names.items():
			try:
				layer.validate(self.layer_images[layer.name])
			except KeyError:
				raise MissingLayerError(layer)

		if len(self.layer_images) > len(self.external_layers):
			raise InvalidLayerNameError(self)

	@property
	def pro(self):
		return len(self.internal_layers) > 1

# layer sizes
SHORT_SLEEVE = (22, 13)
LONG_SLEEVE = (22, 22)
LONG_BODY = (32, 40)

class BasicDesign(Design):
	type_code = 99
	external_layers = [Layer('0', STANDARD)]

class TankTop(Design):
	type_code = 102
	external_layers = [
		Layer('back', STANDARD),
		Layer('front', STANDARD),
	]

class ShortSleeveTee(Design):
	type_code = 101
	external_layers = [
		Layer('back', STANDARD),
		Layer('front', STANDARD),
		Layer('right-sleeve', SHORT_SLEEVE),
		Layer('left-sleeve', SHORT_SLEEVE),
	]

class LongSleeveDressShirt(Design):
	type_code = 100
	external_layers = [
		Layer('back', STANDARD),
		Layer('front', STANDARD),
		Layer('right-sleeve', LONG_SLEEVE),
		Layer('left-sleeve', LONG_SLEEVE),
	]

class Sweater(Design):
	type_code = 103
	external_layers = LongSleeveDressShirt.external_layers

class Hoodie(Design):
	type_code = 104
	# wait where's the hood? lol
	external_layers = Sweater.external_layers

class Coat(Design):
	type_code = 105
	external_layers = [
		Layer('back', LONG_BODY),
		Layer('front', LONG_BODY),
		Layer('right-sleeve', LONG_SLEEVE),
		Layer('left-sleeve', LONG_SLEEVE),
	]

class SleevelessDress(Design):
	type_code = 107
	external_layers = [
		Layer('back', LONG_BODY),
		Layer('front', LONG_BODY),
	]

class ShortSleeveDress(Design):
	type_code = 106
	external_layers = SleevelessDress.external_layers + [
		Layer('right-sleeve', SHORT_SLEEVE),
		Layer('left-sleeve', SHORT_SLEEVE),
	]

class LongSleeveDress(Design):
	type_code = 108
	external_layers = SleevelessDress.external_layers + [
		Layer('right-sleeve', LONG_SLEEVE),
		Layer('left-sleeve', LONG_SLEEVE),
	]

class RoundDress(Design):
	type_code = 110
	external_layers = SleevelessDress.external_layers

class BalloonHemDress(Design):
	type_code = 109
	external_layers = ShortSleeveDress.external_layers

class Robe(Design):
	type_code = 111
	external_layers = LongSleeveDress.external_layers

class BrimmedCap(Design):
	type_code = 112
	external_layers = [
		Layer('front', (44, 41)),
		Layer('back', (20, 44)),
		Layer('brim', (44, 21)),
	]
	internal_layers = [Layer(str(i), STANDARD) for i in range(4)]

	# TODO conversion methods

class KnitCap(Design):
	type_code = 113
	external_layers = [Layer('cap', (64, 53))]
	internal_layers = [
		Layer('0', STANDARD),
		Layer('1', STANDARD),
		# note: these two are officially 32×32, but the game ignores extra pixels after the end of the design
		Layer('2', (32, 21)),
		Layer('3', (32, 21)),
	]

	def internalize(self) -> List[wand.image.Image]:
		img = self.layer_images['cap']
		return [
			img[0:32, 0:32],
			img[32:64, 0:32],
			img[0:32, 32:53],
			img[32:64, 32:53],
		]

	@classmethod
	def externalize(cls, *, internal_layers: List[wand.image.Image], **kwargs) -> 'KnitCap':
		external_layers = {}
		width, height = self.external_layers[0].size
		cap = external_layers['cap'] = wand.image.Image(width=width, height=height)
		cap.composite(internal_layers[0], 0, 0)
		cap.composite(internal_layers[1], 32, 0)
		cap.composite(internal_layers[2], 0, 32)
		cap.composite(internal_layers[3], 32, 32)
		return cls(layers=external_layers, **kwargs)

class BrimmedHat(Design):
	type_code = 114
	external_layers = [
		Layer('top', (36, 36)),
		Layer('middle', (64, 19)),
		Layer('bottom', (64, 9)),
	]
	internal_layers = [Layer(str(i), STANDARD) for i in range(4)]

	def internalize(self) -> List[wand.image.Image]:
		out = list(map(Layer.as_wand, self.internal_layers))

		top, middle, bottom = (self.layer_images[k] for k in ('top', 'middle', 'bottom'))

		out[0].composite(top[0:18, 0:32], 14, 0)
		out[1].composite(top[18:36, 0:32], 0, 0)
		out[2].composite(top[0:18, 32:36], 14, 0)
		out[3].composite(top[18:36, 32:36], 0, 0)

		out[2].composite(middle[0:32, 0:19], 0, 4)
		out[3].composite(middle[32:64, 0:19], 0, 4)

		out[2].composite(bottom[0:32, 0:9], 0, 23)
		out[3].composite(bottom[32:64, 0:9], 0, 23)

		return out

	@classmethod
	def externalize(cls, internal_layers: List[wand.image.Image], **kwargs) -> 'BrimmedHat':
		a, b, c, d = internal_layers
		out = {}
		out['top'], out['middle'], out['bottom'] = map(Layer.as_wand, cls.external_layers)

		out['top'].composite(a[14:32, 0:32], 0, 0)
		out['top'].composite(b[0:18, 0:32], 14, 0)
		out['top'].composite(c[14:32, 0:4], 0, 32)
		out['top'].composite(d[0:18, 0:4], 18, 32)

		out['middle'].composite(c[0:32, 4:22], 0, 0)
		out['middle'].composite(d[32:64, 4:22], 32, 0)

		out['bottom'].composite(d[0:32, 0:9], 0, 0)
		out['bottom'].composite(d[32:64, 0:9], 32, 0)

		return cls(layers=out, **kwargs)

class InvalidLayerError(DesignError):
	layer: Layer
	http_status = HTTPStatus.BAD_REQUEST

	def __init__(self, layer):
		self.layer = layer

	def to_dict(self):
		d = super().to_dict()
		d['layer_name'] = self.layer.name
		d['layer_size'] = self.layer.size
		d['error'] = self.message.format(self)
		return d

class InvalidPaletteError(DesignError):
	code = 27
	message = f'the combined palette of all layers exceed {PALETTE_SIZE} colors'
	http_status = HTTPStatus.BAD_REQUEST

class InvalidLayerSizeError(DesignError):
	code = 28
	message = 'layer "{0.layer.name}" did not meet the expected size ({0.layer.size[0]}×{0.layer.size[1]})'

class MissingLayerError(InvalidLayerError):
	code = 38
	message = 'Payload was missing one or more layers. First missing layer: "{0.layer.name}"'
	http_status = HTTPStatus.BAD_REQUEST

with open('data/net image.jpg', 'rb') as f:
	dummy_net_image = f.read()
with open('data/preview image.jpg', 'rb') as f:
	dummy_preview_image = f.read()

LITTLE_ENDIAN_UINT32 = struct.Struct('>L')
TWO_LITTLE_ENDIAN_UINT32S = struct.Struct('>LL')

DUMMY_EXTRA_METADATA = {
	'mAuthor': {
		'mVId': 4255292630,
		'mPId': 2422107098,
		'mGender': 0,
	},
	'mFlg': 2,
	'mClSet': 238,
}

def tile(image):
	num_v_segments = image.width // STANDARD_WIDTH
	num_h_segments = image.height // STANDARD_HEIGHT
	# y, x so that the images are in row-major order not column-major order,
	# which is how most people expect iamges to be tiled
	for y, x in itertools.product(
		range(0, image.height, STANDARD_HEIGHT),
		range(0, image.width, STANDARD_WIDTH),
	):
		yield image[x:min(image.width, x+STANDARD_WIDTH), y:min(image.height, y+STANDARD_HEIGHT)]

# TODO make this a method of Design
def encode(design: Design) -> dict:
	encoded = {}
	meta = {
		'mMtVNm': design.island_name,
		'mMtDNm': design.design_name,
		'mMtUse': design.type_code,
		'mMtPro': design.pro,
		'mMtNsaId': random.randrange(2**64),
		'mMtVer': 2306,
		'mAppReleaseVersion': 7,
		'mMtVRuby': 2,
		'mMtTag': [0, 0, 0],
		'mMtLang': 'en-US',
		'mPHash': 0,
		'mShareUrl': '',
	}
	encoded['meta'] = msgpack.dumps(meta)

	was_quantized, img_data = [encode_basic, encode_pro][design.pro](design)
	body = {}
	body['mMeta'] = meta
	body['mData'] = img_data
	encoded['body'] = msgpack.dumps(body)
	encoded['net_image'] = dummy_net_image
	encoded['preview_image'] = dummy_preview_image

	return was_quantized, encoded

def encode_basic(design):
	image = design.layer_images['0'].clone()
	if image.size > STANDARD:
		# preserve aspect ratio
		image.transform(resize=f'{STANDARD_WIDTH}x{STANDARD_HEIGHT}')
	if image.size != STANDARD:
		# Due to the ACNH image format not containing size information, all images must be exactly
		# the same size. Otherwise, the image has extra space at the *bottom*, not necessarily on the
		# side, as may be the case with this image.
		base_image = wand.image.Image(width=STANDARD_WIDTH, height=STANDARD_HEIGHT)
		base_image.background_color = wand.color.Color('rgba(0, 0, 0, 0)')
		base_image.sequence.append(image)
		base_image.merge_layers('flatten')
		image = base_image

	was_quantized = maybe_quantize(image)

	with image:
		# casting to a memoryview should ensure efficient slicing
		pxs = memoryview(bytearray(image.export_pixels()))

	return was_quantized, encode_image_data([pxs])

def encode_pro(design):
	design.validate()
	pxss = [memoryview(bytearray(image.export_pixels())) for image in design.internalize()]
	palette = gen_palette(pxss)
	img_data = encode_image_data(pxss)
	return False, img_data

def encode_image_data(pxss: List[bytes]) -> dict:
	palette = gen_palette(pxss)
	layers = {}
	for i, pxs in enumerate(pxss):
		layers[str(i)] = encode_image(palette, pxs)

	img_data = {}
	palette = img_data['mPalette'] = {str(i): color for color, i in palette.items()}
	# implicit transparent
	palette[str(PALETTE_SIZE)] = 0

	img_data['mData'] = layers
	img_data.update(DUMMY_EXTRA_METADATA)

	return img_data

def gen_palette(pxss: List[bytes]) -> Dict[int, int]:
	palette = {}
	color_i = 0
	for pxs in pxss:
		for px in utils.chunked(pxs, 4):
			color, = LITTLE_ENDIAN_UINT32.unpack(px)
			if color not in palette:
				palette[color] = color_i
				color_i += 1

	if len(palette) > PALETTE_SIZE:
		raise InvalidPaletteError

	return palette

def encode_image(palette, pxs):
	img = io.BytesIO()
	for pixels in utils.chunked(pxs, 8):
		px1, px2 = TWO_LITTLE_ENDIAN_UINT32S.unpack_from(pixels)
		img.write((palette[px2] << 4 | palette[px1]).to_bytes(1, byteorder='big'))
	return img.getvalue()

def maybe_quantize(image):
	was_quantized = False
	if image.colors > PALETTE_SIZE:
		image.quantize(number_colors=PALETTE_SIZE)
		was_quantized = True

	if image.colors > PALETTE_SIZE:
		raise RuntimeError(
			f'generated palette has more than {PALETTE_SIZE} colors ({image.colors}) even after quantization!'
		)

	return was_quantized
