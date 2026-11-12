IOP_BIN = empty.irx
IOP_OBJS = empty.o
IOP_CFLAGS += -Wall
IOP_INCS += -I$(PS2SDK)/iop/include -I$(PS2SDK)/common/include -I.

all: $(IOP_BIN)
clean:
	rm -f $(IOP_BIN) $(IOP_OBJS)

include $(PS2SDK)/Defs.make
include $(PS2SDK)/samples/Makefile.pref
include $(PS2SDK)/samples/Makefile.iopglobal
