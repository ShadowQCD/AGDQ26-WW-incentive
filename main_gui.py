import tkinter as tk
# from tkinter import ttk
# from tkinter import filedialog
from pathlib import Path
from time import sleep, time

import dolphin_memory_engine as DME
from keystone import Ks, KS_ARCH_PPC, KS_MODE_PPC64

import helper_funcs as HF


############################################################
# CONSTANTS
############################################################
# PAD1_addr = 0x803F0F34  # controller 1 C/LR data address
# PAD2_addr = 0x803F0F3C  # controller 2 C/LR data address (also r12)
# PAD3_addr = 0x803F0F44  # controller 3 C/LR data address
# PAD4_addr = 0x803F0F4C  # controller 4 C/LR data address

payload_folder      = Path.cwd() / "payload_mods"
model_folder        = Path.cwd() / "model_files"

csv_folder          = Path.cwd() / "csv_files"
model_csv_folder    = Path.cwd() / "model_csv_files"

phase_1_AI_file     = "phase1_addr_instruc_pairs.txt"
phase_1_bin_file    = "phase1.bin"
phase_2_bin_file    = "phase2.bin"

phase_m1_csv_file   = "phase_m1.csv"
phase_1_csv_file    = "phase_1.csv"
phase_2_csv_file    = "phase_2.csv"
phase_3_csv_file    = "phase_3.csv"

phase_m1_csv_path   = csv_folder / phase_m1_csv_file
phase_1_csv_path    = csv_folder / phase_1_csv_file
phase_2_csv_path    = csv_folder / phase_2_csv_file
phase_3_csv_path    = csv_folder / phase_3_csv_file

model_addr_file_pairs = [   (0x80332000, model_folder/"custom"/"hboots_Toad.bdl") ,
                            #(0x803318C0, model_folder/"iron_boots"/"JKRMemArchive.bin") ,
                            #(0x80331940, model_folder/"iron_boots"/"Vboot.rarc") ,
                        ]

# Set number of times to perform each DME write in each phase
phase_m1_Nreps  = 3     # should only need to be 1
phase_1_Nreps   = 10    # each DME write in phase 1 has a ~20% chance to occur while that line is being executed, so P(success) ~ (1-.2**Nreps)**Ninstructions
phase_2_Nreps   = 3     # should only need to be 1, but have been experiencing weird issues
phase_25_Nreps  = 3     # this is where the real issues have been, maybe stmw timing issues
phase_3_Nreps   = 3     # should only need to be 1

# GUI color scheme
BG = "#2e2e2e"
FG = "#FFFFFF"

ks = Ks(KS_ARCH_PPC, KS_MODE_PPC64)

############################################################
# LOGGING SUPPORT
############################################################
def log(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)

############################################################
# DME Write Wrappers
############################################################
def my_DME_write(addr, word, pause=0.001, Nreps=1, showlog=True):
    addr, word = HF.addr_value_converter(addr, word, 'int')
    for _ in range(Nreps):
        DME.write_word(addr, word)
        sleep(pause)
    # Nreps = 1
    # while True:
    #     DME.write_word(addr, word)
    #     sleep(pause)
    #     check = DME.read_word(addr)
    #     if check == word:
    #         break
    #     Nreps += 1
    #     sleep(pause)
        
    if showlog:
        log(f"Wrote 0x{word:08X} to 0x{addr:08X} (x{Nreps})")

def my_DME_writes_from_csv(csv_path, Nreps=1):
    with open(csv_path,'r') as f:
        lines = f.readlines()
        Nwords = len(lines)
        
        full_log = False # (Nwords < 100)
        t0 = time()
        for n, line in enumerate(lines):
            PAD_addr, word = line.strip().replace(' ','').split(",")
            my_DME_write(PAD_addr, word, Nreps=Nreps, showlog=full_log)
            
            # if not full_log:
            #     # Log progress every 10%
            #     progress = (n + 1) / Nwords
            #     if progress % 0.1 < (1 / Nwords):
            #         log(f"Progress: {progress*100:.0f}%")
        log(f"Finished {csv_path.name} writes in {time()-t0:.1f} s")
            
                
