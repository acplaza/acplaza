# © 2020 io mintz <io@mintz.cc>

import contextlib
import datetime as dt
import io
import itertools
import random
import struct
from dataclasses import dataclass, field
from typing import List, Dict, Type, ClassVar, Tuple, Optional, DefaultDict

import wand.image
import wand.color
import msgpack

from .. import utils
from .format import PALETTE_SIZE, SIZE as STANDARD, WIDTH as STANDARD_WIDTH, HEIGHT as STANDARD_HEIGHT
from ..errors import InvalidLayerNameError, MissingLayerError, InvalidPaletteError, InvalidLayerSizeError

XY = Tuple[int, int]

@dataclass
class LayerCorrespondence:
	internal_idx: int
	external_name: str
	internal_pos: XY
	external_pos: XY
	dimensions: XY

class LayerMeta(type):
	def __mul__(cls, x):
		return [cls(str(i), STANDARD) for i in range(x)]

@dataclass
class Layer(metaclass=LayerMeta):
	name: str
	display_name: str = field(init=False)
	size: Tuple[int, int]

	def __post_init__(self):
		self.display_name = self.name.capitalize().replace('-', ' ')

	def as_wand(self) -> wand.image.Image:
		im = wand.image.Image(width=self.size[0], height=self.size[1])
		im.background_color = wand.color.Color('rgba(0,0,0,0)')
		return im

	def validate(self, image):
		if image.size != self.size:
			raise InvalidLayerSizeError(self.name, *self.size)

	@property
	def width(self):
		return self.size[0]

	@property
	def height(self):
		return self.size[1]

NET_IMAGE_BASE = Layer('', (240, 240)).as_wand()

