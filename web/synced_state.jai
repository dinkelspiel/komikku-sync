// SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
// SPDX-License-Identifier: GPL-3.0-or-later

#import "Basic";
#import "String";

SYNCED_STATE_MAGIC :: "KSYN\x02";
SYNCED_STATE_LEGACY_MAGIC :: "KSYN\x01";
MAX_SYNCED_STATE_ITEMS :: 10_000_000;
MAX_SYNCED_STATE_STRING_SIZE :: 16 * 1024 * 1024;
MAX_SYNCED_STATE_SIZE :: 128 * 1024 * 1024;

libz :: #library,system "libz";
zlib_compress_bound :: (source_length: u64) -> u64 #foreign libz "compressBound";
zlib_compress :: (destination: *u8, destination_length: *u64, source: *u8, source_length: u64, level: s32) -> s32 #foreign libz "compress2";
zlib_uncompress :: (destination: *u8, destination_length: *u64, source: *u8, source_length: u64) -> s32 #foreign libz "uncompress";
ZLIB_OK :: 0;
ZLIB_BUFFER_ERROR :: -5;

Synced_Chapter :: struct {
    slug: string;
    has_slug: bool;
    num: string;
    has_num: bool;
    read: bool;
    last_read: s64;
    has_last_read: bool;
    last_page_read_index: s64;
    has_last_page_read_index: bool;
}

Synced_Manga :: struct {
    slug: string;
    server_id: string;
    name: string;
    has_name: bool;
    url: string;
    has_url: bool;
    chapters: [..]Synced_Chapter;
}

Synced_State :: struct {
    mangas: [..]Synced_Manga;
}

Sync_Writer :: struct {
    data: [..]u8;
}

Sync_Reader :: struct {
    data: string;
    offset: s64;
}

