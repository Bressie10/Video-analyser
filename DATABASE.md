# PostgreSQL database

The source of truth is the ordered SQL in [backend/migrations](backend/migrations).
V2 stores reusable content analysis separately from refreshable performance and
private provider identities. See [the backend guide](backend/META_LIBRARY.md) for
scheduling and API behavior, and [README.md](README.md) for stack setup.

## Migrations and local setup

| Order | Migration | Effect |
| --- | --- | --- |
| 001 | [create_video_analysis](backend/migrations/001_create_video_analysis.sql) | Creates videos and four ordered content-analysis child tables |
| 002 | [create_tiktok_video_performance](backend/migrations/002_create_tiktok_video_performance.sql) | Adds optional TikTok count snapshots |
| 003 | [platform_agnostic_performance](backend/migrations/003_platform_agnostic_performance.sql) | Renames the snapshot table to `video_performance`, backfills source `tiktok`, preserves counts/timestamps |
| 004 | [meta_ads_metrics](backend/migrations/004_meta_ads_metrics.sql) | Adds nullable Ads JSONB and permits ad-only snapshots |
| 005 | [meta_library](backend/migrations/005_meta_library.sql) | Adds persistent Meta authorization, source identities, jobs, library snapshots, analysis ownership and versioning |

Start PostgreSQL and configure root `.env` as described in README. For a **new,
empty database only**, run from the repository root:

```sh
set -a
source .env
set +a
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/001_create_video_analysis.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/002_create_tiktok_video_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/003_platform_agnostic_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/004_meta_ads_metrics.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/005_meta_library.sql
```

For an **existing installation**, back up the database, establish which migrations
have already been applied, and run only the remaining files in numerical order.
If 001–004 are already applied, run only 005. These scripts are transactional,
not idempotent; there is no migration runner/history table or automatic startup
migration. Do not rerun the full sequence on an existing database. Inspect
`\dt`, `\d videos`, and `\d video_performance` in `psql` against the migration
files if the installation record is unavailable; resolve uncertainty before applying.
Migration 005 preserves existing analyses, UUIDs and performance snapshots and
backfills `videos.analysis_version` to 1; it does not infer source identities for
old uploads.

