SCRIPT  := llupdate-build.py
BINNAME := llupdate-build

PREFIX ?= /usr
bindir ?= $(PREFIX)/bin

INSTALL ?= install

.PHONY: all install

all: ;

install:
	$(INSTALL) -d $(DESTDIR)$(bindir)
	$(INSTALL) -m 0755 $(SCRIPT) $(DESTDIR)$(bindir)/$(BINNAME)
