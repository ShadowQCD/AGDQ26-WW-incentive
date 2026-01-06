from keystone import Ks, KsError, KS_ARCH_PPC, KS_MODE_PPC64
import re
import picto_functions as picto

#######################################################################################
# Register dictionary at start of ACE payload
def ACE_rdict(r3 = 0x81579F34, r12 = 0x803F0F3C, r29 = 0x80A60850):
    rdict = {
        0:  0x00000002,
        1:  0x8040CE00, # stack pointer (DO NOT CHANGE)
        2:  0x803FFD00, # TOC(?) pointer (DO NOT CHANGE)
        3:  r3,         # sScreen = photo3 pixeldata address; island/heap dependent
        4:  0x00000001, 
        5:  0xFFFFFFFF,
        6:  0x000010B8, # check if consistent?
        7:  0x00293D6C, # seems inconsistent, like it can vary by 0x10 or so
        8:  0x00000008,
        9:  0x0011C664, # seems inconsistent
        10: 0x0011C66C, # seems inconsistent
        11: 0x8040CE30,
        12: r12,        # payload start address
        13: 0x803FE0E0, # &sScreen = r13 - 0x6F38 = 0x803F71A8 (DO NOT CHANGE)
        # 14-27: 0x0,   # fine to edit
        28: 0x8003D1DC,
        29: r29,        # PROC_MSG start address; island/heap dependent
        30: 0x804C3B30, # used by safety branch (DO NOT CHANGE)
        31: 0x803E6EA0
        }
    return rdict



#######################################################################################
# Data conversion functions
#######################################################################################
# Convert list of 4 bytes (little endian from Keystone) into a big-endian word
def LE_bytes_to_BE_word(byte_list):
    if len(byte_list) != 4:
        return None
    # Reverse because Keystone outputs LE
    be_bytes = byte_list[::-1]
    return (be_bytes[0] << 24) | (be_bytes[1] << 16) | (be_bytes[2] << 8) | be_bytes[3], be_bytes

# # Convert byte list to binary string (useful for Keystone outputs)
# def bytes_to_bin(byte_list):
#     return " ".join(f"{b:08b}" for b in byte_list)

# # Convert unsigned 32-bit integer to hex string (not sure if used anywhere)
# def get_u32_hex(n):
#     return hex(n & 0xFFFFFFFF).upper().zfill(4)