############################################################
# HOOK TO DOLPHIN
############################################################
def hook_to_dolphin():
    log("Attempting to hook to Dolphin...")

    try:
        DME.hook()
        sleep(0.2)  # small delay so DME updates state

        if not DME.is_hooked():
            log("❌ Failed to hook to Dolphin.")
            return

        iso = DME.read_bytes(0x80000000, 6)
        if iso != b'GZLE01':
            log(f"❌ Wrong ISO detected: {iso}. Expected GZLE01.")
            return

        log("✅ Successfully hooked to Dolphin (GZLE01 detected).\n")
        
        log("Follow this procedure:")

        log("-Phase -1: Set controllers 2-4 (manually or click 'Phase -1' button)")
        log("-Phase 0:  Trigger ACE (recommended to set a save state beforehand)")
        #log("- Phase 0.5: Transition into Phase 1")
        log("-Phase 1:  Set up input detection & caching for phase 2")
        #log("- Phase 1.5: Transition into Phase 2")
        log("-Phase 2:  Write main payload from phase2.bin (select mods & regenerate first)")
        log("-Phase 3:  Resume gameplay\n")
        
        # log("Select which 'Main Payload Files' to include in Phase 2 and click 'Regenerate phase2.bin'\n")
        # log("While in holding loop, click 'Phase 0.5' - 'Phase 3' in sequence to execute payload and resume gameplay.\n")
        
        # Optional: disable the button once hooked
        #hook_btn.config(state="disabled")

    except Exception as e:
        log(f"❌ Error while hooking: {e}")

############################################################
# LOAD PAYLOAD FILES AND BUILD CHECKBOXES
############################################################
payload_vars = {}
payload_files = sorted(payload_folder.iterdir())

def rebuild_phase2_bin():
    selected_files = [f for f,v in payload_vars.items() if v.get()==1]
    log(f"Rebuilding {phase_2_bin_file} with:")
    for s in selected_files:
        log(f"  - {s.name}")

    HF.phase2_create_bin_from_files(
        selected_files,
        phase_2_bin_file,
        #input_type="hex",
        ks=ks
    )
    
    HF.phase2_bin_to_csv(phase_2_bin_file, phase_2_csv_path)
    log(f"{phase_2_bin_file}, {phase_2_csv_file} regenerated.\n")

########################################################################
# Create phase 1 binary file from file of (address, instruction) pairs
########################################################################
def rebuild_phase1_bin():
    phase1_AI_pairs = HF.get_addr_value_pairs_from_files(phase_1_AI_file, output_type='ASM', ks=ks)
    HF.phase1_create_bin(phase1_AI_pairs, phase_1_bin_file, ks=ks)
    HF.phase1_bin_to_csv(phase_1_bin_file, phase_1_csv_path)
    log(f"{phase_1_bin_file}, {phase_1_csv_file} regenerated.\n")


########################################################################
# Create phase 2.5 (ARC Dump) csv file from ARC file and target address
########################################################################
def rebuild_model_csv_files():
    for addr, f in model_addr_file_pairs:
        csv_filename = f.stem + ".csv"
        csv_path = csv_folder / csv_filename
        HF.create_csv_for_file_dump(addr, f, csv_path, r_min = 17, r_addr = 16, ks=None)
        log(f"{csv_filename} regenerated.\n")


############################################################
############################################################
# PHASE FUNCTIONS
############################################################
############################################################

######################################################################################################
# PHASE -1 (pre-ACE): Set controllers 2-4 at start (optional, can manually set before the run instead)
######################################################################################################
def run_phase_m1():
    log(f"Running Phase -1... (Nreps={phase_m1_Nreps})")
    # # nop out controller 2-4 button/left stick data (will be different if using unplug strats; need to test)
    # for n in range(3):
    #     button_addr = 0x803F0F38 + n*0x08
    #     my_DME_write(button_addr, button_nop)

    # my_DME_write(PAD2_addr, nop)       # clear pad 2 C/LR data
    # my_DME_write(PAD3_addr, icbi_r12)  # invalidate instruction cache at r12=0x803F0F3C so that the CPU sees updates to pad 2 C/LR data
    # my_DME_write(PAD4_addr, b_42)      # branch from pad 4 -> pad 2; main loop for phase 1
    
    my_DME_writes_from_csv(phase_m1_csv_path, Nreps=phase_m1_Nreps)
    log("Phase -1 complete.\n")

######################################################################################################
# PHASE 0: Trigger ACE
######################################################################################################
# def run_phase_0():
#     log("Running Phase 0...")
#     #my_DME_write(0x8039D778, 0x803F0F3C)
#     #my_DME_writes_from_csv('phase_0_hack.csv', Nreps=1)
#     log("Phase 0 complete.\n")

################################################################################
# PHASE 1: Set up input detection & cache management for phase 2 (main payload)
################################################################################
def run_phase_1():
    log(f"Running Phase 1... (Nreps={phase_1_Nreps})")
    my_DME_writes_from_csv(phase_1_csv_path, Nreps=phase_1_Nreps)
    log("Phase 1 complete.\n")
    
    # my_DME_write(0x8039D778, 0x802D5820)
    # my_DME_write(0x803F0F4C, HF.get_ASM_encoding('bl -> 0x802D5820', addr=0x803F0F4C, ks=ks))
    

