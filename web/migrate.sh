#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
migrations_dir="$script_dir/migrations"
database_path="$script_dir/database.db"


go run -tags sqlite3 github.com/golang-migrate/migrate/v4/cmd/migrate@v4.19.1 \
    -path "$migrations_dir" \
    -database "sqlite3://$database_path" \
    up