A content-schema fixture check runs inside a rollback transaction:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/tests/schema_roundtrip.sql
```

This checks representative analysis rows, not live Meta access or the full job
pipeline. See [testing](README.md#testing) for migration/repository/API and browser
integration tests against disposable PostgreSQL.

## Relationships and library storage

| Table | Purpose / key relationships |
| --- | --- |
| `videos` | UUID plus metadata, transcript, analysis version and optional Meta owner |
| `transcript_segments`, `scenes`, `on_screen_text`, `motion_events` | Ordered analysis rows linked by `video_id`; cascade on video deletion |
| `video_performance` | Legacy upload snapshot keyed by `video_id`; cascades on deletion |
| `meta_connections` | Unique private `external_user_id`, encrypted `token_ciphertext`, expiry, connection status and `next_sync_at` |
| `meta_sessions` | `token_hash` primary key, connection owner and expiry; no plaintext browser token |
| `meta_accounts` | UUID, connection, platform, private external/Page IDs, label, timezone, `initial_run_id` and `initialized_at` |
| `meta_library_items` | UUID, account/connection, platform, private `external_id`, content type, publication/seen times, `auto_analyze`, analysis/metrics states and safe errors, `video_id`, `analysis_version` |
| `meta_ad_assets` | Composite `(ad_item_id, video_item_id)` key; multiple ads can link to the same canonical video |
| `meta_library_performance` | One latest `snapshot JSONB` object and `fetched_at` per `item_id` |
| `meta_sync_runs` | Sync/analysis/metrics run, discovery-finalization flag, creation/finish times |
| `meta_jobs` | Durable task kind/payload, item/run/connection links, state, attempts, scheduling, claim UUID, lease and safe error |

Accounts and library items each enforce uniqueness on
`(connection_id, platform, external_id)`. Identical Facebook video IDs discovered
through video/Reel/ad paths share content analysis; different provider IDs are
not deduplicated by file similarity. Ads retain separate identities and snapshots.
Signed media URLs are not stored. External IDs and encrypted credentials stay
private; the authenticated library API returns internal UUIDs.

Imported `videos.meta_connection_id` restricts retrieval to its owning connection.
A successfully analyzed video item uses the same UUID for its item and `videos`
row; an ad's UUID is separate from its assets. Item `analysis_version` is nullable
until analyzed; the current pipeline constant is `ANALYSIS_VERSION = 1`.
Replacement analysis preserves the UUID and is committed atomically. Legacy
uploads have no source identity and cannot be automatically matched to imports.

Partial unique indexes allow one unfinished sync per connection and one active
queued/running/blocked task per item and kind. Job uniqueness within a run is
`(run_id, kind, task_key)`; leases support recovery after interruption. Disconnect
clears credentials/sessions and cancels work while retaining library data.
The retained library link to `videos` is a foreign key without a deletion cascade;
video deletion is not a public library API.

## Performance storage

`video_performance` is the legacy, single-snapshot table:

| Column | Type / meaning |
| --- | --- |
| `video_id` | UUID primary key referencing `videos.id` |
| `source` | Required text: `instagram`, `facebook`, `meta_ads`, or `tiktok`; no default |
| `view_count`, `like_count`, `comment_count`, `share_count` | Nullable nonnegative `BIGINT` counts |
| `fetched_at` | `TIMESTAMPTZ`, default `now()`, replaced on refresh |
| `meta_ads` | Nullable JSONB object allowed only for source `meta_ads` |

At least one count must be known, or the Ads object must contain a metric value
accepted by migration 004. A refresh replaces the snapshot rather than appending
a time series. Repository writes lock the video and reject a source conflict.
This legacy table stores no external media/account ID.

The V2 library instead writes `meta_library_performance.snapshot` with
`performance_source` and `performance_metrics`. It can retain independent organic
and multiple ad snapshots without overwriting each other or legacy data. Organic
snapshots can include optional reach/impressions as well as the four counts.
Missing metrics are unknown, not zero. API provenance adds `item_id`, `fetched_at`
and `organic`, `ad`, or `shared_ad` attribution. These are latest snapshots, not
historical performance series.

### Meta Ads JSONB

Both snapshot forms use `performance_metrics.meta_ads` in API evidence; in the
legacy table the object lives directly in the `meta_ads` column.

| Field | Representation / meaning |
| --- | --- |
| `impressions`, `reach`, `clicks` | Integer or null; reach is not summed across placements |
| `spend`, `ctr`, `cpc` | Exact decimal strings or null; CTR is all-click percentage |
| `actions`, `conversions`, `video_play_actions` | Arrays of action types with decimal-string `value`, `7d_click`, `1d_view`; missing values are null |
| `account_currency` | Provider currency or null; no assumed currency/conversion |
| `date_start`, `date_stop` | Reporting dates |
| `action_report_time`, `action_attribution_windows` | Requested reporting/attribution settings |

The provider requests ad-level, all-placement aggregates with `time_increment=all_days`,
`action_report_time=impression`, and `7d_click`/`1d_view` attribution. Automatic
library reporting runs from ad creation through today in the ad account timezone;
legacy manual requests supply the dates. `view_count` uses only `video_view`
(three-second views), not impressions or plays; ad likes/comments/shares remain null.
Explicit zero, empty arrays, missing arrays and fractional conversions remain
distinct. Rates are not recomputed and overlapping action types/windows are never
summed. Private ad identities are stored separately from the metric object.

## Content-analysis column reference

The numbered child keys preserve response order: segment/detection/event indexes
start at 0; scene numbers start at 1. Each video can have zero or many child rows.

### `videos`

| Column | PostgreSQL type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Unique video ID; defaults to `gen_random_uuid()` |
| `analysis_version` | `INTEGER`, default 1 | Positive processing version; existing analyses backfilled by 005 |
| `meta_connection_id` | `UUID`, nullable | Owner of imported Meta analysis; references `meta_connections.id` |
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
