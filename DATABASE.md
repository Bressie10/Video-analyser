# PostgreSQL database

Migration `005_meta_library.sql` adds the automatic Meta library described in
[backend/META_LIBRARY.md](backend/META_LIBRARY.md). Apply it after migrations
001–004. It preserves existing video/metric rows and backfills analysis version 1.

| Added table | Purpose |
| --- | --- |
| `meta_connections` | Private stable identity, encrypted authorization, expiry, daily schedule |
| `meta_sessions` | Hashed browser session tokens and connection ownership |
| `meta_accounts` | Private Page/Instagram/ad-account identities and initial-sync boundary |
| `meta_library_items` | Internal UUID, private source identity, publication date, readiness and cached analysis link |
| `meta_ad_assets` | Many-to-many links from ads to canonical video assets |
| `meta_library_performance` | Independent latest snapshot and retrieval time per organic item/ad |
| `meta_sync_runs` | Durable sync or explicit batch and completion state |
| `meta_jobs` | Resumable discovery, independent analysis/metrics work, leases, claims and safe outcomes |

`videos.analysis_version` identifies the processing pipeline version.
`videos.meta_connection_id` scopes imported analyses to their owning connection;
legacy public upload routes cannot retrieve them. Canonical source uniqueness is
`(connection_id, platform, external_id)`: Facebook videos and Reels with the same
provider identity share one item, including when discovered through an ad. Account
context and ad identity are retained privately. New library metric snapshots can
coexist across organic items and multiple ads without replacing legacy snapshots.

The source of truth for the schema is
[`backend/migrations/001_create_video_analysis.sql`](backend/migrations/001_create_video_analysis.sql).
It creates five tables. Each processed video has one UUID in `videos.id`; all
analysis rows refer to it through `video_id`. Deleting a video cascades to its
analysis rows.

[`backend/migrations/002_create_tiktok_video_performance.sql`](backend/migrations/002_create_tiktok_video_performance.sql)
adds a sixth table for optional TikTok performance counts linked to the same
internal video UUID. Migration
[`003_platform_agnostic_performance.sql`](backend/migrations/003_platform_agnostic_performance.sql)
renames it to `video_performance` and backfills existing rows with source `tiktok`,
preserving counts and timestamps. Migration
[`004_meta_ads_metrics.sql`](backend/migrations/004_meta_ads_metrics.sql) adds a
nullable `meta_ads JSONB` column for currency, reporting context, decimal values,
and action arrays that the four BIGINT columns cannot represent. Existing rows
keep their counts and timestamps. Apply migrations in numerical order.

When `DATABASE_URL` is configured, `POST /api/videos` stores its result in these
tables and returns `video_id`. The examples below describe possible rows; they
are not seed data and are not present in the database by default.

## Local setup

From the project root:

```sh
cp .env.example .env
docker compose up -d postgres
set -a
source .env
set +a
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/001_create_video_analysis.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/002_create_tiktok_video_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/003_platform_agnostic_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/004_meta_ads_metrics.sql
```