synced_state_decode :: (data: string) -> Synced_State, bool {
    state: Synced_State;
    if data.count < SYNCED_STATE_MAGIC.count {
        log("[Cloud Sync] Invalid state header (% bytes)", data.count, flags=.ERROR);
        return state, false;
    }
    magic := sync_substring(data, 0, SYNCED_STATE_MAGIC.count);
    version: s64;
    if magic == SYNCED_STATE_MAGIC version = 2;
    else if magic == SYNCED_STATE_LEGACY_MAGIC version = 1;
    else {
        log("[Cloud Sync] Invalid state header (% bytes)", data.count, flags=.ERROR);
        return state, false;
    }

    compressed := sync_substring(data, SYNCED_STATE_MAGIC.count, data.count);
    payload, decompressed := sync_decompress(compressed);
    if !decompressed {
        log("[Cloud Sync] Failed to decompress state (% compressed bytes)", compressed.count, flags=.ERROR);
        return state, false;
    }
    defer free(payload);
    reader := Sync_Reader.{data = payload};
    manga_count, ok := sync_read_count(*reader);
    if !ok {
        log("[Cloud Sync] Invalid manga count at offset %/%", reader.offset, reader.data.count, flags=.ERROR);
        return state, false;
    }
    log("[Cloud Sync] Decoding % manga from % bytes", manga_count, reader.data.count);

    for manga_index: 0..manga_count-1 {
        manga: Synced_Manga;
        manga.slug, ok = sync_read_string(*reader);
        if !ok {
            log("[Cloud Sync] Invalid manga % slug at offset %/%", manga_index, reader.offset, reader.data.count, flags=.ERROR);
            free_synced_state(*state);
            return .{}, false;
        }
        manga.server_id, ok = sync_read_string(*reader);
        if !ok {
            log("[Cloud Sync] Invalid manga % server at offset %/%", manga_index, reader.offset, reader.data.count, flags=.ERROR);
            free(manga.slug);
            free_synced_state(*state);
            return .{}, false;
        }
        manga.name, manga.has_name, ok = sync_read_optional_string(*reader);
        if !ok {
            log("[Cloud Sync] Invalid manga % name at offset %/%", manga_index, reader.offset, reader.data.count, flags=.ERROR);
            free_synced_manga(*manga);
            free_synced_state(*state);
            return .{}, false;
        }
        manga.url, manga.has_url, ok = sync_read_optional_string(*reader);
        if !ok {
            log("[Cloud Sync] Invalid manga % URL at offset %/%", manga_index, reader.offset, reader.data.count, flags=.ERROR);
            free_synced_manga(*manga);
            free_synced_state(*state);
            return .{}, false;
        }

        chapter_count: s64;
        chapter_count, ok = sync_read_count(*reader);
        if !ok {
            log("[Cloud Sync] Invalid manga % chapter count at offset %/%", manga_index, reader.offset, reader.data.count, flags=.ERROR);
            free_synced_manga(*manga);
            free_synced_state(*state);
            return .{}, false;
        }
        log("[Cloud Sync] Manga % has % chapters at offset %", manga_index, chapter_count, reader.offset);
        for chapter_index: 0..chapter_count-1 {
            flags: u8;
            flags, ok = sync_read_byte(*reader);
            valid_flags := ifx version == 2 cast(u8) 31 else cast(u8) 7;
            if !ok || flags & ~valid_flags != 0 {
                log("[Cloud Sync] Invalid manga % chapter % flags value % at offset %/%", manga_index, chapter_index, flags, reader.offset, reader.data.count, flags=.ERROR);
                free_synced_manga(*manga);
                free_synced_state(*state);
                return .{}, false;
            }

            chapter := Synced_Chapter.{read = flags & 1 != 0, has_slug = flags & 2 != 0, has_num = flags & 4 != 0};
            if chapter.has_slug {
                chapter.slug, ok = sync_read_string(*reader);
                if !ok {
                    log("[Cloud Sync] Invalid manga % chapter % slug at offset %/%", manga_index, chapter_index, reader.offset, reader.data.count, flags=.ERROR);
                    free_synced_chapter(*chapter);
                    free_synced_manga(*manga);
                    free_synced_state(*state);
                    return .{}, false;
                }
            }
            if chapter.has_num {
                chapter.num, ok = sync_read_string(*reader);
                if !ok {
                    log("[Cloud Sync] Invalid manga % chapter % number at offset %/%", manga_index, chapter_index, reader.offset, reader.data.count, flags=.ERROR);
                    free_synced_chapter(*chapter);
                    free_synced_manga(*manga);
                    free_synced_state(*state);
                    return .{}, false;
                }
            }
            chapter.has_last_read = flags & 8 != 0;
            if chapter.has_last_read {
                chapter.last_read, ok = sync_read_varint(*reader);
                if !ok {
                    log("[Cloud Sync] Invalid manga % chapter % last-read time at offset %/%", manga_index, chapter_index, reader.offset, reader.data.count, flags=.ERROR);
                    free_synced_chapter(*chapter);
                    free_synced_manga(*manga);
                    free_synced_state(*state);
                    return .{}, false;
                }
            }
            chapter.has_last_page_read_index = flags & 16 != 0;
            if chapter.has_last_page_read_index {
                chapter.last_page_read_index, ok = sync_read_varint(*reader);
                if !ok {
                    log("[Cloud Sync] Invalid manga % chapter % resume page at offset %/%", manga_index, chapter_index, reader.offset, reader.data.count, flags=.ERROR);
                    free_synced_chapter(*chapter);
                    free_synced_manga(*manga);
                    free_synced_state(*state);
                    return .{}, false;
                }
            }
            array_add(*manga.chapters, chapter);
        }
        array_add(*state.mangas, manga);
    }

    if reader.offset != reader.data.count {
        log("[Cloud Sync] Unexpected trailing state data at offset %/%", reader.offset, reader.data.count, flags=.ERROR);
        free_synced_state(*state);
        return .{}, false;
    }
    return state, true;
}