##################################################################
# PHASE 2: Write main payload using pads 1-4 and resume gameplay
##################################################################
def run_phase_2():
    log(f"Running Phase 2... (Nreps={phase_2_Nreps})")
    my_DME_writes_from_csv(phase_2_csv_path, Nreps=phase_2_Nreps)
    log("Phase 2 complete.\n")


def run_phase_25():
    log(f"Running Phase 2.5... (Nreps={phase_25_Nreps})")
    for addr, f in model_addr_file_pairs:
        csv_filename = f.stem + ".csv"
        csv_path = csv_folder / csv_filename
        my_DME_writes_from_csv(csv_path, Nreps=phase_25_Nreps)
    log("Phase 2.5 complete.\n")


#################################################################################################
# PHASE 3 (old, now included in phase 2): Perform any cleanup (if necessary) and resume gameplay
#################################################################################################
def run_phase_3():
    log(f"Running Phase 3... (Nreps={phase_3_Nreps})")
    my_DME_writes_from_csv(phase_3_csv_path, Nreps=phase_3_Nreps)
    log("Phase 3 complete.\n")


############################################################################
############################################################################
# TKINTER GUI LAYOUT
############################################################################
############################################################################
root = tk.Tk()
root.title("Wind Waker ACE Controller Payload GUI")
root.configure(bg=BG)
############################################################
# 'Hook to Dolphin' Button
############################################################
hook_frame = tk.Frame(root, bg=BG)
hook_frame.pack(padx=10, pady=5, fill="x")

hook_btn = tk.Button(
    hook_frame,
    text="Hook to Dolphin",
    command=hook_to_dolphin,
    # bg=BG,
    # fg=FG,
    # activebackground=BG,
    # activeforeground=FG
)
hook_btn.pack()

############################################################
# Phase Buttons
############################################################
phase_frame = tk.LabelFrame(root, text="Phases", padx=10, pady=10, bg=BG, fg=FG)
phase_frame.pack(padx=10, pady=10, fill="x")

btn_m1  = tk.Button(phase_frame, text="Phase -1: Set PADs 2-4",   command=run_phase_m1)
#btn_0   = tk.Button(phase_frame, text="Phase 0: Trigger ACE", command=run_phase_0)
btn_0   = tk.Button(phase_frame, text="Phase 0: Trigger ACE", state="disabled")
#btn_05  = tk.Button(phase_frame, text="Phase 0.5", command=run_phase_05)
btn_1   = tk.Button(phase_frame, text="Phase 1: Setup",   command=run_phase_1)
#btn_15  = tk.Button(phase_frame, text="Phase 1.5", command=run_phase_15)
btn_2   = tk.Button(phase_frame, text="Phase 2: Main Payload",   command=run_phase_2)
btn_25   = tk.Button(phase_frame, text="Phase 2.5: Model Data",   command=run_phase_25)
btn_3   = tk.Button(phase_frame, text="Phase 3: Resume Game",   command=run_phase_3)

#for b in (btn_m1, btn_05, btn_1, btn_15, btn_2, btn_3):
for b in (btn_m1, btn_0, btn_1, btn_2, btn_25, btn_3):
    b.pack(side="left", padx=5)


############################################################
# Mods selector frame with 'Regenerate phase2.bin' button
############################################################
files_frame = tk.LabelFrame(root, text="Main Payload Mod Files", padx=10, pady=10, bg=BG, fg=FG)
files_frame.pack(padx=10, pady=10, fill="both")

for f in payload_files:
    var = tk.IntVar(value=1)
    payload_vars[f] = var
    tk.Checkbutton(files_frame, text=f.name, variable=var,
                   bg=BG, fg=FG, selectcolor=BG, activebackground=BG, activeforeground=FG
                   ).pack(anchor='w')

regen_btn = tk.Button(files_frame, text=f"Regenerate {phase_2_bin_file}", command=rebuild_phase2_bin)
regen_btn.pack(pady=5)

#####################################
# 'Regenerate phase1.bin' button
#####################################
regen1_btn = tk.Button(files_frame, text=f"Regenerate {phase_1_bin_file}", command=rebuild_phase1_bin)
regen1_btn.pack(side='right', padx=5)

#####################################
# 'Regenerate phase25.csv' button
#####################################
regen25_btn = tk.Button(files_frame, text=f"Regenerate model csv files", command=rebuild_model_csv_files)
regen25_btn.pack(side='right')

############################################################
# Log output widget
############################################################
log_frame = tk.LabelFrame(root, text="Log Output", bg=BG, fg=FG)
log_frame.pack(padx=10, pady=10, fill="both", expand=True)

log_box = tk.Text(log_frame, height=15, bg="#666666", fg="#26FF13")
log_box.pack(fill="both", expand=True)

#log("GUI Ready.")
log("Make sure ports 2-4 are set to 'None' in Dolphin controller settings.\n")
log("While game is running, click 'Hook to Dolphin' to begin.\n")

root.mainloop()