class Design:
	# shared static vars
	design_types: ClassVar[Dict[str, Type['Design']]] = {}
	design_type_codes: ClassVar[Dict[int, Type['Design']]] = {}
	categories: DefaultDict[str, List[Type['Design']]] = DefaultDict(list)

	# per-class static vars
	type_code: ClassVar[int]
	display_name: str
	# the layers that are presented to the user
	external_layers: ClassVar[List[Layer]]
	external_layer_names: ClassVar[Dict[str, Layer]]
	# the layers that are sent to the API
	internal_layers: ClassVar[List[Optional[Layer]]]
	correspondence: ClassVar[Optional[List[LayerCorrespondence]]]
	category: ClassVar[str]

	# instance vars
	author_id: Optional[int]
	author_name: Optional[str]
	island_name: Optional[str]
	design_name: Optional[str]
	created_at: Optional[dt.datetime]
	layer_images: Dict[str, wand.image.Image]

	def __init_subclass__(cls):
		if (
			# if this class doesn't define it
			not hasattr(cls, 'display_name')
			# or it's inherited (XXX this is really gay)
			or any(cls.display_name is getattr(supercls, 'display_name', None) for supercls in cls.__bases__)
		):
			cls.display_name = cls.__name__
		# make it kebab-case for the API
		cls.name = cls.display_name.lower().replace(' ', '-')
		cls.design_types[cls.name] = cls
		cls.design_type_codes[cls.type_code] = cls
		with contextlib.suppress(AttributeError):
			cls.categories[cls.category].append(cls)

		if not hasattr(cls, 'internal_layers'):
			cls.internal_layers = [Layer(str(i), l.size) for i, l in enumerate(cls.external_layers)]

		if not hasattr(cls, 'correspondence'):
			cls.correspondence = None

		cls.external_layer_names = {layer.name: layer for layer in cls.external_layers}

		cls.one_to_one = cls.correspondence is None
		cls.pro = len(cls.internal_layers) > 1

		if cls.pro:
			cls.net_image_mask = wand.image.Image(filename=f'data/net image masks/{cls.name}.png')

	def __new__(cls, type=None, **kwargs):
		# this is really two constructors:
		# 1) Design(101) → <class 'acnh.designs.api.ShortSleeveTee'>
		# 2) ShortSleeveTee(island_name='foo', design_name='bar', layers=[...])
		#    -> <acnh.designs.api.ShortSleeveTee object at ...>

		# constructor #1: type object lookup
		if cls is Design:
			if type is None:
				raise TypeError('Design expected 1 positional argument, 0 were passed')

			try:
				subcls = (cls.design_type_codes if isinstance(type, int) else cls.design_types)[type]
			except KeyError:
				if isinstance(type, int):
					raise ValueError('invalid design type code')
				raise ValueError('invalid design type name')

			if not kwargs:
				return subcls
			return subcls(**kwargs)

		# constructor #2: instance variables
		self = object.__new__(cls)
		author_id, author_name, island_name, design_name, created_at, layers = cls._parse_subclass_init_kwargs(**kwargs)
		self.author_id = author_id
		self.author_name = author_name
		self.island_name = island_name
		self.design_name = design_name
		self.created_at = created_at
		self.layer_images = layers
		return self

	@classmethod
	def _parse_subclass_init_kwargs(
		cls, *, author_id=None, author_name=None, island_name=None, design_name=None, created_at=None, layers
	):
		return author_id, author_name, island_name, design_name, created_at, layers

	@classmethod
	def from_data(cls, data: dict):
		from .render import render_layers  # resolve circular import

		internal_layers = [layer for i, layer in render_layers(data['mData'])]
		type_code = data['mMeta']['mMtUse']
		subcls = cls(type_code)
		return subcls.externalize(
			internal_layers,
			author_id=data['author_id'],
			author_name=data['author_name'],
			island_name=data['mMeta']['mMtVNm'],
			design_name=data['mMeta']['mMtDNm'],
			created_at=dt.datetime.fromtimestamp(data['created_at'], dt.timezone.utc),
		)

	def internalize(self) -> List[wand.image.Image]:
		if self.one_to_one:
			return list(self.layer_images.values())

		out = list(map(Layer.as_wand, self.internal_layers))
		for c in self.correspondence:
			dst = out[c.internal_idx]
			dst_position = c.internal_pos
			src = self.layer_images[c.external_name]
			src_position = c.external_pos
			self.copy(dst, src, dst_position, src_position, c.dimensions)

		return out

	@classmethod
	def externalize(cls, internal_layers: List[wand.image.Image], **kwargs) -> 'Design':
		if cls.one_to_one:
			return cls(
				layers={cls.external_layers[i].name: img for i, img in enumerate(internal_layers)},
				**kwargs,
			)

		out = {layer.name: layer.as_wand() for layer in cls.external_layers}
		for c in cls.correspondence:
			dst = out[c.external_name]
			dst_position = c.external_pos
			src = internal_layers[c.internal_idx]
			src_position = c.internal_pos
			cls.copy(dst, src, dst_position, src_position, c.dimensions)

		return cls(layers=out, **kwargs)

	# pylint: disable=too-many-arguments
	@classmethod
	def copy(cls, dst, src, dst_position, src_position, dimensions):
		width, height = dimensions
		x, y = src_position
		x_slice = slice(x, x + width)
		y_slice = slice(y, y + height)
		dst.composite(src[x_slice, y_slice], *dst_position)

	# pylint: disable=no-self-use
	def net_image(self) -> wand.image.Image:
		...

	def validate(self):
		for layer in self.external_layer_names.values():
			try:
				layer.validate(self.layer_images[layer.name])
			except KeyError:
				raise MissingLayerError(layer)

		if len(self.layer_images) > len(self.external_layers):
			raise InvalidLayerNameError(self)

# layer sizes
SHORT_SLEEVE = (22, 13)
LONG_SLEEVE = (22, 22)
WIDE_SLEEVE = (30, 22)
LONG_BODY = (32, 41)

STANDARD_BODY_LAYERS = [
	Layer('back', STANDARD),
	Layer('front', STANDARD),
]

LONG_BODY_LAYERS = [
	Layer('back', LONG_BODY),
	Layer('front', LONG_BODY),
]

SHORT_SLEEVE_LAYERS = [
	Layer('right-sleeve', SHORT_SLEEVE),
	Layer('left-sleeve', SHORT_SLEEVE),
]

LONG_SLEEVE_LAYERS = [
	Layer('right-sleeve', LONG_SLEEVE),
	Layer('left-sleeve', LONG_SLEEVE),
]

WIDE_SLEEVE_LAYERS = [
	Layer('right-sleeve', WIDE_SLEEVE),
	Layer('left-sleeve', WIDE_SLEEVE),
]

