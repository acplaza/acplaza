import ctypes
import PIL.Image
from enum import IntEnum

class ColorFormat(IntEnum):  # from high bits -> low bits, 8 bit per channel
	RGB = 1
	RGBA = 2
	RGBA_UNBUFFERED = 3  # like RGBA, but without the one-time buffer creation overhead (ca. 100 - 300 ms) at the expense of a slightly slower scaling time

SCALE_FACTOR_MAX = 6

xbrz = ctypes.CDLL('./xbrz/xbrz.so')
uint32_p = ctypes.POINTER(ctypes.c_uint32)
xbrz.xbrz_scale_defaults.argtypes = [ctypes.c_size_t, uint32_p, uint32_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
xbrz.xbrz_scale_defaults.restype = None

xbrz.xbrz_rgba_to_argb.argtypes = [uint32_p, ctypes.c_size_t]
xbrz.xbrz_rgba_to_argb.restype = None

xbrz.xbrz_argb_to_rgba.argtypes = [uint32_p, ctypes.c_size_t]
xbrz.xbrz_argb_to_rgba.restype = None

def scale(img, factor, width, height, color_format: ColorFormat):
	"""Scale img, an array of width * height 32 bit ints. Return an array
	of scale * width * scale * height 32 bit ints.
	Scale factor must be in range(2, SCALE_FACTOR_MAX+1).
	"""
	if factor not in range(2, SCALE_FACTOR_MAX + 1):
		raise ValueError('invalid scale factor')

	img = (ctypes.c_uint32 * (width * height)).from_buffer(img)

	scaled = (ctypes.c_uint32 * (factor ** 2 * width * height))()
	xbrz.xbrz_scale_defaults(factor, img, scaled, width, height, color_format)

	return scaled

def scale_pil(img: PIL.Image.Image, factor):
	# Yes, I realize that xBRZ speaks ARGB while PIL only speaks RGBA.
	# However, it seems to work fine without conversion, for some reason??
	scaled = scale(bytearray(img.tobytes()), factor, img.width, img.height, ColorFormat.__members__[img.mode])
	return PIL.Image.frombytes('RGBA', (factor * img.size[0], factor * img.size[1]), scaled)
