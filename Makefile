VERSION  ?= 1.0
RELEASE  ?= 1
SPECFILE  = SPECS/lrn-transfer.spec
NAME      = lrn-transfer

GREEN  := \033[1;32m
NC     := \033[0m

.PHONY: all rpm tarball fetch-deps clean distclean help

all: rpm

help:
	@echo "Targets:"
	@echo "  fetch-deps   Download Python wheels (needs internet)"
	@echo "  rpm          Build RPM (run fetch-deps first)"
	@echo "  tarball      Build source tarball only"
	@echo "  clean        Remove build artifacts (keep wheels)"
	@echo "  distclean    Remove everything including SOURCES/wheels/"

fetch-deps:
	@echo -e "$(GREEN)[*]$(NC) Fetching Python dependencies..."
	bash scripts/fetch-deps.sh

tarball:
	@echo -e "$(GREEN)[*]$(NC) Creating source tarball..."
	@mkdir -p SOURCES BUILD RPMS SRPMS
	tar czf SOURCES/$(NAME)-$(VERSION).tar.gz \
		--transform 's|^|$(NAME)-$(VERSION)/|' \
		--exclude='.git' \
		--exclude='SOURCES' \
		--exclude='BUILD' \
		--exclude='RPMS' \
		--exclude='SRPMS' \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		.
	@echo -e "$(GREEN)[+]$(NC) Tarball: SOURCES/$(NAME)-$(VERSION).tar.gz"

rpm: tarball
	@echo -e "$(GREEN)[*]$(NC) Building RPM..."
	rpmbuild -bb \
		--define "_topdir $(CURDIR)" \
		--define "_version $(VERSION)" \
		--define "_release $(RELEASE)" \
		$(if $(wildcard SOURCES/wheels),--define "_wheels_dir $(CURDIR)/SOURCES/wheels") \
		$(SPECFILE)
	@echo -e "$(GREEN)[+]$(NC) RPM built:"
	@ls -lh RPMS/x86_64/*.rpm

clean:
	@echo -e "$(GREEN)[*]$(NC) Cleaning build artifacts..."
	rm -rf BUILD/* RPMS/* SRPMS/* SOURCES/$(NAME)-$(VERSION).tar.gz
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	@echo -e "$(GREEN)[+]$(NC) Clean complete"

distclean: clean
	rm -rf SOURCES/wheels/