SHORT_SLEEVE_CORRESPONDENCE = [
	LayerCorrespondence(2, 'right-sleeve', (5, 10), (0, 0), SHORT_SLEEVE),
	LayerCorrespondence(3, 'left-sleeve', (5, 10), (0, 0), SHORT_SLEEVE),
]

LONG_SLEEVE_CORRESPONDENCE = [
	LayerCorrespondence(2, 'right-sleeve', (5, 10), (0, 0), LONG_SLEEVE),
	LayerCorrespondence(3, 'left-sleeve', (5, 10), (0, 0), LONG_SLEEVE),
]

WIDE_SLEEVE_CORRESPONDENCE = [
	LayerCorrespondence(2, 'right-sleeve', (1, 10), (0, 0), WIDE_SLEEVE),
	LayerCorrespondence(3, 'left-sleeve', (1, 10), (0, 0), WIDE_SLEEVE),
]

STANDARD_BODY_CORRESPONDENCE = [
	LayerCorrespondence(0, 'back', (0, 0), (0, 0), STANDARD),
	LayerCorrespondence(1, 'front', (0, 0), (0, 0), STANDARD),
]

LONG_BODY_CORRESPONDENCE = [
	LayerCorrespondence(0, 'front', (0, 0), (0, 0), STANDARD),
	LayerCorrespondence(2, 'front', (0, 0), (0, 32), (32, 9)),
	LayerCorrespondence(1, 'back', (0, 0), (0, 0), STANDARD),
	LayerCorrespondence(3, 'back', (0, 0), (0, 32), (32, 9)),
]

class BasicDesign(Design):
	type_code = 99
	display_name = 'Basic design'
	external_layers = Layer * 1

	def net_image(self):
		net_img = self.layer_images['0'].clone()
		net_img.scale(230, 230)
		net_img.border(wand.color.Color('#f3f5e7'), 5, 5)
		return net_img

class StandardBodyMixin:
	def net_image(self):
		net_img = NET_IMAGE_BASE.clone()
		back = self.layer_images['back'].clone()
		back.scale(112, 113)
		net_img.composite(back, 6, 6)
		front = self.layer_images['front'].clone()
		front.scale(113, 113)
		net_img.composite(front, 121, 6)
		return net_img

class TankTop(StandardBodyMixin, Design):
	type_code = 102
	display_name = 'Tank top'
	category = 'Tops'
	external_layers = STANDARD_BODY_LAYERS

	def net_image(self):
		net_img = super().net_image()
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class ShortSleeveMixin:
	def net_image(self):
		net_img = super().net_image()
		right_sleeve = self.layer_images['right-sleeve'].clone()
		right_sleeve.scale(72, 44)
		net_img.composite(right_sleeve, 26, 157)
		left_sleeve = self.layer_images['left-sleeve'].clone()
		left_sleeve.scale(72, 44)
		net_img.composite(left_sleeve, 141, 157)
		return net_img

# multiple inheritance as function composition 😎
class ShortSleeveTee(ShortSleeveMixin, StandardBodyMixin, Design):
	type_code = 101
	display_name = 'Short-sleeve tee'
	category = 'Tops'
	external_layers = STANDARD_BODY_LAYERS + SHORT_SLEEVE_LAYERS
	internal_layers = Layer * 4
	correspondence = STANDARD_BODY_CORRESPONDENCE + SHORT_SLEEVE_CORRESPONDENCE

	def net_image(self):
		net_img = super().net_image()
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class LongSleeveMixin:
	def net_image(self):
		net_img = super().net_image()
		right_sleeve = self.layer_images['right-sleeve'].clone()
		right_sleeve.scale(72, 77)
		net_img.composite(right_sleeve, 26, 157)
		left_sleeve = self.layer_images['left-sleeve'].clone()
		left_sleeve.scale(72, 77)
		net_img.composite(left_sleeve, 141, 157)
		return net_img

