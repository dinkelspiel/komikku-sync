-- SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
-- SPDX-License-Identifier: GPL-3.0-or-later
CREATE TABLE
    IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    );

CREATE INDEX IF NOT EXISTS sessions_token_idx ON sessions (token);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);
