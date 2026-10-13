#!/usr/bin/env python3
"""Create a minimal 16x16 32-bit ICO file for Tauri."""
import struct
import zlib

# 16x16 32-bit BMP (DIB header + pixels)
width, height = 16, 16
bpp = 32
row_size = ((width * bpp + 31) // 32) * 4  # 64 bytes per row
pixel_data = b'\x00' * (row_size * height)  # all transparent (blue=0, green=0, red=0, alpha=0)

# BMP file header
bmp_header = struct.pack('<2sIHHI', b'BM', 14 + 40 + len(pixel_data), 0, 0, 14 + 40)
# DIB header (BITMAPINFOHEADER)
dib_header = struct.pack('<IIIHHIIIIII', 40, width, height * 2, 1, bpp, 0, len(pixel_data), 0, 0, 0, 0)

bmp = bmp_header + dib_header + pixel_data

# ICO header
icon_dir = struct.pack('<HHH', 0, 1, 1)  # reserved, type=ICO, count=1
# Icon directory entry
entry = struct.pack('<BBBBHHII', width, height, 0, 0, 1, bpp, len(bmp), 22)  # 22 = ICO header(6) + entry(16)

with open('D:/Projects/seraphim/prototypes/stack-s02/ui-tauri/icons/icon.ico', 'wb') as f:
    f.write(icon_dir + entry + bmp)

print("icon.ico created")
