#---------------------------------------------------------------------------------
.SUFFIXES:
#---------------------------------------------------------------------------------
ifeq ($(strip $(DEVKITARM)),)
$(error "Please set DEVKITARM in your environment. export DEVKITARM=<path to>devkitARM")
endif

export TARGET	:=	usb-display
export TOPDIR	:=	$(CURDIR)

# specify a directory which contains the nitro filesystem
# this is relative to the Makefile
NITRO_FILES	:=

# These set the information text in the nds file
GAME_TITLE     := USB Display Example
GAME_SUBTITLE1 := DSpico
GAME_SUBTITLE2 := tinkerizer
GAME_ICON	   := icon.bmp

include $(DEVKITARM)/ds_rules

.PHONY: buildid checklibtwl checkarm7 checkarm9 clean push

#---------------------------------------------------------------------------------
# main targets
#---------------------------------------------------------------------------------
all: buildid checklibtwl checkarm7 checkarm9 $(TARGET).nds

#---------------------------------------------------------------------------------
buildid:
	../tools/gen_build_id.sh

#---------------------------------------------------------------------------------
checklibtwl: buildid
	$(MAKE) -C ../libs/libtwl/libtwl7
	$(MAKE) -C ../libs/libtwl/libtwl9

#---------------------------------------------------------------------------------
checkarm7: checklibtwl
	$(MAKE) -C arm7

#---------------------------------------------------------------------------------
checkarm9: checklibtwl
	$(MAKE) -C arm9

#---------------------------------------------------------------------------------
$(TARGET).nds	: $(NITRO_FILES) arm7/$(TARGET).elf arm9/$(TARGET).elf
	ndstool	-c $(TARGET).nds -7 arm7/$(TARGET).elf -9 arm9/$(TARGET).elf \
	-b $(GAME_ICON) "$(GAME_TITLE);$(GAME_SUBTITLE1);$(GAME_SUBTITLE2)" \
	$(_ADDFILES)
	dlditool ../libs/dsupdate/DSpico.dldi $(TARGET).nds

#---------------------------------------------------------------------------------
arm7/$(TARGET).elf:
	$(MAKE) -C arm7

#---------------------------------------------------------------------------------
arm9/$(TARGET).elf:
	$(MAKE) -C arm9

#---------------------------------------------------------------------------------
# Build, then send to the running DS over USB. See tools/dsctl.py.
push: all
	../tools/ds push

#---------------------------------------------------------------------------------
clean:
	$(MAKE) -C arm9 clean
	$(MAKE) -C arm7 clean
	rm -f $(TARGET).nds $(TARGET).arm7 $(TARGET).arm9
