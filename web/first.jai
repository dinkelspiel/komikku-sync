// SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
// SPDX-License-Identifier: GPL-3.0-or-later

#import "prairie";
#import "argon2-jai";

#load "database.jai";
#load "synced_state.jai";

#import "Basic";
#import "Hash_Table";
#import "POSIX";

database: *sqlite3;

main :: () {
    app, ok := create("0.0.0.0", 8010);
    if !ok {
        print("Failed creating server\n");
        return;
    }

    router := create_router();
    defer destroy_router(*router);

    sqlite3_status := sqlite3_open_v2("database.db", *database, SQLITE_OPEN_CREATE|SQLITE_OPEN_READWRITE, null);
    if sqlite3_status != SQLITE_OK {
        log("failed to open/create sqlite db at 'database.db' with err = %", get_sqlite_error(database), flags=.ERROR);

        if database sqlite3_free(database);
        return;
    }
    foreign_keys_ok, _, _ := sqlite3_exec_query(database, "PRAGMA foreign_keys = ON");
    if !foreign_keys_ok {
        log("failed to enable sqlite foreign keys", flags=.ERROR);
        sqlite3_free(database);
        return;
    }

    get(*router, "/", (request: Http_Request) -> Http_Response {
        return .{
            status_code = 200,
            body = #string HTML
                <html>
                <head>
                    <style type="text/css">body{margin:40px
                    auto;max-width:650px;line-height:1.6;font-size:18px;color:#444;padding:0
                    10px}h1,h2,h3{line-height:1.2}</style>
                </head>
                <body>
                    <h2>Login</h2>
                    <form action="/login" method="POST">
                        <label>Username</label>
                        <input name="username">
                        <label>Password</label>
                        <input type="password" name="password">
                        <button type="submit">Login</button>
                    </form>
                    <h2>Sign Up</h2>
                    <form action="/signup" method="POST">
                        <label>Username</label>
                        <input name="username">
                        <label>Password</label>
                        <input type="password" name="password">
                        <label>Confirm Password</label>
                        <input type="password" name="confirm_password">
                        <button type="submit">Sign Up</button>
                    </form>
                </body></html>
            HTML,
            content_type = .TEXT_HTML
        };
    });

    post(*router, "/login", (request: Http_Request) -> Http_Response {
        username, has_username := table_find(*request.form_fields, "username");
        password, has_password := table_find(*request.form_fields, "password");

        if !has_username || !has_password {
            return .{
                status_code = 400,
                body = "Username and password are required",
                content_type = .TEXT_HTML
            };
        }

        decoded_username, username_is_encoded_correctly := decode_form_value(username);
        decoded_password, password_is_encoded_correctly := decode_form_value(password);
        if !username_is_encoded_correctly || !password_is_encoded_correctly {
            free(decoded_username);
            free(decoded_password);
            return .{status_code = 400, body = "Invalid form encoding", content_type = .TEXT_HTML};
        }
        defer free(decoded_username);
        defer free(decoded_password);
        username = decoded_username;
        password = decoded_password;

        user, user_exists := users_find(database, username = username);
        if !user_exists {
            return .{status_code = 401, body = "Invalid username or password", content_type = .TEXT_HTML};
        }
        defer free_user(*user);

        argon2_status := argon2id_verify(
            temp_c_string(user.password),
            password.data,
            password.count.(u64),
        );
        if argon2_status == xx Argon2_ErrorCodes.VERIFY_MISMATCH {
            return .{status_code = 401, body = "Invalid username or password", content_type = .TEXT_HTML};
        }
        if argon2_status != 0 {
            log("Failed to verify password: %", to_string(argon2_error_message(argon2_status)), flags=.ERROR);
            return .{status_code = 500, body = "Failed to verify password", content_type = .TEXT_HTML};
        }

        return .{
            status_code = 200,
            body = "Logged in",
            content_type = .TEXT_HTML
        };
    });

    post(*router, "/api/login", (request: Http_Request) -> Http_Response {
        user, authenticated_ok := authenticate_password(request);
        if !authenticated_ok return .{status_code = 400, body = "Invalid username or password", content_type = .TEXT_HTML};
        defer free_user(*user);

        token, token_ok := generate_session_token();
        if !token_ok return .{status_code = 400, body = "Failed to create session", content_type = .TEXT_HTML};

        session := sessions_create(database, user.id, token);
        if session.id <= 0 {
            free(token);
            return .{status_code = 400, body = "Failed to create session", content_type = .TEXT_HTML};
        }
        defer free_session(*session);

        return .{status_code = 200, body = token, content_type = .TEXT_HTML, owned_body = true};
    });

    get(*router, "/api/auth/validate", (request: Http_Request) -> Http_Response {
        user, authenticated_ok := authenticate_token(request);
        if !authenticated_ok return .{status_code = 400, body = "Invalid session", content_type = .TEXT_HTML};
        free_user(*user);
        return .{status_code = 200, body = "", content_type = .TEXT_HTML};
    });

    get(*router, "/api/state", (request: Http_Request) -> Http_Response {
        user, authenticated_ok := authenticate_token(request);
        if !authenticated_ok return .{status_code = 400, body = "Invalid session", content_type = .TEXT_HTML};
        defer free_user(*user);

        state_version, found := state_versions_find(database, user_id = user.id);
        if !found {
            empty_state: Synced_State;
            encoded := synced_state_encode(empty_state);
            return .{status_code = 200, body = encoded, content_type = .APPLICATION_OCTET_STREAM, owned_body = true};
        }
        defer free_state_version(*state_version);

        decoded_state, valid := synced_state_decode(state_version.data);
        if !valid return .{status_code = 500, body = "Invalid stored sync state", content_type = .TEXT_HTML};
        free_synced_state(*decoded_state);
        return .{status_code = 200, body = copy_string(state_version.data), content_type = .APPLICATION_OCTET_STREAM, owned_body = true};
    });

    post(*router, "/api/state", (request: Http_Request) -> Http_Response {
        user, authenticated_ok := authenticate_token(request);
        if !authenticated_ok return .{status_code = 400, body = "Invalid session", content_type = .TEXT_HTML};
        defer free_user(*user);
        if !request_has_content_type(request, "application/vnd.komikku.sync-state") && !request_has_content_type(request, "application/octet-stream") {
            return .{status_code = 400, body = "Invalid content type", content_type = .TEXT_HTML};
        }

        client_state, client_ok := synced_state_decode(request.body);
        if !client_ok return .{status_code = 400, body = "Invalid sync state", content_type = .TEXT_HTML};
        defer free_synced_state(*client_state);

        merged_state := client_state;
        client_state = .{};
        defer free_synced_state(*merged_state);

        latest, found := state_versions_find(database, user_id = user.id);
        if found {
            defer free_state_version(*latest);
            server_state, server_ok := synced_state_decode(latest.data);
            if !server_ok return .{status_code = 500, body = "Invalid stored sync state", content_type = .TEXT_HTML};
            synced_state_merge(*server_state, merged_state);
            free_synced_state(*merged_state);
            merged_state = server_state;
        }

        encoded := synced_state_encode(merged_state);
        saved := state_versions_create(database, user.id, encoded);
        if saved.id <= 0 {
            free(encoded);
            return .{status_code = 500, body = "Failed to save sync state", content_type = .TEXT_HTML};
        }
        free_state_version(*saved);
        return .{status_code = 200, body = encoded, content_type = .APPLICATION_OCTET_STREAM, owned_body = true};
    });

    post(*router, "/signup", (request: Http_Request) -> Http_Response {
        username, has_username := table_find(*request.form_fields, "username");
        password, has_password := table_find(*request.form_fields, "password");
        confirm_password, has_confirm_password := table_find(*request.form_fields, "confirm_password");

        if !has_username || !has_password || !has_confirm_password {
            return .{
                status_code = 400,
                body = "Username, password, and confirm_password are required",
                content_type = .TEXT_HTML
            };
        }

        decoded_username, username_is_encoded_correctly := decode_form_value(username);
        decoded_password, password_is_encoded_correctly := decode_form_value(password);
        decoded_confirmation, confirmation_is_encoded_correctly := decode_form_value(confirm_password);
        if !username_is_encoded_correctly || !password_is_encoded_correctly || !confirmation_is_encoded_correctly {
            free(decoded_username);
            free(decoded_password);
            free(decoded_confirmation);
            return .{status_code = 400, body = "Invalid form encoding", content_type = .TEXT_HTML};
        }
        defer free(decoded_username);
        defer free(decoded_password);
        defer free(decoded_confirmation);
        username = decoded_username;
        password = decoded_password;
        confirm_password = decoded_confirmation;

        if !valid_signup_username(username) {
            return .{
                status_code = 400,
                body = "Username must be 1-32 characters and contain only lowercase letters, numbers, and underscores",
                content_type = .TEXT_HTML
            };
        }

        if !valid_signup_password(password) {
            return .{
                status_code = 400,
                body = "Password must be 8-255 characters and include an uppercase letter, lowercase letter, number, and symbol",
                content_type = .TEXT_HTML
            };
        }

        if password != confirm_password {
            return .{
                status_code = 400,
                body = "Password isn't equal to confirm_password",
                content_type = .TEXT_HTML
            };
        }

        existing_user, user_exists := users_find(database, username = username);
        if user_exists free_user(*existing_user);

        if user_exists {
            return .{
                status_code = 400,
                body = "User with this username already exists",
                content_type = .TEXT_HTML
            };
        }

        salt: [16]u8;
        if getentropy(salt.data, salt.count.(u64)) != 0 {
            return .{
                status_code = 500,
                body = "Failed to generate password salt",
                content_type = .TEXT_HTML
            };
        }

        encoded_hash: [128]u8;
        argon2_status := argon2id_hash_encoded(
            3,
            64 * 1024,
            1,
            password.data,
            password.count.(u64),
            salt.data,
            salt.count.(u64),
            32,
            encoded_hash.data,
            encoded_hash.count.(u64),
        );
        if argon2_status != 0 {
            log("Failed to hash password: %", to_string(argon2_error_message(argon2_status)), flags=.ERROR);
            return .{
                status_code = 500,
                body = "Failed to hash password",
                content_type = .TEXT_HTML
            };
        }

        user := users_create(database, username, to_string(encoded_hash.data));

        return .{
            status_code = 200,
            body = tprint("Created user %", user),
            content_type = .TEXT_HTML
        };
    });

    // middleware(*router, (router: *Router) {
    //     middleware(router, (nested_router: *Router) {
    //         get(nested_router, "/test", (request: Http_Request) -> Http_Response {
    //             return .{
    //                 status_code = 200,
    //                 body = "test",
    //                 content_type = .TEXT_HTML
    //             };
    //         });
    //     }, test);

    //     get(router, "/api", (request: Http_Request) -> Http_Response {
    //         return .{
    //             status_code = 200,
    //             body = "{\"test\": \"test\"}",
    //             content_type = .APPLICATION_JSON
    //         };
    //     });
    // }, authenticated);

    run(app, handle_request(*router));
}

