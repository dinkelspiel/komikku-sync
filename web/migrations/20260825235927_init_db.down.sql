-- SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
-- SPDX-License-Identifier: GPL-3.0-or-later
DROP INDEX IF EXISTS sessions_user_id_idx;

DROP INDEX IF EXISTS sessions_token_idx;

DROP TABLE IF EXISTS sessions;

DROP INDEX IF EXISTS state_versions_user_id_idx;

DROP TABLE IF EXISTS state_versions;

DROP TABLE IF EXISTS users;