class LongSleeveDressShirt(LongSleeveMixin, StandardBodyMixin, Design):
	type_code = 100
	display_name = 'Long-sleeve dress shirt'
	category = 'Tops'
	external_layers = STANDARD_BODY_LAYERS + LONG_SLEEVE_LAYERS
	internal_layers = Layer * 4
	correspondence = STANDARD_BODY_CORRESPONDENCE + LONG_SLEEVE_CORRESPONDENCE

	def net_image(self):
		net_img = super().net_image()
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class Sweater(LongSleeveDressShirt):
	type_code = 103

# wait where's the hood? lol
class Hoodie(LongSleeveDressShirt):
	type_code = 104

class LongBodyMixin:
	def net_image(self):
		net_img = NET_IMAGE_BASE.clone()
		back = self.layer_images['back'].clone()
		back.scale(112, 145)
		net_img.composite(back, 6, 6)
		front = self.layer_images['front'].clone()
		front.scale(113, 145)
		net_img.composite(front, 121, 6)
		return net_img

class SleevelessDress(LongBodyMixin, Design):
	type_code = 107
	display_name = 'Sleeveless dress'
	category = 'Dress-up'
	external_layers = LONG_BODY_LAYERS
	internal_layers = Layer * 4
	correspondence = LONG_BODY_CORRESPONDENCE

	def net_image(self):
		net_img = super().net_image()
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class Coat(LongSleeveMixin, LongBodyMixin, Design):
	type_code = 105
	category = 'Tops'
	external_layers = LONG_BODY_LAYERS + LONG_SLEEVE_LAYERS
	correspondence = LONG_BODY_CORRESPONDENCE + LONG_SLEEVE_CORRESPONDENCE

	def net_image(self):
		net_img = super().net_image()
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class ShortSleeveDress(ShortSleeveMixin, LongBodyMixin, Design):
	type_code = 106
	display_name = 'Short-sleeve dress'
	category = 'Dress-up'
	external_layers = LONG_BODY_LAYERS + SHORT_SLEEVE_LAYERS
	internal_layers = Layer * 4
	correspondence = LONG_BODY_CORRESPONDENCE + SHORT_SLEEVE_CORRESPONDENCE

class LongSleeveDress(Coat):
	type_code = 108
	display_name = 'Long-sleeve dress'
	category = 'Dress-up'

class RoundDress(ShortSleeveDress):
	type_code = 110
	display_name = 'Round dress'

class BalloonHemDress(ShortSleeveDress):
	type_code = 109
	display_name = 'Balloon-hem dress'

class Robe(LongBodyMixin, Design):
	type_code = 111
	category = 'Dress-up'
	external_layers = LONG_BODY_LAYERS + WIDE_SLEEVE_LAYERS
	internal_layers = Layer * 4
	correspondence = LONG_BODY_CORRESPONDENCE + WIDE_SLEEVE_CORRESPONDENCE

	def net_image(self):
		net_img = super().net_image()
		right_sleeve = self.layer_images['right-sleeve'].clone()
		right_sleeve.scale(105, 77)
		net_img.composite(right_sleeve, 10, 157)
		left_sleeve = self.layer_images['left-sleeve'].clone()
		left_sleeve.scale(105, 77)
		net_img.composite(left_sleeve, 125, 157)
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class BrimmedCap(Design):
	type_code = 112
	display_name = 'Brimmed cap'
	category = 'Headwear'
	external_layers = [
		Layer('front', (44, 41)),
		Layer('back', (20, 44)),
		Layer('brim', (44, 21)),
	]
	internal_layers = Layer * 4
	correspondence = [
		LayerCorrespondence(0, 'front', (0, 0), (0, 0), STANDARD),
		LayerCorrespondence(1, 'front', (0, 0), (32, 0), (12, 32)),
		LayerCorrespondence(2, 'front', (0, 0), (0, 32), (32, 9)),
		LayerCorrespondence(3, 'front', (0, 0), (32, 32), (12, 9)),
		LayerCorrespondence(1, 'back', (12, 0), (0, 0), (20, 32)),
		LayerCorrespondence(3, 'back', (12, 0), (0, 32), (20, 12)),
		LayerCorrespondence(2, 'brim', (0, 11), (0, 0), (32, 21)),
		LayerCorrespondence(3, 'brim', (0, 11), (32, 0), (12, 21)),
	]

	def net_image(self) -> wand.image.Image:
		net_img = NET_IMAGE_BASE.clone()
		front = self.layer_images['front'].clone()
		front.scale(151, 146)
		net_img.composite(front, 8, 4)
		brim = self.layer_images['brim'].clone()
		brim.scale(150, 69)
		net_img.composite(brim, 9, 163)
		back = self.layer_images['back'].clone()
		back.scale(66, 147)
		net_img.composite(back, 166, 13)
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class KnitCap(Design):
	type_code = 113
	display_name = 'Knit cap'
	category = 'Headwear'
	external_layers = [Layer('cap', (64, 53))]
	internal_layers = [
		Layer('0', STANDARD),
		Layer('1', STANDARD),
		# note: these two are officially 32×32, but the game ignores extra pixels after the end of the design
		Layer('2', (32, 21)),
		Layer('3', (32, 21)),
	]
	correspondence = [
		LayerCorrespondence(0, 'cap', (0, 0), (0, 0), STANDARD),
		LayerCorrespondence(0, 'cap', (0, 0), (32, 0), STANDARD),
		LayerCorrespondence(0, 'cap', (0, 0), (0, 32), STANDARD),
		LayerCorrespondence(0, 'cap', (0, 0), (32, 32), STANDARD),
	]

	def net_image(self):
		net_img = NET_IMAGE_BASE.clone()
		cap = self.layer_images['cap'].clone()
		cap.scale(228, 182)
		net_img.composite(cap, 6, 10)
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