synced_state_encode :: (state: Synced_State) -> string {
    writer: Sync_Writer;
    defer array_free(writer.data);

    sync_write_varint(*writer, state.mangas.count);
    for manga: state.mangas {
        sync_write_string(*writer, manga.slug);
        sync_write_string(*writer, manga.server_id);
        sync_write_optional_string(*writer, manga.name, manga.has_name);
        sync_write_optional_string(*writer, manga.url, manga.has_url);
        sync_write_varint(*writer, manga.chapters.count);
        for chapter: manga.chapters {
            flags: u8 = ifx chapter.read cast(u8) 1 else cast(u8) 0;
            if chapter.has_slug flags |= 2;
            if chapter.has_num flags |= 4;
            if chapter.has_last_read flags |= 8;
            if chapter.has_last_page_read_index flags |= 16;
            array_add(*writer.data, flags);
            if chapter.has_slug sync_write_string(*writer, chapter.slug);
            if chapter.has_num sync_write_string(*writer, chapter.num);
            if chapter.has_last_read sync_write_varint(*writer, chapter.last_read);
            if chapter.has_last_page_read_index sync_write_varint(*writer, chapter.last_page_read_index);
        }
    }

    compressed_capacity := zlib_compress_bound(writer.data.count.(u64));
    result := alloc_string(SYNCED_STATE_MAGIC.count + compressed_capacity.(s64));
    for byte: SYNCED_STATE_MAGIC result[it_index] = byte;
    compressed_size := compressed_capacity;
    status := zlib_compress(
        result.data + SYNCED_STATE_MAGIC.count,
        *compressed_size,
        writer.data.data,
        writer.data.count.(u64),
        9,
    );
    if status != ZLIB_OK {
        free(result);
        return "";
    }
    result.count = SYNCED_STATE_MAGIC.count + compressed_size.(s64);
    return result;
}

synced_state_merge :: (server: *Synced_State, client: Synced_State) {
    for client_manga: client.mangas {
        server_manga: *Synced_Manga;
        for *server.mangas {
            if it.slug == client_manga.slug && it.server_id == client_manga.server_id {
                server_manga = it;
                break;
            }
        }
        if !server_manga {
            array_add(*server.mangas, copy_synced_manga(client_manga));
            continue;
        }

        if client_manga.has_name {
            if server_manga.has_name free(server_manga.name);
            server_manga.name = copy_string(client_manga.name);
            server_manga.has_name = true;
        }
        if client_manga.has_url {
            if server_manga.has_url free(server_manga.url);
            server_manga.url = copy_string(client_manga.url);
            server_manga.has_url = true;
        }

        for client_chapter: client_manga.chapters {
            server_chapter: *Synced_Chapter;
            for *server_manga.chapters {
                slug_matches := client_chapter.has_slug && it.has_slug && client_chapter.slug == it.slug;
                num_matches := client_chapter.has_num && it.has_num && client_chapter.num == it.num;
                if slug_matches || num_matches {
                    server_chapter = it;
                    break;
                }
            }
            if server_chapter {
                server_chapter.read = server_chapter.read || client_chapter.read;
                if client_chapter.has_last_read && (!server_chapter.has_last_read || client_chapter.last_read > server_chapter.last_read) {
                    server_chapter.last_read = client_chapter.last_read;
                    server_chapter.has_last_read = true;
                    server_chapter.last_page_read_index = client_chapter.last_page_read_index;
                    server_chapter.has_last_page_read_index = client_chapter.has_last_page_read_index;
                }
            } else {
                array_add(*server_manga.chapters, copy_synced_chapter(client_chapter));
            }
        }
    }
}

free_synced_state :: (state: *Synced_State) {
    for *state.mangas free_synced_manga(it);
    array_free(state.mangas);
    state.* = .{};
}

free_synced_manga :: (manga: *Synced_Manga) {
    free(manga.slug);
    free(manga.server_id);
    if manga.has_name free(manga.name);
    if manga.has_url free(manga.url);
    for *manga.chapters free_synced_chapter(it);
    array_free(manga.chapters);
    manga.* = .{};
}

free_synced_chapter :: (chapter: *Synced_Chapter) {
    if chapter.has_slug free(chapter.slug);
    if chapter.has_num free(chapter.num);
    chapter.* = .{};
}

#scope_file