# Convert integer to binary string with spaces every 'group' bits (default 8)
def format_bin(n, group=8):
    # how many bits are needed to represent n
    bitlen = n.bit_length() or 1
    # round up to nearest multiple of group (default 8)
    width = ((bitlen + group - 1) // group) * group
    # format and split into groups
    b = f"{n:0{width}b}"
    return " ".join(b[i:i+group] for i in range(0, len(b), group))

# Convert hex string to a list of decimal integers (one for each byte); useful for translating controller data -> inputs
def hex_bytes_to_dec(hex_str):
    if hex_str[:2].lower() == '0x':
        hex_str = hex_str[2:]
    return [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]

# Split address into base + offset to use for 'lis rA, base' + 'stw rS, offset (rA)'
def split_addr(addr):
    addr = int(addr, 16) if isinstance(addr,str) else addr
    addr_base = addr // 0x10000
    addr_off = addr % 0x10000
    if addr_off >= 0x8000:
        addr_base += 1
        addr_off = addr_off - 0x10000
        #print(hex(addr_base), hex(addr_off), addr_off)
    return addr_base, addr_off

# # Compute HA/LO used for PowerPC constant loading, e.g. 'lis rA, HA' + 'ori rA, rA, LO'
# def ha_lo(value):
#     value = int(value, 16) if isinstance(value,str) else value
#     ha = ((value + 0x8000) >> 16) & 0xFFFF
#     lo = value & 0xFFFF
#     return ha, lo
#######################################################################################
# Classify whether so types
#######################################################################################
# Check whether a string is hex or not
def is_hex(s: str) -> bool:
    if s.startswith(("0x", "0X")):  # Strip optional leading 0x or 0X
        s = s[2:]
    if not s:
        return False    # Empty string after stripping is not valid hex
    return all(c in "0123456789abcdefABCDEF" for c in s)    # Check each character

# Check whether an (address, value_str) pair makes a valid ASM instruction or not
def is_ASM(addr, val_str, ks=None):
    try:
        # Try encoding; only the exception behavior matters
        addr = int(addr, 16) if isinstance(addr, str) else addr
        get_ASM_encoding(val_str, addr=addr, ks=ks, output_type='hex')
        return True
    except Exception:
        print(hex(addr), val_str)
        return False

# Determine whether a hex value is an ASM instruction or not (current implementation is roundabout, should improve/streamline)
def get_value_type(addr, val, ks=None):
    addr = int(addr, 16) if isinstance(addr,str) else addr
    if isinstance(val, int):
        return 'int'
    elif is_hex(val):
        return 'hex'
    elif is_ASM(addr, val, ks=ks):               # should refine this later
        return 'asm'
    else:
        #print(val, type(val))
        raise TypeError(f"{addr:08X}: {val} is unrecognized (address, value) pair type")
#######################################################################################
# Assembly instructions -> hex/binary words
#######################################################################################
# E.g. fcmp0 cr0, f22, f21
def encode_fcmpo(operands):
    """
    operands = ["cr0", "f22", "f21"] or ["cr0","fr22","fr21"]
    returns uppercase hex string, e.g. "FD58A040"
    """
    if len(operands) != 3:
        raise ValueError(f"fcmpo requires 3 operands, got: {operands}")

    cr = operands[0]
    fa = operands[1]
    fb = operands[2]

    # --- parse cr field ---
    # accept crX or crfX
    if cr.startswith("crf"):
        crfD = int(cr[3:])
    elif cr.startswith("cr"):
        crfD = int(cr[2:])
    else:
        raise ValueError(f"Invalid condition register field: {cr}")

    # --- parse floating registers ---
    fa = fa.replace("fr", "").replace("f", "")
    fb = fb.replace("fr", "").replace("f", "")
    a = int(fa)
    b = int(fb)

    # --- fcmpo fields ---
    opcode = 63     # 0x3F
    XO     = 32     # 0b100000
    Rc     = 0

    # Assemble the word
    word = (
        (opcode << 26) |
        (crfD  << 23) |
        (a     << 16) |
        (b     << 11) |
        (XO    << 1 ) |
        Rc
    )

    # Return hex word exactly as Keystone does
    return f"{word:08X}"


# Use custom encoding for ASM instructions that aren't recognized by Keystone
def custom_encode_ASM(asm_code, addr=0):
    # strip whitespace, inline comments, etc.
    asm = asm_code.split('#')[0].strip()

    # canonicalize spacing (optional)
    asm = " ".join(asm.replace(",", " ").split())

    # extract mnemonic and operands
    parts = asm.split()
    if not parts:
        raise ValueError(f"Empty instruction for custom encoder: {asm_code}")

    mnemonic = parts[0].lower()
    operands = parts[1:]

    # ---- Dispatch table ----
    if mnemonic == "fcmpo":
        return encode_fcmpo(operands)

    # Add more custom handlers here:
    # if mnemonic == "fcmpu": ...
    # if mnemonic == "ps_add": ...
    # etc.

    raise NotImplementedError(f"Custom PPC encoder does not support: {asm_code}")

# Use Keystone to convert a Gekko PowerPC assembly instruction into hex/bin/bytes
def get_ASM_encoding(asm_code, addr=0, ks=None, output_type='hex'):  # addr is the instruction address (for branch offsets)
    if ks is None:
        ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64)
    #print(f'{addr:08X}', asm_code)
    
    #print(f'bleh {hex(addr)}: {asm_code}')
    try:
        if ' ' in asm_code:
            opcode, rest = asm_code.split(' ',1)
            rest = ' ' + rest
            rest = rest.replace('->', '')   # keystone doesn't like '->' in branch instructions
            for sym in [' r', '(r', ' f', '(f']:
                #print(sym, sym[0])
                rest = rest.replace(sym, sym[0])  # keystone doesn't like 'r' or 'f' in register names (this is a lazy/dangerous way to do this, may break some instructions)
            asm_code = opcode + rest
            #print(asm_code)
        
        encoding, count = ks.asm(asm_code, addr=addr, as_bytes=False)            
        int_word, BE_bytes = LE_bytes_to_BE_word(encoding)
        hex_word = f'{int_word:08X}'
    
    except KsError as e:
        hex_word = custom_encode_ASM(asm_code, addr=addr)

    
    match output_type:
        case 'hex':
            return hex_word     # outputs as hex string
        case 'bin':
            return format_bin(int_word)
        case 'bytes':
            return bytes.fromhex(hex_word)

#######################################################################################
# (address, value) pairs
#######################################################################################
# Convert the value in an (address, value) pair from one data type to another
def addr_value_converter(addr, value, output_type, ks=None):
    addr = int(addr, 16) if isinstance(addr,str) else addr  # convert addr to an integer if it's still a hex string

    #input_type = input_type.lower()
    input_type = get_value_type(addr, value)
    output_type = output_type.lower()   
    
    if input_type == output_type:
        return addr, value
    
    # if isinstance(value, bytes):
    #     assert input_type == output_type == 'bytes',  "Are you really trying to convert FROM bytes to something else?"
    #     return addr, value
    
    # if isinstance(value, int):
    #     assert (input_type == 'hex') and (output_type in ['hex','bytes']),  "Unpexpected integer"
    #     value = f'{value:08X}'  # convert integer to hex string
    
    if isinstance(value, str):
        if input_type == output_type:
            return addr, value
        
        elif input_type == 'asm':
            v_out = get_ASM_encoding(value, addr=addr, ks=ks, output_type=output_type)
            return (addr, v_out)
        
        elif input_type == 'hex' and output_type == 'bytes':
            return (addr, bytes.fromhex(value))
        
        elif input_type == 'hex' and output_type == 'int':
            return (addr, int(value, 16))
    
    raise TypeError(f"Unexpected conversion request: value={value}, input_type={input_type}, output_type={output_type}")