class BrimmedHat(Design):
	type_code = 114
	display_name = 'Brimmed hat'
	category = 'Headwear'
	external_layers = [
		Layer('top', (36, 36)),
		Layer('middle', (64, 19)),
		Layer('bottom', (64, 9)),
	]
	internal_layers = Layer * 4
	correspondence = [
		LayerCorrespondence(0, 'top', (14, 0), (0, 0), (18, 32)),
		LayerCorrespondence(1, 'top', (0, 0), (18, 0), (18, 32)),
		LayerCorrespondence(2, 'top', (14, 0), (0, 32), (18, 4)),
		LayerCorrespondence(3, 'top', (0, 0), (18, 32), (18, 4)),
		LayerCorrespondence(2, 'middle', (0, 4), (0, 0), (32, 19)),
		LayerCorrespondence(3, 'middle', (0, 4), (32, 0), (32, 19)),
		LayerCorrespondence(2, 'bottom', (0, 23), (0, 0), (32, 9)),
		LayerCorrespondence(3, 'bottom', (0, 23), (32, 0), (32, 9)),
	]

	def net_image(self) -> wand.image.Image:
		net_img = NET_IMAGE_BASE.clone()
		top = self.layer_images['top'].clone()
		top.scale(121, 121)
		net_img.composite(top, 59, 9)
		middle = self.layer_images['middle'].clone()
		middle.scale(228, 62)
		net_img.composite(middle, 6, 138)
		bottom = self.layer_images['bottom'].clone()
		bottom.scale(228, 26)
		net_img.composite(bottom, 6, 206)
		net_img.composite(self.net_image_mask, 0, 0)
		return net_img

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
	encoded['net_image'] = design.net_image().make_blob('JPG')
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
	img_data = encode_image_data(pxss)
	return False, img_data

def encode_image_data(pxss: List[bytes]) -> dict:
	palette = gen_palette(pxss)
	layers = {}
	for i, pxs in enumerate(pxss):
		layers[str(i)] = encode_image(palette, pxs)

	img_data = {}
	palette = img_data['mPalette'] = {str(i): color for color, i in palette.items()}

	img_data['mData'] = layers
	img_data.update(DUMMY_EXTRA_METADATA)

	return img_data

def gen_palette(pxss: List[bytes], *, pro=False) -> Dict[int, int]:
	palette = {}
	color_i = 0
	for pxs in pxss:
		for px in utils.chunked(pxs, 4):
			color, = LITTLE_ENDIAN_UINT32.unpack(px)
			if color not in palette:
				palette[color] = color_i
				color_i += 1

	if pro:
		palette_max = PALETTE_SIZE
	else:
		palette_max = PALETTE_SIZE + 1
		# implicit transparent
		palette[0] = PALETTE_SIZE

	if len(palette) > palette_max:
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
