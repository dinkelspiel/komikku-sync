// SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
// SPDX-License-Identifier: GPL-3.0-or-later

#load "database.jai";

#import "Basic";
#import "File";
#import "File_Utilities";
#import "Sort";
#import "String";

main :: () {
    database: *sqlite3;
    status := sqlite3_open(":memory:", *database);
    assert(status == SQLITE_OK);
    defer sqlite3_close(database);

    success, _, _ := sqlite3_exec_query(database, "PRAGMA foreign_keys = ON");
    assert(success);
    assert(run_up_migrations(database, "migrations"));

    user := users_create(database, "alice", "encoded-password-hash");
    assert(user.id > 0);
    defer free_user(*user);

    found_by_id, found_by_id_ok := users_find(database, user.id);
    assert(found_by_id_ok && found_by_id.id == user.id && found_by_id.username == "alice");
    defer free_user(*found_by_id);

    found_by_username, found_by_username_ok := users_find(database, username = "alice");
    assert(found_by_username_ok && found_by_username.id == user.id);
    defer free_user(*found_by_username);

    updated_user := users_update(database, user.id, "alice-updated", user.password);
    assert(updated_user.id == user.id && updated_user.username == "alice-updated");
    defer free_user(*updated_user);

    session := sessions_create(database, user.id, "session-token");
    assert(session.id > 0 && session.user_id == user.id && session.token == "session-token");
    defer free_session(*session);

    found_session, found_session_ok := sessions_find(database, session.token);
    assert(found_session_ok && found_session.id == session.id);
    defer free_session(*found_session);

    state := state_versions_create(database, user.id, "abc\0def");
    assert(state.id > 0 && state.data.count == 7);
    defer free_state_version(*state);

    found_state, found_state_ok := state_versions_find(database, user_id = user.id);
    assert(found_state_ok && found_state.id == state.id && found_state.data == state.data);
    defer free_state_version(*found_state);

    assert(state_versions_delete(database, state.id));
    _, deleted_state_found := state_versions_find(database, state.id);
    assert(!deleted_state_found);

    second_state := state_versions_create(database, user.id, "state");
    assert(second_state.id > 0);
    defer free_state_version(*second_state);

    assert(users_delete(database, user.id));
    _, deleted_user_found := users_find(database, user.id);
    assert(!deleted_user_found);
    _, cascaded_state_found := state_versions_find(database, second_state.id);
    assert(!cascaded_state_found);
    _, cascaded_session_found := sessions_find(database, session.token);
    assert(!cascaded_session_found);
}

#scope_file

run_up_migrations :: (database: *sqlite3, directory: string) -> bool {
    files := file_list(directory);
    defer {
        for files free(it);
        array_free(files);
    }

    up_migrations: [..]string;
    defer array_free(up_migrations);
    for files {
        if ends_with(it, ".up.sql") array_add(*up_migrations, it);
    }
    quick_sort(up_migrations, (a, b) => compare_strings(a, b));

    for up_migrations {
        sql, read_ok := read_entire_file(it, zero_terminated = true);
        if !read_ok return false;
        defer free(sql);

        error_message: *u8;
        status := sqlite3_exec(database, sql.data, null, null, *error_message);
        if status != SQLITE_OK {
            if error_message {
                log("Migration % failed: %", it, to_string(error_message), flags = .ERROR);
                sqlite3_free(error_message);
            }
            return false;
        }
    }

    return true;
}