The migration is applied once to a new database. Change the credentials and
port in `.env` for your local setup, and keep `DATABASE_URL` in sync. To inspect
the resulting tables, run `psql "$DATABASE_URL" -c '\dt'`. To test a sample
round trip without retaining rows, run:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/tests/schema_roundtrip.sql
```

## Tables and relationships

| Table | One row represents | Primary key | Link to video |
| --- | --- | --- | --- |
| `videos` | One video's metadata and complete transcript | `id` (UUID) | The parent row |
| `transcript_segments` | One timestamped speech segment | `(video_id, segment_index)` | `video_id` → `videos.id` |
| `scenes` | One detected scene and its cut boundary | `(video_id, scene_number)` | `video_id` → `videos.id` |
| `on_screen_text` | One interval when detected text is visible | `(video_id, detection_index)` | `video_id` → `videos.id` |
| `motion_events` | One classified motion interval | `(video_id, event_index)` | `video_id` → `videos.id` |
| `video_performance` | Available video engagement counts | `video_id` | `video_id` → `videos.id` |

The performance table stores a count snapshot, a required `source`, and `fetched_at`. It stores
neither the TikTok URL nor TikTok's video ID; the internal UUID is the only
database link in this legacy table. The new Meta library stores stable ad, video,
and account identities privately for synchronization and deduplication; it never
exposes them in the new customer-facing API.

`meta_ads` is only allowed for source `meta_ads`. The common API embeds its
allowlisted contents at `performance_metrics.meta_ads`; other sources omit this
key. Ad-only snapshots can have all four common counts null, provided at least
one ad metric is available. The existing row lock, source-conflict check,
refresh timestamp, and cascade deletion still apply. Decimal values are stored
as strings to avoid binary floating-point rounding. See the Meta Ads section
in README.md for fields and reporting semantics.

The numbered child keys preserve the order of arrays in the processing
response. `segment_index`, `detection_index`, and `event_index` start at 0;
`scene_number` starts at 1, as in the current scene output. A video can have
zero or many rows in any child table.

### `videos`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Unique video ID; defaults to `gen_random_uuid()` |
| `duration_seconds` | `NUMERIC(12,3)` | Source video duration |
| `container` | `TEXT` | Source container name from ffprobe |
| `file_size_bytes` | `BIGINT` | Source file size |
| `overall_bit_rate` | `BIGINT`, nullable | Overall source bitrate |
| `video_codec` | `TEXT`, nullable | Video codec name |
| `video_codec_long_name` | `TEXT`, nullable | Full video codec name |
| `width`, `height` | `INTEGER`, nullable | Source video resolution in pixels |
| `aspect_ratio` | generated `NUMERIC`, nullable | `width / height`; never supplied on insert |
| `fps` | `NUMERIC(12,3)`, nullable | Average video frames per second |
| `source_fps` | `NUMERIC(12,3)`, nullable | Source stream frame rate |
| `pixel_format` | `TEXT`, nullable | Video pixel format |
| `video_bit_rate` | `BIGINT`, nullable | Video stream bitrate |
| `frame_count` | `BIGINT`, nullable | Number of source video frames |
| `audio_codec` | `TEXT`, nullable | Audio codec name |
| `audio_codec_long_name` | `TEXT`, nullable | Full audio codec name |
| `audio_sample_rate` | `INTEGER`, nullable | Audio samples per second |
| `audio_channels` | `INTEGER`, nullable | Number of audio channels |
| `audio_channel_layout` | `TEXT`, nullable | Audio channel layout |
| `audio_bit_rate` | `BIGINT`, nullable | Audio stream bitrate |
| `transcript_text` | `TEXT` | Complete joined transcript; defaults to empty text |

The metadata columns correspond to `metadata.duration_seconds`,
`metadata.container`, `metadata.file_size_bytes`, `metadata.overall_bit_rate`,
the nested `metadata.video` and `metadata.audio` fields, and `audio.text` in
the current API response. `aspect_ratio` is derived from the source width and
height; it is `NULL` when either is unavailable.

### `transcript_segments`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `video_id` | `UUID` | Parent video |
| `segment_index` | `INTEGER` | Position in `audio.segments` |
| `start_seconds` | `NUMERIC(12,3)` | Segment start timestamp |
| `end_seconds` | `NUMERIC(12,3)` | Segment end timestamp |
| `text` | `TEXT` | Spoken text in this segment |

### `scenes`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `video_id` | `UUID` | Parent video |
| `scene_number` | `INTEGER` | Scene number from `scenes[]` |
| `start_seconds` | `NUMERIC(12,3)` | Scene start timestamp |
| `end_seconds` | `NUMERIC(12,3)` | Scene end timestamp |
| `duration_seconds` | `NUMERIC(12,3)` | Reported scene duration |
| `cut_timestamp_seconds` | `NUMERIC(12,3)`, nullable | Cut before this scene; `NULL` for the first scene |

### `on_screen_text`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `video_id` | `UUID` | Parent video |
| `detection_index` | `INTEGER` | Position in `on_screen_text[]` |
| `text` | `TEXT` | Detected text or popup content |
| `bounding_box` | `JSONB` | Quadrilateral as `[[x,y],[x,y],[x,y],[x,y]]` |
| `confidence` | `NUMERIC(4,3)` | OCR confidence from 0 to 1 |
| `appearance_timestamp_seconds` | `NUMERIC(12,3)` | First visible timestamp |
| `disappearance_timestamp_seconds` | `NUMERIC(12,3)` | Timestamp at which it stopped appearing |

The quadrilateral stays in `JSONB` so all four points and their order can be
reconstructed. There is no separate popup classifier in the current processing
output; text and popups share this table.

### `motion_events`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `video_id` | `UUID` | Parent video |
| `event_index` | `INTEGER` | Position in `motion_events[]` |
| `start_seconds` | `NUMERIC(12,3)` | Motion interval start |
| `end_seconds` | `NUMERIC(12,3)` | Motion interval end |
| `type` | `TEXT` | Classification such as `camera_pan`, `camera_zoom`, `camera_shake`, `local_motion`, `general_motion`, or `unknown` |
| `confidence` | `NUMERIC(4,3)` | Motion confidence from 0 to 1 |

## Example rows

These rows show how one video's data would be linked. The UUID is illustrative.
Only selected metadata columns are shown here; the complete column list is
above.

`videos`:

| id | duration_seconds | width | height | aspect_ratio | fps | video_codec | audio_codec | file_size_bytes | transcript_text |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 12.345 | 1920 | 1080 | 1.777778… | 29.970 | h264 | aac | 1234567 | Hello world |

`transcript_segments`:

| video_id | segment_index | start_seconds | end_seconds | text |
| --- | ---: | ---: | ---: | --- |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 0 | 0.100 | 1.250 | Hello world |

`scenes`:

| video_id | scene_number | start_seconds | end_seconds | duration_seconds | cut_timestamp_seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 1 | 0.000 | 5.000 | 5.000 | NULL |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 2 | 5.000 | 12.345 | 7.345 | 5.000 |

`on_screen_text`:

| video_id | detection_index | text | bounding_box | confidence | appearance_timestamp_seconds | disappearance_timestamp_seconds |
| --- | ---: | --- | --- | ---: | ---: | ---: |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 0 | Watch this | `[[10,20],[110,20],[110,50],[10,50]]` | 0.987 | 1.500 | 3.000 |

`motion_events`:

| video_id | event_index | start_seconds | end_seconds | type | confidence |
| --- | ---: | ---: | ---: | --- | ---: |
| `8db7e284-353b-4f3e-9bf0-44d78d888720` | 0 | 2.000 | 4.250 | camera_pan | 0.875 |

To retrieve all results for a video, query each child table with the same
`video_id` and order by its numbered key. For example:

```sql
SELECT * FROM videos WHERE id = '8db7e284-353b-4f3e-9bf0-44d78d888720';
SELECT * FROM transcript_segments WHERE video_id = '8db7e284-353b-4f3e-9bf0-44d78d888720' ORDER BY segment_index;
SELECT * FROM scenes WHERE video_id = '8db7e284-353b-4f3e-9bf0-44d78d888720' ORDER BY scene_number;
SELECT * FROM on_screen_text WHERE video_id = '8db7e284-353b-4f3e-9bf0-44d78d888720' ORDER BY detection_index;
SELECT * FROM motion_events WHERE video_id = '8db7e284-353b-4f3e-9bf0-44d78d888720' ORDER BY event_index;
```

The numeric timestamp columns preserve the three decimal places emitted by
the processing code. The schema also checks nonnegative durations and ordered
intervals, and restricts confidence scores to the range 0–1.