# Get list of (address, value) pairs from file_list and output the values in desired format
def get_addr_value_pairs_from_files(file_list, output_type='hex', ks=None):
    if isinstance(file_list, str):
        file_list = [file_list]
    
    addr_value_pairs = []
    for file in file_list:
        with open(file, 'r') as f:
            for line in f:
                for sym in ['#', '//', ';']:
                    line = line.split(sym, 1)[0].strip()    # remove comments & whitespace
                if not line:
                    continue
                addr_str, value_str = line.replace(':','').split(None,1)

                # Check whether value_str is ASM or hex
                #input_type = get_value_type(addr_str, value_str)
                # if input_type == 'asm':
                #     # set cache flag?

                addr, value = addr_value_converter(addr_str, value_str, output_type, ks=ks)
                addr_value_pairs.append((addr,value))
    return addr_value_pairs


# Consolidate a list of (address, hex) pairs into a list of contiguous memory ranges of the form (start address, block size)
def group_contiguous_instruction_ranges(addr_hex_pairs):
    instr_addrs = sorted([addr for addr,val in addr_hex_pairs]) # if get_value_type(addr, val)=='asm'])
    if not instr_addrs:
        return []
    ranges = []
    start = instr_addrs[0]
    last = start
    for a in instr_addrs[1:]:
        if a == last + 4:
            last = a
        else:
            ranges.append((start, last+4 - start))  # (start, length)
            start = a
            last = a
    ranges.append((start, last+4 - start))
    #print([(hex(a), s) for a,s in ranges])
    return ranges

#######################################################################################
# PHASE 1 FUNCTIONS
#######################################################################################
'''
During phase 1:
- DME only writes to 0x803F0F3C (controller 2 C/LR data)
- All instructions are run several times (in case o write/execute conflicts)
- All writes can be done relative to r12=0x803F0F3C
'''

# Get list of PAD2 ASM instructions needed to write hex_to_write at addr_target during phase 1
def phase1_get_instrucs_for_write(addr_target, hex_to_write, r12=0x803F0F3C):
    addr_target = int(addr_target, 16) if isinstance(addr_target,str) else addr_target
    hex_to_write = f'{hex_to_write:08X}' if isinstance(hex_to_write,int) else hex_to_write
    
    # addr_base, addr_off = split_addr(addr_target)
    
    PAD2_instruc_1 = f'lis r14, 0x{hex_to_write[:4]}'
    PAD2_instruc_2 = f'ori r15, r14, 0x{hex_to_write[4:]}'       # use a different register since this will 
    # PAD2_instruc_3 = f'lis r16, 0x{addr_base:04X}'
    # PAD2_instruc_4 = f'stw r15, 0x{addr_off:04X} (r16)'
    # return [PAD2_instruc_1, PAD2_instruc_2, PAD2_instruc_3, PAD2_instruc_4]
    PAD2_instruc_3 = f'stw r15, {addr_target - r12} (r12)'
    return [PAD2_instruc_1, PAD2_instruc_2, PAD2_instruc_3]

    
# Convert a list of (address, instruction) pairs to write during phase 1 into a list of PAD2 instructions (in ASM/hex/bytes) to write with DME
def phase1_get_PAD2_instrucs_for_writes(addr_instruc_pairs, r12=0x803F0F3C, ks=None):
    if ks == None:
        ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64)
    PAD2_instruc_list = []
    for (instruc_addr, instruc) in addr_instruc_pairs:
        hex_to_write = get_ASM_encoding(instruc, addr=instruc_addr, ks=ks, output_type='hex')
        #print(f'{instruc_addr:08X}', hex_to_write)
        new_PAD2_instrucs = phase1_get_instrucs_for_write(instruc_addr, hex_to_write, r12=r12)
        PAD2_instruc_list += new_PAD2_instrucs
    # PAD2_hex_list = [get_ASM_encoding(PAD2_instruc, addr=0x803F0F3C, ks=ks, output_type='hex') for PAD2_instruc in PAD2_instruc_list]   # this addr needs to be wherever DME writes in phase 1 (unrelated to whatever r12 is)
    # PAD2_bytes_list = [bytes.fromhex(instruc_hex) for instruc_hex in PAD2_hex_list]
    return PAD2_instruc_list #, PAD2_hex_list, PAD2_bytes_list


def phase1_final_PAD2_instrucs():
    PAD2_instrucs = [
        'subi r3, r12, 0xC',
        'li r4, 0x70',
        'bl -> 0x80003374',
        'b -> 0x803F0F50'
    ]
    return PAD2_instrucs

# Create phase 1 binary file from list of (address, instruction) pairs
def phase1_create_bin(phase1_addr_instruc_pairs, phase1_bytes_file, r12=0x803F0F3C, ks=None):
    PAD2_instruc_list = phase1_get_PAD2_instrucs_for_writes(phase1_addr_instruc_pairs, r12=r12, ks=ks)
    PAD2_instruc_list += phase1_final_PAD2_instrucs()
    with open(phase1_bytes_file,'wb') as f:
        for PAD2_instruc in PAD2_instruc_list:
            PAD2_instruc_bytes = get_ASM_encoding(PAD2_instruc, addr=0x803F0F3C, ks=ks, output_type='bytes')
            f.write(PAD2_instruc_bytes)


