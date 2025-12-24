import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
#import struct

#######################################################################################
# Hex to/from base4 converters (not used in any code, but useful for quick checks)
def hex_to_base4(hex_str):
    # Convert hex string to integer
    num = int(hex_str, 16)
    # Convert integer to base 4
    if num == 0:
        return '0'* len(hex_str) * 2  # Ensure 2 digits for each hex character
    base4 = ''
    while num > 0:
        base4 = str(num % 4) + base4
        num //= 4
    if len(base4) < 2 * len(hex_str):
        # Pad with leading zeros to ensure the length is twice the hex string length
        base4 = '0' * (2 * len(hex_str) - len(base4)) + base4
    return base4

def hex_data_to_base4(hex_data):
    # Split the hex data into pairs of characters (2 characters = 1 byte)
    bytes_list = [hex_data[i:i+2] for i in range(0, len(hex_data), 2)]
    # Convert each byte to base 4
    base4_list = [hex_to_base4(byte) for byte in bytes_list]
    return ' '.join(base4_list)

def base4_to_hex(base4_str):
    hex_str = hex(int(base4_str, 4))
    return hex_str

# Hex to/from bytes converters
def make_hex(data):
    if isinstance(data,bytes):
        data = data.hex()
    return data.upper().replace(' ','')

def make_bytes(data):
    if isinstance(data,str):
        data = bytes.fromhex(data)
    return data
    
#######################################################################################
#######################################################################################
# Decoding CMPR-compressed image data into pixels
#######################################################################################
#######################################################################################
# Color converter from 2-byte (Gamecube format) to 3-byte (PC format)
def rgb565_to_rgb888_be(high_byte, low_byte):
    """Convert two bytes (big-endian) of RGB565 to RGB888"""
    value = (high_byte << 8) | low_byte

    r = ((value >> 11) & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x3F) * 255 // 63
    b = (value & 0x1F) * 255 // 31

    return (r, g, b)