authenticated :: (request: Http_Request) -> Middleware_Response {
    if request.route == "/api" return respond(.{status_code = 400});
    return next();
}

test :: (request: Http_Request) -> Middleware_Response {
    if request.route == "/test" return respond(.{status_code = 500});
    return next();
}

valid_signup_username :: (username: string) -> bool {
    if username.count < 1 || username.count > 32 return false;

    for byte: username {
        if byte >= #char "a" && byte <= #char "z" continue;
        if byte >= #char "0" && byte <= #char "9" continue;
        if byte == #char "_" continue;
        return false;
    }

    return true;
}

valid_signup_password :: (password: string) -> bool {
    if password.count < 8 || password.count > 255 return false;

    has_lowercase := false;
    has_uppercase := false;
    has_number := false;
    has_symbol := false;

    for byte: password {
        if byte >= #char "a" && byte <= #char "z" {
            has_lowercase = true;
        } else if byte >= #char "A" && byte <= #char "Z" {
            has_uppercase = true;
        } else if byte >= #char "0" && byte <= #char "9" {
            has_number = true;
        } else {
            has_symbol = true;
        }
    }

    return has_lowercase && has_uppercase && has_number && has_symbol;
}

decode_form_value :: (encoded: string) -> string, bool {
    decoded := alloc_string(encoded.count);
    write_index: s64;
    read_index: s64;

    while read_index < encoded.count {
        byte := encoded[read_index];
        if byte == #char "+" {
            decoded[write_index] = #char " ";
            read_index += 1;
        } else if byte == #char "%" {
            if read_index + 2 >= encoded.count {
                free(decoded);
                return "", false;
            }

            high, high_ok := hexadecimal_value(encoded[read_index + 1]);
            low, low_ok := hexadecimal_value(encoded[read_index + 2]);
            if !high_ok || !low_ok {
                free(decoded);
                return "", false;
            }

            decoded[write_index] = high * 16 + low;
            read_index += 3;
        } else {
            decoded[write_index] = byte;
            read_index += 1;
        }
        write_index += 1;
    }

    decoded.count = write_index;
    return decoded, true;
}