#######################################################################################
# PHASE 2 FUNCTIONS
#######################################################################################

# Get list of pad 1-4 ASM instructions needed to write hex_to_write at addr_target during phase 2
def phase2_get_instrucs_for_write(addr_target, hex_to_write):
    addr_target = int(addr_target, 16) if isinstance(addr_target,str) else addr_target
    hex_to_write = f'{hex_to_write:08X}' if isinstance(hex_to_write,int) else hex_to_write
    
    size = len(hex_to_write) // 2
    if size == 4 and (addr_target % 4 == 0):
        PAD_instruc_1 = f'lis r14, 0x{hex_to_write[:4]}'
        PAD_instruc_2 = f'ori r14, r14, 0x{hex_to_write[4:]}'       # can use same register in phase 2
        store = 'stw'
    elif size <= 2:
        PAD_instruc_1 = f'nop'  # inefficient, but it'll be a headache if we don't always do 4-instruction batches
        
        val = int(hex_to_write,16)
        if val >= 0x8000:
            val -= 0x10000  # keystone needs SIMM signs to be explicit
        PAD_instruc_2 = f'li r14, {val}'
        
        if size == 2 and (addr_target % 2 == 0):
            store = 'sth'
        elif size == 1:
            store = 'stb'
    else:
        raise ValueError(f"Bad alignment or hex size -- {addr_target:08X}: {hex_to_write}")
    
    addr_base, addr_off = split_addr(addr_target)
    #print(hex(addr_base), hex(addr_off), addr_off)

    PAD_instruc_3 = f'lis r15, 0x{addr_base:04X}'
    PAD_instruc_4 = f'{store} r14, {addr_off} (r15)'
    
    return [PAD_instruc_1, PAD_instruc_2, PAD_instruc_3, PAD_instruc_4]

# Create list of pad 1-4 ASM instructions to manage caching for a given memory block (start address, length in bytes) 
def phase2_get_instrucs_to_cache_block(start, length, cache_routine = 0x80003374):
    #ha_start, lo_start = ha_lo(start)
    #ha_len, lo_len = ha_lo(length)
    #print(f"# Invalidate cache for range {start:08X} - {start+length-1:08X} (len {length})")
    start = f'{start:08X}'
    asm_instrucs = []
    asm_instrucs.append(f"lis r3, 0x{start[:4]}")           # r3 = start (partial)
    asm_instrucs.append(f"ori r3, r3, 0x{start[4:]}")       # r3 = start
    asm_instrucs.append(f"li r4, 0x{length:04X}")           # r4 = length
    asm_instrucs.append(f"bl -> 0x{cache_routine:08X}")     # branch to cache routine
    return asm_instrucs

# Create list of pad 1-4 ASM instructions to manage caching for all (address, hex) pairs in phase 2
def phase2_get_cache_instrucs_from_AH_pairs(phase2_addr_hex_pairs):
    #entries = parse_patch_lines(patch_text)
    start_size_pairs = group_contiguous_instruction_ranges(phase2_addr_hex_pairs)
    PAD_cache_instrucs = []
    for start, size in start_size_pairs:
        PAD_cache_instrucs += phase2_get_instrucs_to_cache_block(start, size)
        PAD_cache_instrucs += ['nop'] * 4   # need pad 4 to change each time for new DME writes to be read
    return PAD_cache_instrucs

# Convert a list of (address, hex) pairs to write during phase 2 into a list of PAD instructions (in ASM) to write with DME
def phase2_get_PAD_instruction_list(addr_hex_pairs):
    PAD_write_instrucs = []
    for (addr, hex_to_write) in addr_hex_pairs:
        #print(f'{instruc_addr:08X}', hex_to_write)
        new_PAD_instrucs = phase2_get_instrucs_for_write(addr, hex_to_write)
        PAD_write_instrucs += new_PAD_instrucs
    
    PAD_cache_instrucs = phase2_get_cache_instrucs_from_AH_pairs(addr_hex_pairs)
    return PAD_write_instrucs + PAD_cache_instrucs


# Create phase 2 binary file from list of (address, hex_to_write) pairs
def phase2_create_bin_from_AH_pairs(phase2_addr_hex_pairs, phase2_bin_file, ks = None):
    PAD_instruc_list = phase2_get_PAD_instruction_list(phase2_addr_hex_pairs)
    #print(PAD_instruc_list)
    with open(phase2_bin_file,'wb') as f:
        for n, PAD_instruc in enumerate(PAD_instruc_list):
            #print(PAD_instruc)
            PAD_addr = 0x803F0F34 + 8*(n % 4)
            PAD_instruc_bytes = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='bytes')   # will need to edit addr if we do any non brl/bctrl branches during phase 2
            f.write(PAD_instruc_bytes)


    

# Create phase 2 binary file from list of mod files that contain (address, value) pairs
def phase2_create_bin_from_files(phase2_file_list, phase2_bin_file, ks = None):
    phase2_AH_pairs = get_addr_value_pairs_from_files(phase2_file_list, output_type='hex', ks=ks)
    phase2_create_bin_from_AH_pairs(phase2_AH_pairs, phase2_bin_file, ks=ks)


