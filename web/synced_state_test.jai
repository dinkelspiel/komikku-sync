// SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
// SPDX-License-Identifier: GPL-3.0-or-later

#load "synced_state.jai";

#import "Basic";

main :: () {
    server: Synced_State;
    server_manga := Synced_Manga.{slug = copy_string("manga"), server_id = copy_string("server")};
    array_add(*server_manga.chapters, .{slug = copy_string("chapter-1"), has_slug = true, num = copy_string("1"), has_num = true, read = false});
    array_add(*server.mangas, server_manga);
    defer free_synced_state(*server);

    encoded := synced_state_encode(server);
    defer free(encoded);
    assert(encoded == "KSYN\x02\x78\xda\x63\x64\xcd\x4d\xcc\x4b\x4f\x64\x2b\x4e\x2d\x2a\x4b\x2d\x62\x60\x60\x64\xe3\x4c\xce\x48\x2c\x28\x49\x2d\xd2\x35\x64\x34\x04\x00\x81\x92\x08\x2f");
    decoded, ok := synced_state_decode(encoded);
    assert(ok);
    defer free_synced_state(*decoded);
    assert(decoded.mangas.count == 1);
    assert(decoded.mangas[0].slug == "manga");
    assert(decoded.mangas[0].chapters.count == 1);
    assert(!decoded.mangas[0].chapters[0].read);

    legacy, legacy_ok := synced_state_decode("KSYN\x01\x78\xda\x63\x64\xcd\x4d\xcc\x4b\x4f\x64\x2b\x4e\x2d\x2a\x4b\x2d\x62\x60\x60\x64\xe3\x4c\xce\x48\x2c\x28\x49\x2d\xd2\x35\x64\x34\x04\x00\x81\x92\x08\x2f");
    assert(legacy_ok && legacy.mangas[0].chapters.count == 1);
    defer free_synced_state(*legacy);

    client: Synced_State;
    client_manga := Synced_Manga.{slug = copy_string("manga"), server_id = copy_string("server")};
    array_add(*client_manga.chapters, .{
        num = copy_string("1"),
        has_num = true,
        read = true,
        last_read = 100,
        has_last_read = true,
        last_page_read_index = 7,
        has_last_page_read_index = true,
    });
    array_add(*client_manga.chapters, .{slug = copy_string("chapter-2"), has_slug = true, read = false});
    array_add(*client.mangas, client_manga);
    defer free_synced_state(*client);

    synced_state_merge(*decoded, client);
    assert(decoded.mangas[0].chapters.count == 2);
    assert(decoded.mangas[0].chapters[0].read);
    assert(decoded.mangas[0].chapters[0].last_read == 100);
    assert(decoded.mangas[0].chapters[0].last_page_read_index == 7);
    assert(!decoded.mangas[0].chapters[1].read);

    stale: Synced_State;
    stale_manga := Synced_Manga.{slug = copy_string("manga"), server_id = copy_string("server")};
    array_add(*stale_manga.chapters, .{
        num = copy_string("1"),
        has_num = true,
        last_read = 50,
        has_last_read = true,
        last_page_read_index = 2,
        has_last_page_read_index = true,
    });
    array_add(*stale.mangas, stale_manga);
    defer free_synced_state(*stale);
    synced_state_merge(*decoded, stale);
    assert(decoded.mangas[0].chapters[0].last_read == 100);
    assert(decoded.mangas[0].chapters[0].last_page_read_index == 7);

    large_state: Synced_State;
    large_manga := Synced_Manga.{slug = copy_string("large"), server_id = copy_string("server")};
    for index: 0..129 {
        array_add(*large_manga.chapters, .{num = copy_string(tprint("%", index)), has_num = true});
    }
    array_add(*large_state.mangas, large_manga);
    defer free_synced_state(*large_state);

    large_encoded := synced_state_encode(large_state);
    defer free(large_encoded);
    large_decoded, large_ok := synced_state_decode(large_encoded);
    assert(large_ok && large_decoded.mangas[0].chapters.count == 130);
    defer free_synced_state(*large_decoded);
}
