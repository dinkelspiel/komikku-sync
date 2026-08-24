## SPDX-FileCopyrightText: 2019-2025 Valéry Febvre
## SPDX-License-Identifier: GPL-3.0-or-later

BUILD := _build
BUILD2 := _build2
CLIENT_ROOT := $(abspath .komikku-dev)

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help:
	@python3 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

setup:  ## Setup build folder.
	meson setup . $(BUILD)

local:  ## Configure a local build.
	meson configure $(BUILD) -Dprefix=$$(pwd)/$(BUILD)/testdir

develop:  ## Configure a local build with debugging.
	meson configure $(BUILD) -Dprefix=$$(pwd)/$(BUILD)/testdir -Dprofile=development

run:  ## Run the local build.
	ninja -C $(BUILD) install
	mkdir -p $(CLIENT_ROOT)/client1/data $(CLIENT_ROOT)/client1/cache $(CLIENT_ROOT)/client1/config
	XDG_DATA_HOME=$(CLIENT_ROOT)/client1/data XDG_CACHE_HOME=$(CLIENT_ROOT)/client1/cache XDG_CONFIG_HOME=$(CLIENT_ROOT)/client1/config GSETTINGS_BACKEND=keyfile ninja -C $(BUILD) run

$(BUILD2)/build.ninja:
	meson setup . $(BUILD2) -Dprefix=$(abspath $(BUILD2)/testdir) -Dprofile=beta

run2: $(BUILD2)/build.ninja  ## Run a second isolated client.
	ninja -C $(BUILD2) install
	mkdir -p $(CLIENT_ROOT)/client2/data $(CLIENT_ROOT)/client2/cache $(CLIENT_ROOT)/client2/config
	XDG_DATA_HOME=$(CLIENT_ROOT)/client2/data XDG_CACHE_HOME=$(CLIENT_ROOT)/client2/cache XDG_CONFIG_HOME=$(CLIENT_ROOT)/client2/config GSETTINGS_BACKEND=keyfile ninja -C $(BUILD2) run

install:  ## Install system-wide.
	ninja -C $(BUILD) install

test:  ## Run tests.
	ninja -C $(BUILD) install
	ninja -C $(BUILD) test
	TEST_PATH=$(TEST_PATH) ninja -C $(BUILD) tests

clean:  ## Clean build files.
	rm -rf $(BUILD) $(BUILD2)