####################################################################################################
# Convert phase 1/2 binary files to csv files that Trog can use to operate the USB Gecko on console
####################################################################################################
# Each phase 1 write has a ~20% chance to fail (write/execute collision), so likely need to perform each one several times (10 is more than enough)
def phase1_bin_to_csv(binfile, csvfile):
    with open(binfile,'rb') as f_in, open(csvfile,'w') as f_out:
        # Phase 0.5: nop out all 4 controllers' button/left stick data (pads 3-4 need to already be harmless before this, but might as well ensure their exact values)
        for n in range(4):
            button_addr = 0x803F0F30 + n*0x08
            f_out.write(f"0x{button_addr:08X}, 0x10808080\n")

        # nop out controller 1 C-stick/trigger data (could wait until phase 1.5, but might as well do it now)    
        f_out.write(f"0x803F0F34, 0x60000000\n")
        
        # Phase 1 proper: Write bytes from phase1.bin to pad 2 C/LR data to set up input detection & caching for phase 2 (main payload)
        input_bytes = f_in.read()
        instructions = [input_bytes[i:i+4] for i in range(0, len(input_bytes), 4)]
        for instruction in instructions:
            f_out.write(f"0x803F0F3C, 0x{instruction.hex().upper()}\n")
        
        # Phase 1.5: Transition to phase 2 (main payload)
        f_out.write(f"0x803F0F44, 0x60000000\n")    # pad 3 (remove phase 1 caching)
        f_out.write(f"0x803F0F4C, 0x60000000\n")    # pad 4 (remove b -> pad 2)
        f_out.write(f"0x803F0F3C, 0x60000000\n")    # pad 2

# Phase 2 writes the main payload & each write should only need to be performed once
def phase2_bin_to_csv(binfile, csvfile):
    with open(binfile,'rb') as f_in, open(csvfile,'w') as f_out:
        input_bytes = f_in.read()
        instructions = [input_bytes[i:i+4] for i in range(0, len(input_bytes), 4)]
        for n, instruction in enumerate(instructions):
            pad_idx = n % 4
            pad_address = 0x803F0F34 + (pad_idx * 0x08)  # controller C-stick/LR address
            f_out.write(f"0x{pad_address:08X}, 0x{instruction.hex().upper()}\n")
        #f_outwrite(f"0x803F0F4C, 0x4BE24718")  # branch to safety ('phase 3')
        

#######################################################################################
# Dump from file to specific target address
#######################################################################################
def dump_bytes_PAD_instrucs(addr_target, data_bytes, r_min = 14, r_addr = 8):
    Nbytes = len(data_bytes)
    if Nbytes % 4 != 0:
        raise ValueError("WARNING: Can't dump fractional number of words, should edit function")
    words = [data_bytes[i:i+4].hex().upper() for i in range(0, len(data_bytes), 4)]
    Nwords = len(words)
    
    #addr_base, addr_off = split_addr(addr_target)
    addr_hex = f'{addr_target:08X}'

    PAD_instrucs = [f"lis {r_addr}, 0x{addr_hex[:4]}", 
                    f"ori {r_addr}, {r_addr}, 0x{addr_hex[4:]}"]    # set r_addr

    A_min = max(r_min, 32 - Nwords)    # in case there's fewer than 18 words (72 bytes) in the file
    A = A_min
    for n, word in enumerate(words):
        PAD_instrucs += [f"lis r{A}, 0x{word[:4]}",
                         f"ori r{A}, r{A}, 0x{word[4:]}"]
        A += 1
        if A == 32:
            PAD_instrucs += [f"stmw r{A_min}, 0 ({r_addr})"] # needs to be controller 4
            Nwords_left = Nwords - (n + 1)
            if Nwords_left == 0:
                return PAD_instrucs
            addr_target += (32-A_min)*4
            #addr_base, addr_off = split_addr(addr_target)
            addr_hex = f'{addr_target:08X}'
            PAD_instrucs += [f"lis {r_addr}, 0x{addr_hex[:4]}", 
                             f"ori {r_addr}, {r_addr}, 0x{addr_hex[4:]}"]
            A_min = max(r_min, 32 - Nwords_left)
            A = A_min
    raise ValueError("Error in register indexing")

