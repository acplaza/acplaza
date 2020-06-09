# © 2020 io mintz <io@mintz.cc>

# xbrz.py is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# xbrz.py is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with xbrz.py. If not, see <https://www.gnu.org/licenses/>.

import ctypes
import wand.image
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

def scale_wand(img: wand.image.Image, factor):
	scaled_pixels = scale(
		bytearray(img.export_pixels(channel_map='RGBA')),
		factor,
		img.width,
		img.height,
		ColorFormat.RGBA,
	)
	scaled = wand.image.Image(width=factor * img.width, height=factor * img.height)
	scaled.import_pixels(channel_map='RGBA', data=bytearray(scaled_pixels))
	return scaled

def main():
	import sys

	scaled = scale(bytearray(sys.stdin.buffer.read()), *map(int, sys.argv[1:]), ColorFormat.RGBA)
	sys.stdout.buffer.write(scaled)

if __name__ == '__main__':
	main()