copy_synced_manga :: (source: Synced_Manga) -> Synced_Manga {
    result := Synced_Manga.{
        slug = copy_string(source.slug),
        server_id = copy_string(source.server_id),
        has_name = source.has_name,
        has_url = source.has_url,
    };
    if source.has_name result.name = copy_string(source.name);
    if source.has_url result.url = copy_string(source.url);
    for chapter: source.chapters array_add(*result.chapters, copy_synced_chapter(chapter));
    return result;
}

copy_synced_chapter :: (source: Synced_Chapter) -> Synced_Chapter {
    result := Synced_Chapter.{
        has_slug = source.has_slug,
        has_num = source.has_num,
        read = source.read,
        last_read = source.last_read,
        has_last_read = source.has_last_read,
        last_page_read_index = source.last_page_read_index,
        has_last_page_read_index = source.has_last_page_read_index,
    };
    if source.has_slug result.slug = copy_string(source.slug);
    if source.has_num result.num = copy_string(source.num);
    return result;
}

sync_write_varint :: (writer: *Sync_Writer, initial_value: s64) {
    value := initial_value;
    while value >= 128 {
        array_add(*writer.data, cast(u8) ((value & 127) | 128));
        value >>= 7;
    }
    array_add(*writer.data, cast(u8) value);
}

sync_write_string :: (writer: *Sync_Writer, value: string) {
    sync_write_varint(writer, value.count);
    for byte: value array_add(*writer.data, byte);
}

sync_write_optional_string :: (writer: *Sync_Writer, value: string, present: bool) {
    if !present {
        sync_write_varint(writer, 0);
        return;
    }
    sync_write_varint(writer, value.count + 1);
    for byte: value array_add(*writer.data, byte);
}

sync_read_byte :: (reader: *Sync_Reader) -> u8, bool {
    if reader.offset >= reader.data.count return 0, false;
    value := reader.data[reader.offset];
    reader.offset += 1;
    return value, true;
}

sync_read_varint :: (reader: *Sync_Reader) -> s64, bool {
    value: s64;
    shift: s64;
    while shift < 64 {
        byte, ok := sync_read_byte(reader);
        if !ok return 0, false;
        component := cast(s64) (byte & 127);
        value |= component << shift;
        if byte < 128 return value, true;
        shift += 7;
    }
    return 0, false;
}

sync_read_count :: (reader: *Sync_Reader) -> s64, bool {
    value, ok := sync_read_varint(reader);
    return value, ok && value <= MAX_SYNCED_STATE_ITEMS;
}

sync_read_string :: (reader: *Sync_Reader) -> string, bool {
    size, ok := sync_read_varint(reader);
    if !ok || size > MAX_SYNCED_STATE_STRING_SIZE || reader.offset + size > reader.data.count return "", false;
    value := copy_string(sync_substring(reader.data, reader.offset, reader.offset + size));
    reader.offset += size;
    return value, true;
}

sync_read_optional_string :: (reader: *Sync_Reader) -> string, bool, bool {
    size, ok := sync_read_varint(reader);
    if !ok return "", false, false;
    if size == 0 return "", false, true;
    if size - 1 > MAX_SYNCED_STATE_STRING_SIZE || reader.offset + size - 1 > reader.data.count return "", false, false;
    value := copy_string(sync_substring(reader.data, reader.offset, reader.offset + size - 1));
    reader.offset += size - 1;
    return value, true, true;
}

sync_substring :: (value: string, start: s64, end: s64) -> string {
    result: string;
    result.data = value.data + start;
    result.count = end - start;
    return result;
}

sync_decompress :: (compressed: string) -> string, bool {
    if compressed.count == 0 return "", false;
    capacity := max(compressed.count * 4, 1024);
    while capacity <= MAX_SYNCED_STATE_SIZE {
        result := alloc_string(capacity);
        result_size := capacity.(u64);
        status := zlib_uncompress(result.data, *result_size, compressed.data, compressed.count.(u64));
        if status == ZLIB_OK {
            result.count = result_size.(s64);
            return result, true;
        }
        free(result);
        if status != ZLIB_BUFFER_ERROR return "", false;
        if capacity > MAX_SYNCED_STATE_SIZE / 2 break;
        capacity *= 2;
    }
    return "", false;
}