# Create csv
def create_csv_for_file_dump(addr_target, binfile, csvfile, r_min = 14, r_addr = 8, ks=None):
    with open(binfile, 'rb') as f:
        input_bytes = f.read()
    PAD_instrucs = dump_bytes_PAD_instrucs(addr_target, input_bytes, r_min = r_min, r_addr = r_addr)
    PADs = [0x803F0F34 + 8*n for n in range(4)]
    nop = "0x60000000"
    with open(csvfile,'w') as f:
        n = 0
        for PAD_instruc in PAD_instrucs:
            if PAD_instruc[:4] == 'stmw':
                for j in range(n,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                PAD_addr = PADs[3]
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
                for j in range(4):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                n = 0
            else:
                PAD_addr = PADs[n]
                n = (n+1) % 4
            PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
            f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
            #print(f"0x{PAD_addr:08X}, {PAD_instruc}")

####################################################################################################
# Allocate memory for data in a specified heap, then dump hboots data from .bdl file to that memory
####################################################################################################
def hboots_dump_PAD_instrucs(heapName, data_bytes, ppData, r_min = 17, r_addr = 16):
    Nbytes = len(data_bytes)
    if Nbytes % 4 != 0:
        raise ValueError("WARNING: Can't dump fractional number of words, should edit function")
    words = [data_bytes[i:i+4].hex().upper() for i in range(0, len(data_bytes), 4)]
    Nwords = len(words)

    # Get ppHeap
    heap_dict = {'Game':0x803F6920, 'Zelda':0x803F6928, 'Command':0x803F6930, 'Archive':0x803F6938}
    ppHeap = heap_dict[heapName]
    ppHeap_base, ppHeap_off = split_addr(ppHeap)
    #ppHeap_hex = f'{ppHeap:08X}'

    # Get total allocation size = Nbytes (data) + 228 (J3DModelData); could potentially add 2*264 (right+left J3DModel)
    alloc_size = Nbytes #+ 228
    
    size_hex = f'{alloc_size:08X}'
    Nbytes_hex = f'{Nbytes:08X}'
    ppData_hex = f'{ppData:08X}'
    ppModelData_hex = f'{ppData+4:08X}'

    ###################################
    # Allocate memory in heapName
    PAD_instrucs = []
    
    # Set r3 = total allocation size = Nbytes (data) + 228 (J3DModelData)
    PAD_instrucs += [f"lis r23, 0x{size_hex[:4]}" ,
                    f"ori r23, r23, 0x{size_hex[4:]}"]

    # Set r4 = 0x20 (alignment amount + head vs tail)
    PAD_instrucs += [f"li r24, 0x20"]

    # Set r5 = pHeap
    PAD_instrucs += [f"lis r25, 0x{ppHeap_base:04X}", 
                    f"lwz r25, {ppHeap_off} (r25)"]
    
    # Set r_addr = pTarget = JKRHeap::alloc(Nbytes, 4, pHeap)
    PAD_instrucs += ["bl -> 0x803F0F74" ,    # allocation code set up in phase 1
                     f'mr {r_addr}, r26' ]
    
    # Store pData = pTarget at ppData
    PAD_instrucs += [f'stw r26, {ppData-0x803F0F3C} (r12)']

    # Store pModelData = pData + Nbytes at ppData+4              
    PAD_instrucs += [f'lis r23, 0x{Nbytes_hex[:4]}' ,
                     f'ori r23, r23, 0x{Nbytes_hex[4:]}' ,
                     f'add r27, r26, r23' ,
                     f'stw r27, {ppData+4 - 0x803F0F3C} (r12)']
    
    #return PAD_instrucs
    
    ###################################
    # Do hboots.bdl data dump
    A_min = max(r_min, 32 - Nwords)    # in case there's fewer than 18 words (72 bytes) in the file
    A = A_min
    for n, word in enumerate(words):
        PAD_instrucs += [f"lis r{A}, 0x{word[:4]}",
                         f"ori r{A}, r{A}, 0x{word[4:]}"]
        A += 1
        if A == 32:
            PAD_instrucs += [f"stmw r{A_min}, 0 ({r_addr})"] # needs to be controller 4
            
            addr_increase = (32-A_min)*4
            PAD_instrucs += [f"addi {r_addr}, {r_addr}, {addr_increase}"]
            Nwords_left = Nwords - (n + 1)
            if Nwords_left == 0:
                #return PAD_instrucs
                break
            A_min = max(r_min, 32 - Nwords_left)
            A = A_min
    if Nwords_left != 0:
        raise ValueError("Error in register indexing")
    
    #return PAD_instrucs
    ###################################
    # Create J3DModelData with hboots_manager mod
    # Note: Can't directly run code here with PAD_instrucs due to r3 & r4 use in caching
    PAD_instrucs += ['bl -> 0x803312B0']
    
    return PAD_instrucs

# Create the csv for the hboots.bdl dump + J3DModelData creation
def create_csv_for_hboots_dump(heapName, binfile, ppData, csvfile, r_min = 17, r_addr = 16, ks=None):
    with open(binfile, 'rb') as f:
        data_bytes = f.read()
    PAD_instrucs = hboots_dump_PAD_instrucs(heapName, data_bytes, ppData, r_min = r_min, r_addr = r_addr)
    PADs = [0x803F0F34 + 8*n for n in range(4)]
    nop = "0x60000000"
    with open(csvfile,'w') as f:
        n = 0
        for PAD_instruc in PAD_instrucs:
            if PAD_instruc[:4] in 'stmw':
                for j in range(n,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                PAD_addr = PADs[3]
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
                for j in range(4):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                n = 0
            elif PAD_instruc[:5] == 'bl ->':
                for j in range(n,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                PAD_addr = PADs[3]
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
                for j in range(4):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                n = 0
            else:
                PAD_addr = PADs[n]
                n = (n+1) % 4
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
            #print(f"0x{PAD_addr:08X}, {PAD_instruc}")
        # Flush any straggler instructions and nop everything
        for k in range(4):
            j = (n+k) % 4
            f.write(f"0x{PADs[j]:08X}, {nop}\n")

#######################################################################################
# Convert a png to a csv that makes it a pictograph in game (7904 bytes)
#######################################################################################
def live_photo_dump_bytes_PAD_instrucs(CMPR_bytes, Nrefreshes=13, r_min=19, r_addr=18, r_base=17, r_save=16):
    Nbytes = len(CMPR_bytes)
    if Nbytes % 4 != 0:
        raise ValueError("WARNING: Can't dump fractional number of words, should edit function")
    words = [CMPR_bytes[i:i+4].hex().upper() for i in range(0, len(CMPR_bytes), 4)]
    Nwords = len(words)

    Nwords_per_refresh = 1976 // Nrefreshes
    if Nrefreshes * Nwords_per_refresh != 1976:
        raise ValueError("Nrefreshes needs to be a factor of 1,976=13*19*8")
    
    byte0 = CMPR_bytes[0] ^ 8   # flip lowest red bit of 1st CMPR byte after each draw update
    
    PAD_instrucs = []
    
    # Initiate controller 2-4 loop
    PAD_instrucs += ['NOPS',
                     'WAIT']
    
    # Save r31 for vanilla code
    PAD_instrucs += [f'mr r{r_save}, r31']

    # Set r_addr = r_base = pBufferPhoto (load from ppBufferPhoto = 0x803F68CC)
    PAD_instrucs += [f'lis {r_base}, 0x803F' ,
                     f'lwz {r_base}, 0x68CC ({r_base})' ,
                     f'mr {r_addr}, {r_base}']

    # Do CMPR data dump to pBufferPhoto
    A_min = max(r_min, 32 - Nwords)    # in case there's fewer than 18 words (72 bytes) in the file
    A = A_min
    Nwords_left = Nwords
    for n, word in enumerate(words):
        PAD_instrucs += [f"lis r{A}, 0x{word[:4]}",
                         f"ori r{A}, r{A}, 0x{word[4:]}"]
        A += 1
        if A == 32:
            addr_increase = (32-A_min)*4
            PAD_instrucs += [f"stmw r{A_min}, 0 ({r_addr})" , # needs to be controller 4
                             f"addi {r_addr}, {r_addr}, {addr_increase}"
                            ]
            Nwords_left = Nwords - (n + 1)
            A_min = max(r_min, 32 - Nwords_left)
            A = A_min
        if (n+1) % Nwords_per_refresh == 0:
            PAD_instrucs += [
                             f"li r10, {byte0}" ,
                             f"stb r10, 0 ({r_base})" , # change 1st CMPR byte to trigger redraw
                             f'mr r31, r{r_save}' ,     # restore r31 for vanilla code
                             "b -> 0x80006460" ,        # resume vanilla code to advance a frame
                             'NOPS' ,                   # trigger a new controller loop
                             'WAIT'
                            ]
            byte0 ^= 8  # flip lowest red bit of first CMPR byte so a photo redraw gets triggered
            if Nwords_left == 0:
                #return PAD_instrucs
                break
    if Nwords_left != 0:
        raise ValueError("Error in register indexing")
    
    PAD_instrucs += [
                    f"li r10, {byte0}" ,
                    f"stb r10, 0 ({r_base})" ,  # change 1st CMPR byte to trigger redraw
                    f'mr r31, r{r_save}' ,        # restore r31 for vanilla code
                    "b -> 0x80006460"]    # resume vanilla code to advance a frame
    return PAD_instrucs

# Create csv for CMPR data dump, staggered to only do so many bytes at time for live image update
def create_csv_for_photo_dump(CMPR_bytes, csvfile, Nrefreshes=13, r_min = 19, r_addr = 18, r_base = 17, r_save = 16, ks=None):
    # with open(CMPRfile, 'rb') as f:
    #     CMPR_bytes = f.read()
    
    PAD_instrucs = live_photo_dump_bytes_PAD_instrucs(CMPR_bytes, Nrefreshes=Nrefreshes, r_min=r_min, r_addr=r_addr, r_base=r_base, r_save=r_save)
    PADs = [0x803F0F34 + 8*n for n in range(4)]
    nop = "0x60000000"
    #branch = "0x803F0F4C, 0x4BC15514\n"   # b -> 0x80006460 to do a frame update
    with open(csvfile,'w') as f:
        n = 1
        for PAD_instruc in PAD_instrucs:
            if PAD_instruc[:4] == 'stmw':
                for j in range(n,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                PAD_addr = PADs[3]
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
                for j in range(1,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                    #print(f"0x{PADs[j]:08X}, nop")
                n = 1
            elif PAD_instruc[:4] == 'b ->':  
                for j in range(n,3):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                PAD_addr = PADs[3]
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")   # b -> 0x80006460 to do a frame update
                n = 1
            elif PAD_instruc == 'NOPS':
                for j in range(1,4):
                    f.write(f"0x{PADs[j]:08X}, {nop}\n")
                n = 1
            elif PAD_instruc == 'WAIT':    
                f.write('WAIT A FRAME\n')
                n = 1
            else:
                PAD_addr = PADs[n]
                n = max(1, (n+1)%4)
                PAD_word = get_ASM_encoding(PAD_instruc, addr=PAD_addr, ks=ks, output_type='hex')
                f.write(f"0x{PAD_addr:08X}, 0x{PAD_word}\n")
                #print(f"0x{PAD_addr:08X}, {PAD_instruc}")
        # for j in range(1,3):
        #     f.write(f"0x{PADs[j]:08X}, {nop}\n")
        # f.write(branch) #BLEH

#######################################################################################
# Convert a png to a csv that uploads it into buffer pictograph data (7904 bytes)
#######################################################################################
def png_to_csv(png_file, csv_file, Nrefreshes=247, r_min=19, r_addr=18, r_base=17, r_save=16, ks=None):
    cmpr_data = picto.image_to_CMPR(png_file, out_file=None, width=152, height=104, resize_if_needed=True)
    create_csv_for_photo_dump(cmpr_data, csv_file, Nrefreshes=Nrefreshes, r_min=r_min, r_addr=r_addr, r_base=r_base, r_save=r_save, ks=ks)


#######################################################################################
# Automatically format addresses in mod files so we don't need to set them manually 
#######################################################################################
def format_mod(infile, start_addr: int, outfile):
    with open(infile, 'r') as f1:
        text = f1.read()
        lines = text.splitlines()

    # First pass: determine label addresses
    labels = {}
    current_addr = start_addr

    for line in lines:
        stripped = line.strip()

        # Label definition
        if stripped.endswith(":") and not stripped.startswith("#") and not is_hex(stripped[:-1]):
            label = stripped[:-1]
            labels[label] = current_addr
            #print(label, f'{current_addr:08X}')
            continue

        # Instruction line (heuristic: starts with opcode or has registers)
        if stripped and not stripped.startswith("#") and not is_hex(stripped[:8]):
            current_addr += 4

    # Second pass: emit output
    output = []
    current_addr = start_addr

    for line in lines:
        stripped = line.strip()
        # is_label_line = stripped.endswith(":") and stripped[:-1] in labels
        # if is_label_line:
        #     continue

        # Label definition → address label
        if stripped.endswith(":") and not stripped.startswith("#") and not is_hex(stripped[:-1]):
            label = stripped[:-1]
            #output.append(f"{labels[label]:08X}:   {''}".rstrip())
            continue

        # Replace branch targets
        def replace_label(match):
            lbl = match.group(1)
            return f"-> 0x{labels[lbl]:08X}"

        if not stripped.startswith('#'):
            line = re.sub(r"->\s*([A-Za-z_][A-Za-z0-9_]*)", replace_label, line)
    
        # If this is an instruction, prefix address (unless it already has one)
        if stripped and not stripped.startswith("#") and not is_hex(stripped[:8]):
            #print('aah', stripped)
            output.append(f"{current_addr:08X}:   {line.strip()}")
            current_addr += 4
        else:
            #print('bleh', line)
            output.append(line)

    out_text = "\n".join(output)
    with open(outfile, 'w') as f2:
        f2.write(out_text)
    return current_addr     # address immediately afterwards


#######################################################################################
# Old way I used to create bytes files
#######################################################################################
# # Get bytes list from a file of hex words
# def hexfile2bytes(hexfile):
#     instructions = []
#     with open(hexfile) as f:
#         for line in f:
#             hex_word = line.split('#', 1)[0].strip()    # remove comments & whitespace
#             if hex_word:
#                 #print(hex_word)
#                 instruction = bytes.fromhex(hex_word)
#                 instructions.append(instruction)
#     return instructions

# def create_bytes_file(bytes_list, bytes_filename):
#     with open(bytes_filename, 'wb') as f:
#         for word_bytes in bytes_list:
#             f.write(word_bytes)

#######################################################################################
# Old ASM -> hex/bin functions
#######################################################################################
# # Return hex for "source: b -> target" instructions (should be redundant with Keystone asm)
# def branch_hex(target, source=0x803F0F44):
#     target = int(target, 16) if isinstance(target,str) else target
#     source = int(source, 16) if isinstance(source,str) else source
#     off = target - source
#     if off < 0:
#         off += 0x04000000
#     out = 0x48000000 + off
#     return f'{out:08X}'

# # Same but return binary string
# def branch_bin(target, source):
#     hex_str = branch_hex(target, source)
#     return format_bin(int(hex_str, 16))


# # Return hex for lwz instruction (should be redundant with Keystone asm)
# def lwz_hex(D, A=12, offset=0x8):
#     opcode_bin = '100000' # lwz opcode in binary
#     D_bin = bin(D)[2:].zfill(5)
#     A_bin = bin(A)[2:].zfill(5)
#     if offset < 0:
#         offset += 0x10000
#     offset_bin = bin(offset)[2:].zfill(16)
#     instruction_bin = opcode_bin + D_bin + A_bin + offset_bin
#     instruction_hex = hex(int(instruction_bin, 2)).upper().zfill(8)
#     return instruction_hex