authenticate_password :: (request: Http_Request) -> User, bool {
    username, has_username := table_find(*request.form_fields, "username");
    password, has_password := table_find(*request.form_fields, "password");
    if !has_username || !has_password return .{}, false;

    decoded_username, username_ok := decode_form_value(username);
    decoded_password, password_ok := decode_form_value(password);
    if !username_ok || !password_ok {
        free(decoded_username);
        free(decoded_password);
        return .{}, false;
    }
    defer free(decoded_username);
    defer free(decoded_password);

    user, found := users_find(database, username = decoded_username);
    if !found return .{}, false;
    verify_status := argon2id_verify(temp_c_string(user.password), decoded_password.data, decoded_password.count.(u64));
    if verify_status != 0 {
        free_user(*user);
        return .{}, false;
    }
    return user, true;
}

authenticate_token :: (request: Http_Request) -> User, bool {
    authorization := get_request_header(request, "Authorization");
    prefix := "Bearer ";
    if authorization.count <= prefix.count || substring(authorization, 0, prefix.count) != prefix return .{}, false;

    token := substring(authorization, prefix.count, authorization.count);
    session, found := sessions_find(database, token);
    if !found return .{}, false;
    defer free_session(*session);
    user, user_found := users_find(database, id = session.user_id);
    return user, user_found;
}

get_request_header :: (request: Http_Request, name: string) -> string {
    for index: 0..request.header_count-1 {
        if equal_ascii_case_insensitive(request.headers[index].key, name) return request.headers[index].value;
    }
    return "";
}

generate_session_token :: () -> string, bool {
    random_bytes: [32]u8;
    if getentropy(random_bytes.data, random_bytes.count.(u64)) != 0 return "", false;

    hexadecimal := "0123456789abcdef";
    token := alloc_string(random_bytes.count * 2);
    for random_bytes {
        token[it_index * 2] = hexadecimal[it >> 4];
        token[it_index * 2 + 1] = hexadecimal[it & 15];
    }
    return token, true;
}

hexadecimal_value :: (byte: u8) -> u8, bool {
    if byte >= #char "0" && byte <= #char "9" return byte - #char "0", true;
    if byte >= #char "a" && byte <= #char "f" return byte - #char "a" + 10, true;
    if byte >= #char "A" && byte <= #char "F" return byte - #char "A" + 10, true;
    return 0, false;
}