#######################################################################################
# Convert 8-byte block of CMPR-compressed image data to a 4x4 of pixels
def decode_cmpr_block(block_bytes):
    block_bytes = make_bytes(block_bytes)
    if len(block_bytes) != 8:
        raise ValueError("CMPR block must be exactly 8 bytes")

    # Convert base colors to RGB
    c0 = rgb565_to_rgb888_be(block_bytes[0], block_bytes[1])
    c1 = rgb565_to_rgb888_be(block_bytes[2], block_bytes[3])

    raw0 = (block_bytes[0] << 8) | block_bytes[1]
    raw1 = (block_bytes[2] << 8) | block_bytes[3]

    if raw0 > raw1:
        c2 = tuple((2 * a + b) // 3 for a, b in zip(c0, c1))
        c3 = tuple((a + 2 * b) // 3 for a, b in zip(c0, c1))
    else:
        print("this shouldn't trigger?")
        c2 = tuple((a + b) // 2 for a, b in zip(c0, c1))
        c3 = (0, 0, 0)

    palette = [c0, c1, c2, c3]

    # Extract pixel indices (4x4 grid, right to left per row)
    bitmap = int.from_bytes(block_bytes[4:8], 'little')
    pixels = [[(0, 0, 0) for _ in range(4)] for _ in range(4)]

    for row in range(4):
        for col in range(4):
            bit_index = (row * 4 + (3 - col)) * 2
            index = (bitmap >> bit_index) & 0b11
            pixels[row][col] = palette[index]
    return pixels

# Reconstruct a full photo from raw memory data by converting multiple blocks of CMPR-compressed image data into a width x height grid of pixels (pictobox resolution is 152x104)
def decode_cmpr_image_tiled(data, width=152, height=104):
    data = make_bytes(data)
    if width % 8 != 0 or height % 8 != 0:
        raise ValueError("Width and height must be multiples of 8")

    blocks_x = width // 4
    blocks_y = height // 4

    tiles_x = width // 8
    tiles_y = height // 8

    pixels = [[(0, 0, 0) for _ in range(width)] for _ in range(height)]

    i = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            # Each tile is 2×2 blocks (8×8 pixels)
            blocks = []
            for block_index in range(4):
                block = data[i:i+8]
                if len(block) < 8:
                    raise ValueError("Insufficient data for block")
                blocks.append(decode_cmpr_block(block))
                i += 8

            # Place 4 decoded 4x4 blocks into the image
            for row in range(4):
                for col in range(4):
                    pixels[ty * 8 + row][tx * 8 + col] = blocks[0][row][col]
                    pixels[ty * 8 + row][tx * 8 + col + 4] = blocks[1][row][col]
                    pixels[ty * 8 + row + 4][tx * 8 + col] = blocks[2][row][col]
                    pixels[ty * 8 + row + 4][tx * 8 + col + 4] = blocks[3][row][col]

    return pixels

#######################################################################################
#######################################################################################
# Brightness Patterns, Probabilities, & Rarity Scores
#######################################################################################
#######################################################################################
# Convert CMPR palette index to brightness index (WBLD -> BDLW)
def p2b_idxmap(p_idx):
    p2b_dict = {0: 3, 1: 0, 2: 2, 3: 1}
    return p2b_dict[p_idx]

# Compute contrast/brightness difference between two palette indices
def brightness_distance(a, b):
    """Map index to brightness and return contrast distance."""
    return abs(p2b_idxmap(a) - p2b_idxmap(b))

#######################################################################################
# Given 4 bytes of CMPR tiling/pixel data, return 4x4 grid of 2-bit indices corresponding to either palette ('p') or brightness ('b') indices
def decode_tiling_indices(tiling_block, idx_type='p'): # 'p' for palette, 'b' for brightness
    """Given 4 bytes of CMPR tiling data, return 4x4 grid of 2-bit indices."""
    tiling_block = make_bytes(tiling_block)
    bits = int.from_bytes(tiling_block, byteorder='big')
    indices = [(bits >> (30 - 2 * i)) & 0b11 for i in range(16)]
    if idx_type == 'b':
        # Convert to brightness indices
        indices = [p2b_idxmap(i) for i in indices]
    return [indices[i * 4:(i + 1) * 4] for i in range(4)]

#######################################################################################
# Count how many times each brightness & edge pattern appears in a NONTRIVIAL tiling; returns b_dict (keys: 'B','D','L','W') and edge_dict (keys: 'BB','BD',...,'BvB','BvD',...)
def block_brightness_patterns(tiling_data):
    # Check if tiling_data is a hex string or bytes, and check if it's all zeros
    tiling_data = make_bytes(tiling_data)
    if all(b == 0 for b in tiling_data):
        #b_dict = {'trivial W': 16}
        #edge_dict = {'trivial WW': 24}
        return {}, {} # Don't want to include trivial tilings when computing probabilities
    
    brightness_grid = decode_tiling_indices(tiling_data, idx_type='b')
    brightnesses = 'BDLW'  # Brightness labels: Black, Dark, Light, White
    b_dict = {}
    edge_dict = {}
    for b1 in brightnesses:
        b_dict[b1] = 0
        for b2 in brightnesses:
            edge_dict[b1+b2] = 0            # Horizontal pattern (b1 left of b2)
            edge_dict[b1 + 'v' + b2] = 0    # Vertical pattern (b1 above b2)
    for row in brightness_grid:
        for col in row:
            b_dict[brightnesses[col]] += 1
        for i in range(3):
            b12 = brightnesses[row[i]] + brightnesses[row[i + 1]]
            edge_dict[b12] += 1
    for j in range(4):
        column = [brightness_grid[i][j] for i in range(4)]
        for i in range(3):
            b12 = brightnesses[column[i]] + 'v' + brightnesses[column[i + 1]]
            edge_dict[b12] += 1
    return b_dict, edge_dict

#######################################################################################
# Scan through CMPR data and count frequency of each brightness (b_dict), edge pattern(edge_dict), hex value (hex_dict), and byte value (byte_dict). Output is a single dictionary dict = {'b': b_dict, 'edge': edge_dict, 'hex': hex_dict, 'byte': byte_dict}
def tiling_counter(data):
    data = make_hex(data)
    assert len(data) % 16 == 0, "CMPR data must be a multiple of 8 bytes"
    hex_dict = {}
    byte_dict = {}
    #score_dict = {}
    b_dict = {}
    edge_dict = {}
    # Iterate through the data in 8-byte chunks
    for i in range(0, len(data), 16):
        if data[i+4:i+8] == '0000':
            byte_dict['trivial 00'] = byte_dict.get('trivial 00', 0) + 4
            hex_dict['trivial 0'] = hex_dict.get('trivial 0', 0) + 8
            #edge_dict['trivial 0'] = edge_dict.get('trivial 0', 0) + 24
            #edge_dict['trivial WW'] = edge_dict.get('trivial WW', 0) + 24
            #score_dict[1] = score_dict.get(1, 0) + 1 # default rarity score is 1 for trivial tiling
            continue # skip the trivial tiling (all 16 pixels are the same color)
        
        tile = data[i+8:i+16]  # last 4 bytes of the 8-byte CMPR block
        #brightness_counts = count_tiling_brightnesses(tile)
        b_dict_block, edge_dict_block = block_brightness_patterns(tile)
        for b, count in b_dict_block.items():
            b_dict[b] = b_dict.get(b,0) + count
        for edge, count in edge_dict_block.items():
            edge_dict[edge] = edge_dict.get(edge,0) + count
        
        #print(tile, [f'{b}: {b_dict_block[b]}' for b in 'WBLD'])
        for b in 'WB':
            if b_dict_block[b] == 0:
                print(f"WTF: Tiling {tile} doesn't use palette label {b}!")
        for i in range(len(tile)):
            hex_dict[tile[i]] = hex_dict.get(tile[i], 0) + 1
            if i % 2 == 0:
                byte_hex = tile[i:i+2] 
                byte_dict[byte_hex] = byte_dict.get(byte_hex, 0) + 1
        
        # if rarity_dict:
        #     score = tiling_rarity_score(tile, rarity_dict)
        #     score_dict[score] = score_dict.get(score, 0) + 1
        #     score_dict = dict(sorted(score_dict.items(), key=lambda x: x[1], reverse=True))

    # Sort the dictionary by hex value
    hex_dict = dict(sorted(hex_dict.items(), key=lambda x: x[1], reverse=True))
    byte_dict = dict(sorted(byte_dict.items(), key=lambda x: x[1], reverse=True))
    #score_dict = dict(sorted(score_dict.items(), key=lambda x: x[1], reverse=True))
    #print(hex_dict)
    dicts = {'hex': hex_dict, 'byte': byte_dict, 'b': b_dict, 'edge': edge_dict}
    # if rarity_dict:
    #     dicts['score'] = score_dict
    return dicts #hex_dict, byte_dict, b_dict, edge_dict, score_dict

#######################################################################################
# Construct a probability dictionary of brightnesses and edge patterns for NONTRIVIAL tilings using brightness & edge count dictionaries
def construct_P_dict_from_dicts(b_dict, edge_dict):
    """Construct a probability dictionary of NONTRIVIAL tilings from brightness pattern dictionaries."""
    P_dict = {}
    N_pixels = sum(b_dict.values())
    for b, count in b_dict.items():
        if 'trivial' in b:
            KeyError('b_dict should NOT include trivial tiling info')
        P_dict[b] = count / N_pixels
        # rarity_score = -np.log10(prob_b) if prob_b > 0 else np.inf
        # rarity_dict[b] = rarity_score  # / 24  # Normalize by 24 to scale the rarity score

    for edge, count in edge_dict.items():
        if 'trivial in edge':
            KeyError('edge_dict should NOT include trivial tiling info')
        if len(edge) == 2:
            b_left = edge[0]
            N_b_left_edges = sum([edge_dict[b_left + b_right] for b_right in 'BDLW'])
            P_dict[edge] = count / N_b_left_edges # normalized conditional probability
        elif 'v' in edge:
            b_top = edge[0]
            N_b_top_edges = sum([edge_dict[b_top + 'v' + b_bot] for b_bot in 'BDLW'])
            P_dict[edge] = count / N_b_top_edges # normalized conditional probability
        # if 'trivial' not in edge and edge[0]!=edge[1]:
        #     prob = prob #/ 2 # to account for symmetry (e.g. 'BD' is the same as 'DB')
    return P_dict

# Construct P_dict from a list of files with CMPR data
def construct_P_dict_from_files(file_list):
    b_dict = {}
    edge_dict = {}
    for file in file_list:
        with open(file, 'r') as f:
            data = f.read()
        tile_dicts = tiling_counter(data)
        for b, count in tile_dicts['b'].items():
            b_dict[b] = b_dict.get(b, 0) + count
        for edge, count in tile_dicts['edge'].items():
            edge_dict[edge] = edge_dict.get(edge, 0) + count
    P_dict = construct_P_dict_from_dicts(b_dict, edge_dict)
    return P_dict

# Default P_dict using data from 5 arbitrary pictographs I took
default_P_dict = {
    'B': 0.3428472987872106, 'D': 0.16178335170893055, 'L': 0.1646499448732084, 'W': 0.33071940463065047,
    'BB': 0.6595569689658953, 'BvB': 0.7394861724758632, 'BD': 0.13943414848119312, 'BvD': 0.14236622484045164, 'BL': 0.06749643601272069, 'BvL': 0.058582883325151366, 'BW': 0.13351244654019082, 'BvW': 0.05956471935853379,
    'DB': 0.2880369109084917, 'DvB': 0.27908761925649744, 'DD': 0.39580358123695486, 'DvD': 0.3991665752823775, 'DL': 0.1951005163133033, 'DvL': 0.2191029718170852, 'DW': 0.12105899154125013, 'DvW': 0.10264283364403992,
    'LB': 0.13797563867629623, 'LvB': 0.1002234280242579, 'LD': 0.19823218712945995, 'LvD': 0.2284285562293861, 'LL': 0.39538643958176134, 'LvL': 0.39248856261304393, 'LW': 0.26840573461248246, 'LvW': 0.27885945313331206,
    'WB': 0.14610717896865522, 'WvB': 0.06585463031475895, 'WD': 0.0670711156049882, 'WvD': 0.052421879446752806, 'WL': 0.14155712841253792, 'WvL': 0.1515737947521202, 'WW': 0.6452645770138187, 'WvW': 0.730149695486368}

# Corresponding default rarity score dictionary
default_rarity_dict = {k: -np.log10(default_P_dict[k]) for k in default_P_dict}
#######################################################################################
# Compute "rarity score" = -log10(Prob(tiling)) using probabilities in P_dict. Currently approximates Prob(tiling) = P(edge1)*P(edge2)*...*P(edge24) with each P(edge) in P_dict normalized as a conditional probability, e.g. P(BB)+P(BD)+P(BL)+P(BW) = 1
def tiling_rarity_score(tiling_data, P_dict = default_P_dict):
    grid = decode_tiling_indices(tiling_data, idx_type='b')
    if not any(0 in row for row in grid):
        #print(f"Tiling 0x{tiling_data} has no 'black' pixels; setting rarity to infinity")
        return np.inf
    
    brightnesses = 'BDLW'
    score = 0
    for y in range(4):
        for x in range(4):
            #b = brightnesses[grid[y][x]]
            #score += rarity_dict[b] # from individual brightnesses
            if x < 3:
                i1,i2 = grid[y][x], grid[y][x + 1]
                edge = brightnesses[i1] + brightnesses[i2]
                P_edge = P_dict[edge]   # normalized conditional probability
                edge_rarity = -np.log10(P_edge)
                score += edge_rarity    
            if y < 3:
                i1,i2 = grid[y][x], grid[y+1][x]
                edge = brightnesses[i1] + 'v' + brightnesses[i2]
                P_edge = P_dict[edge]   # normalized conditional probability
                edge_rarity = -np.log10(P_edge)
                score += edge_rarity    
    return score

# Go through CMPR data and output list of each 4x4 tiling's rarity score using P_dict
def compute_rarity_list(data, P_dict):
    data = make_hex(data)
    assert len(data) % 16 == 0, "CMPR data must be a multiple of 8 bytes"
    
    # Iterate through the data in 8-byte chunks
    score_list = []
    for i in range(0, len(data), 16):
        tile = data[i+8:i+16]  # last 4 bytes of the 8-byte CMPR block
        if tile[4:8] != '0000': # ignore trivial tilings
            score = tiling_rarity_score(tile, P_dict)
            score_list.append(score)
    score_list.sort()
    return score_list

#######################################################################################
#######################################################################################
# Visuals
#######################################################################################
#######################################################################################
# Visualize 4x4 of pixels, with option for overlaying the tiling hex labels ("pixel data")
def visualize_4x4_pixels(ax, pixels, tiling_hex=None):
    #pixels = np.array(pixels).reshape((4, 4, 3)).astype(np.uint8)
    ax.imshow(pixels)

    # Hide axes
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # Draw hex labels if tiling_hex is given
    if tiling_hex:
        # Draw horizontal gridlines
        for y in range(1, 4):
            ax.axhline(y - 0.52, color='red', linewidth=1.5)

        # Draw bold vertical center line between bytes 2 and 3
        ax.axvline(1.5, color='red', linewidth=1.5)
        
        if isinstance(tiling_hex, str):
            tiling_hex = tiling_hex.replace(' ', '')
        # elif isinstance(tiling_hex, int):
        #     tiling_hex = tiling_hex.to_bytes(4, 'big')

        # Each byte affects a 2x2 block (4 bytes, 4 regions)
        hex_labels = [h for h in tiling_hex]
        positions = [(0.5, 0), (2.5, 0), (0.5, 1), (2.5, 1), (0.5, 2), (2.5, 2), (0.5, 3), (2.5, 3)]

        for (x, y), label in zip(positions, hex_labels):
            ax.text(x, y, label, fontsize=10, ha='center', va='center',
                    color='black', bbox=dict(facecolor='red', alpha=0.5, lw=0))
            
# Same as above, but only requires tiling hex as input; defaults to white/black palette
def visualize_4x4_tiling(tiling_hex, palette_hex='FFFF0000', show_hex_labels=False, ax=None):
    pixels = decode_cmpr_block(palette_hex + tiling_hex)
    #pixels = np.array(pixels).reshape((4, 4, 3)).astype(np.uint8)

    if ax is None:
        fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(pixels)

    # Hide axes
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # Draw hex labels if tiling_hex is given
    if show_hex_labels:
        # Draw horizontal gridlines
        for y in range(1, 4):
            ax.axhline(y - 0.52, color='red', linewidth=1.5)
        # Draw vertical center line between bytes 2 and 3
        ax.axvline(1.5, color='red', linewidth=1.5)
        
        tiling_hex = tiling_hex.replace(' ', '')
        
        # Each byte affects a 2x2 block (4 bytes, 4 regions)
        hex_labels = [h for h in tiling_hex]
        positions = [(0.5, 0), (2.5, 0), (0.5, 1), (2.5, 1), (0.5, 2), (2.5, 2), (0.5, 3), (2.5, 3)]

        for (x, y), label in zip(positions, hex_labels):
            ax.text(x, y, label, fontsize=10, ha='center', va='center',
                    color='black', bbox=dict(facecolor='red', alpha=0.5, lw=0))

#######################################################################################
# Save pixels to an image file; defaults to photo.png
def save_image(pixels, filename="photo.png"):
    height = len(pixels)
    width = len(pixels[0])
    img = Image.new("RGB", (width, height))
    flat_pixels = [pixel for row in pixels for pixel in row]
    img.putdata(flat_pixels)
    img.save(filename)

# Convert raw CMPR data file to an image file
def CMPR_to_image(data_file, out_file="photo.png", width=152, height=104):
    with open(data_file,'r') as f:
        data = f.read()
    pixels = decode_cmpr_image_tiled(data, width=width, height=height)
    save_image(pixels, filename=out_file)

#######################################################################################
# Convert a png to a CMPR-compressed pictograph data file (7904 bytes)
#######################################################################################
# Convert 24-bit RGB to 16-bit RGB565 raw integer (big-endian ordering used elsewhere)
def rgb888_to_rgb565_raw(r, g, b):
    r5 = int(r * 31 / 255 + 0.5)
    g6 = int(g * 63 / 255 + 0.5)
    b5 = int(b * 31 / 255 + 0.5)
    raw = (r5 << 11) | (g6 << 5) | b5
    return raw


# Encode a 4x4 block of RGB pixels (list of 4 rows each with 4 (r,g,b) tuples) into 8 bytes of CMPR block
def encode_cmpr_block(pixels4x4):
    # Flatten pixels
    flat = [tuple(map(int, p)) for row in pixels4x4 for p in row]
    arr = np.array(flat, dtype=np.float64)

    # Simple 2-means clustering (k=2) on RGB to pick two endpoint colors
    # Initialize with min/max luminance
    lum = 0.2126 * arr[:, 0] + 0.7152 * arr[:, 1] + 0.0722 * arr[:, 2]
    idx_min = int(np.argmin(lum))
    idx_max = int(np.argmax(lum))
    c0 = arr[idx_max].copy()
    c1 = arr[idx_min].copy()

    for _ in range(8):
        d0 = np.sum((arr - c0) ** 2, axis=1)
        d1 = np.sum((arr - c1) ** 2, axis=1)
        assign = d0 <= d1
        if assign.sum() > 0:
            c0_new = arr[assign].mean(axis=0)
        else:
            c0_new = c0
        if (~assign).sum() > 0:
            c1_new = arr[~assign].mean(axis=0)
        else:
            c1_new = c1
        # Break if converged
        if np.allclose(c0_new, c0) and np.allclose(c1_new, c1):
            break
        c0, c1 = c0_new, c1_new

    # Convert centroids to integer RGB 0-255
    c0 = tuple(int(np.clip(round(x), 0, 255)) for x in c0)
    c1 = tuple(int(np.clip(round(x), 0, 255)) for x in c1)

    raw0 = rgb888_to_rgb565_raw(*c0)
    raw1 = rgb888_to_rgb565_raw(*c1)

    # Ensure raw0 > raw1 to select 4-color mode where possible
    if raw0 <= raw1:
        # swap
        raw0, raw1 = raw1, raw0
        c0, c1 = c1, c0

    # Build palette according to decoder rules
    def mix(a, b, w_a, w_b, div):
        return tuple((w_a * aa + w_b * bb) // div for aa, bb in zip(a, b))

    if raw0 > raw1:
        c2 = mix(c0, c1, 2, 1, 3)
        c3 = mix(c0, c1, 1, 2, 3)
    else:
        c2 = tuple((a + b) // 2 for a, b in zip(c0, c1))
        c3 = (0, 0, 0)

    palette = [c0, c1, c2, c3]

    # For each pixel pick nearest palette index (Euclidean)
    palette_arr = np.array(palette, dtype=np.float64)
    idxs = []
    for pix in flat:
        d = np.sum((palette_arr - np.array(pix, dtype=np.float64)) ** 2, axis=1)
        idxs.append(int(np.argmin(d)))

    # Pack indices into 32-bit bitmap (little-endian when writing bytes)
    bitmap = 0
    # bit_index = (row * 4 + (3 - col)) * 2 used by decoder
    for row in range(4):
        for col in range(4):
            index = idxs[row * 4 + col] & 0x3
            bit_index = (row * 4 + (3 - col)) * 2
            bitmap |= (index << bit_index)

    # Compose 8 bytes: raw0 (big-endian), raw1 (big-endian), bitmap (4 bytes little-endian)
    out = bytearray()
    out.append((raw0 >> 8) & 0xFF)
    out.append(raw0 & 0xFF)
    out.append((raw1 >> 8) & 0xFF)
    out.append(raw1 & 0xFF)
    out.extend(int(bitmap).to_bytes(4, 'little'))
    return bytes(out)


# Convert a PNG (or other image) into CMPR hex data file matching the decoder layout
def image_to_CMPR(png_file, out_file=None, width=152, height=104, resize_if_needed=True):
    img = Image.open(png_file).convert('RGB')
    #print(img.size)
    if img.size != (width, height):
        if resize_if_needed:
            img = img.resize((width, height), Image.NEAREST)
        else:
            raise ValueError(f"Image size {img.size} doesn't match target ({width},{height})")

    pixels = list(img.getdata())
    # Convert into 2D list of rows
    pix2d = [pixels[i * width:(i + 1) * width] for i in range(height)]

    tiles_x = width // 8
    tiles_y = height // 8

    data_bytes = bytearray()

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            # For each of the 4 sub-blocks in tile order
            for block_index in range(4):
                if block_index == 0:
                    origin_r = ty * 8
                    origin_c = tx * 8
                elif block_index == 1:
                    origin_r = ty * 8
                    origin_c = tx * 8 + 4
                elif block_index == 2:
                    origin_r = ty * 8 + 4
                    origin_c = tx * 8
                elif block_index == 3:
                    origin_r = ty * 8 + 4
                    origin_c = tx * 8 + 4

                block_pixels = []
                for r in range(4):
                    row = []
                    for c in range(4):
                        row.append(pix2d[origin_r + r][origin_c + c])
                    block_pixels.append(row)

                block_bytes = encode_cmpr_block(block_pixels)
                data_bytes.extend(block_bytes)

    # Write output as hex string (uppercase) to match existing reader expectations
    # hexstr = data_bytes.hex().upper()
    # with open(out_file, 'w') as f:
    #     f.write(hexstr)
    with open(out_file, 'wb') as f:
        f.write(data_bytes)
    return out_file

#######################################################################################
# Show pie chart of data_dict = {label1: count1, ...}; useful for visualizing b_dict and edge_dict probabilities
def show_pie_chart(data_dict, title=None):
    labels = list(data_dict.keys())
    counts = list(data_dict.values())

    # Generate colors automatically or define your own
    colors = plt.cm.tab20.colors  # or 'tab10', 'hsv', etc.
    color_list = colors[:len(labels)]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        counts,
        labels=labels,
        autopct='%1.1f%%',
        startangle=140,
        colors=color_list,
        textprops=dict(color="black")  # default color for percentage text
    )

    # Color each label to match the wedge
    for text, color in zip(texts, color_list):
        text.set_color(color)

    if title != None:
        ax.set_title(title, color='white')
    plt.tight_layout()
    plt.show()

#######################################################################################
#######################################################################################
# Finding target tiling pattern & highlighting pixels in photo
#######################################################################################
#######################################################################################
# Search for target 4-byte tiling pattern inside CMPR data & return list of offsets of matches
def find_tiling_pattern(data, target):
    # Check if data and/or target is a hex string, and if so converts to bytes
    data = make_bytes(data)
    target = make_bytes(target)
    assert len(target) == 4, "Target pattern must be exactly 4 bytes"
    assert len(data) % 8 == 0, "CMPR data must be a multiple of 8 bytes"

    matches = []
    for i in range(0, len(data), 8):
        tile = data[i+4:i+8]  # last 4 bytes of the 8-byte CMPR block
        if tile == target:
            print(f"MATCH FOUND! Offset: {i}")
            matches.append(i)
        
    if not matches:
        print("No matches found :(")
        return None
    return matches


# Create image with highlighted pixel tiling pattern located at a specific byte offset in the data
def highlight_at_offset(data_file, tiling_offset, out_file='photo.png', palette='F000001F'):
    with open(data_file,'r') as f:
        data = f.read()
    data = make_bytes(data)
    palette = make_bytes(palette)
    hl_data = data[:tiling_offset - 4] + palette + data[tiling_offset:]
    pixels = decode_cmpr_image_tiled(hl_data, width=152, height=104)
    save_image(pixels, filename=out_file)


# Convert offset within CMPR data to pixel (row, column) in image
def cmpr_offset_to_pixel(offset, width=152, height=104):
    # CMPR compresses in 8x8 macroblocks, each 32 bytes
    macroblock_bytes = 32
    subblock_bytes = 8
    #subblocks_per_macro = 4

    # How many macroblocks per row?
    macroblocks_per_row = width // 8

    # Index of macroblock
    macro_idx = offset // macroblock_bytes
    macro_row = macro_idx // macroblocks_per_row
    macro_col = macro_idx % macroblocks_per_row

    # Offset within the macroblock
    within_macro_offset = offset % macroblock_bytes
    subblock_idx = within_macro_offset // subblock_bytes

    # Determine which of the 4 subblocks this is:
    if subblock_idx == 0:
        sub_r, sub_c = 0, 0
    elif subblock_idx == 1:
        sub_r, sub_c = 0, 4
    elif subblock_idx == 2:
        sub_r, sub_c = 4, 0
    elif subblock_idx == 3:
        sub_r, sub_c = 4, 4
    else:
        raise ValueError("Invalid offset: does not align with CMPR subblock layout")

    # Final pixel row/col = macroblock origin + subblock offset
    pixel_row = macro_row * 8 + sub_r
    pixel_col = macro_col * 8 + sub_c

    return (pixel_row, pixel_col)


# Find (horizontal, vertical) distance between 2 pixels in photo given data offsets
def pixel_distance(offset, tgt_offset=0x1264):
    (r, c) = cmpr_offset_to_pixel(offset)
    (r_tgt, c_tgt) = cmpr_offset_to_pixel(tgt_offset)
    return (r_tgt-r, c_tgt-c)