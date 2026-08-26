// SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
// SPDX-License-Identifier: GPL-3.0-or-later

#import "jai-sqlite";

#import "Basic";

User :: struct {
	id: s64;
	username: string;
	password: string;
	created_at: string;
	updated_at: string;
}

State_Version :: struct {
	id: s64;
	user_id: s64;
	data: string;
	created_at: string;
}

Session :: struct {
	id: s64;
	user_id: s64;
	token: string;
	created_at: string;
}

users_find :: (database: *sqlite3, id: s64 = 0, username: string = "") -> User, bool {
	if id > 0 && username.count > 0 {
		user, found := users_find_query(database, "SELECT id, username, password, created_at, updated_at FROM users WHERE id = ? AND username = ? LIMIT 1", id, username);
		return user, found;
	}
	if id > 0 {
		user, found := users_find_query(database, "SELECT id, username, password, created_at, updated_at FROM users WHERE id = ? LIMIT 1", id);
		return user, found;
	}
	if username.count > 0 {
		user, found := users_find_query(database, "SELECT id, username, password, created_at, updated_at FROM users WHERE username = ? LIMIT 1", username);
		return user, found;
	}
	return .{}, false;
}

users_create :: (database: *sqlite3, username: string, password: string) -> User {
	user, _ := users_find_query(
		database,
		"INSERT INTO users (username, password) VALUES (?, ?) RETURNING id, username, password, created_at, updated_at",
		username,
		password,
	);
	return user;
}

users_update :: (database: *sqlite3, id: s64, username: string, password: string) -> User {
	if id <= 0 return .{};

	user, _ := users_find_query(
		database,
		"UPDATE users SET username = ?, password = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? RETURNING id, username, password, created_at, updated_at",
		username,
		password,
		id,
	);
	return user;
}

users_delete :: (database: *sqlite3, id: s64) -> bool {
	if id <= 0 return false;
	success, rows_changed, _ := sqlite3_exec_query(database, "DELETE FROM users WHERE id = ?", id);
	return success && rows_changed == 1;
}

free_user :: (user: *User) {
	free(user.username);
	free(user.password);
	free(user.created_at);
	free(user.updated_at);
	user.* = .{};
}

state_versions_find :: (database: *sqlite3, id: s64 = 0, user_id: s64 = 0) -> State_Version, bool {
	if id > 0 && user_id > 0 {
		state_version, found := state_versions_find_query(database, "SELECT id, user_id, CAST(data AS TEXT) AS data, created_at FROM state_versions WHERE id = ? AND user_id = ? LIMIT 1", id, user_id);
		return state_version, found;
	}
	if id > 0 {
		state_version, found := state_versions_find_query(database, "SELECT id, user_id, CAST(data AS TEXT) AS data, created_at FROM state_versions WHERE id = ? LIMIT 1", id);
		return state_version, found;
	}
	if user_id > 0 {
		state_version, found := state_versions_find_query(database, "SELECT id, user_id, CAST(data AS TEXT) AS data, created_at FROM state_versions WHERE user_id = ? ORDER BY id DESC LIMIT 1", user_id);
		return state_version, found;
	}
	return .{}, false;
}

state_versions_create :: (database: *sqlite3, user_id: s64, data: string) -> State_Version {
	if user_id <= 0 return .{};

	state_version, _ := state_versions_find_query(
		database,
		"INSERT INTO state_versions (user_id, data) VALUES (?, CAST(? AS BLOB)) RETURNING id, user_id, CAST(data AS TEXT) AS data, created_at",
		user_id,
		data,
	);
	return state_version;
}

state_versions_delete :: (database: *sqlite3, id: s64) -> bool {
	if id <= 0 return false;
	success, rows_changed, _ := sqlite3_exec_query(database, "DELETE FROM state_versions WHERE id = ?", id);
	return success && rows_changed == 1;
}

free_state_version :: (state_version: *State_Version) {
	free(state_version.data);
	free(state_version.created_at);
	state_version.* = .{};
}

sessions_find :: (database: *sqlite3, token: string) -> Session, bool {
	if token.count == 0 return .{}, false;
	session, found := sessions_find_query(database, "SELECT id, user_id, token, created_at FROM sessions WHERE token = ? LIMIT 1", token);
	return session, found;
}

sessions_create :: (database: *sqlite3, user_id: s64, token: string) -> Session {
	if user_id <= 0 || token.count == 0 return .{};
	session, _ := sessions_find_query(
		database,
		"INSERT INTO sessions (user_id, token) VALUES (?, ?) RETURNING id, user_id, token, created_at",
		user_id,
		token,
	);
	return session;
}

sessions_delete :: (database: *sqlite3, token: string) -> bool {
	if token.count == 0 return false;
	success, rows_changed, _ := sqlite3_exec_query(database, "DELETE FROM sessions WHERE token = ?", token);
	return success && rows_changed == 1;
}

free_session :: (session: *Session) {
	free(session.token);
	free(session.created_at);
	session.* = .{};
}

#scope_file

users_find_query :: (database: *sqlite3, sql: string, parameters: ..Any) -> User, bool {
	success, users, _ := sqlite3_exec_query(database, User, sql, ..parameters);
	if !success || users.count == 0 {
		array_free(users);
		return .{}, false;
	}

	user := users[0];
	array_free(users);
	return user, true;
}

state_versions_find_query :: (database: *sqlite3, sql: string, parameters: ..Any) -> State_Version, bool {
	success, state_versions, _ := sqlite3_exec_query(database, State_Version, sql, ..parameters);
	if !success || state_versions.count == 0 {
		array_free(state_versions);
		return .{}, false;
	}

	state_version := state_versions[0];
	array_free(state_versions);
	return state_version, true;
}

sessions_find_query :: (database: *sqlite3, sql: string, parameters: ..Any) -> Session, bool {
	success, sessions, _ := sqlite3_exec_query(database, Session, sql, ..parameters);
	if !success || sessions.count == 0 {
		array_free(sessions);
		return .{}, false;
	}

	session := sessions[0];
	array_free(sessions);
	return session, true;
}
