"""Facebook Page video and Reel insights mapped to the common snapshot."""

import re
from typing import Literal

from app.meta import MetaClient, MetaError
from app.performance import VideoPerformance, performance_snapshot

MediaKind = Literal["videos", "reels"]
# Only explicit like reactions are likes; do not sum love, care, etc.
METRICS = {
    "videos": {
        "total_video_views": {None: "view_count"},
        "total_video_reactions_by_type_total": {"like": "like_count"},
        "total_video_stories_by_action_type": {"comment": "comment_count", "share": "share_count"},
    },
    "reels": {
        "fb_reels_total_plays": {None: "view_count"},
        "post_video_likes_by_reaction_type": {"REACTION_LIKE": "like_count"},
        "post_video_social_actions": {"COMMENT": "comment_count", "SHARE": "share_count"},
    },
}


class InvalidFacebookVideo(ValueError):
    pass


class FacebookMetricsUnavailable(ValueError):
    pass


def video_performance(
    client: MetaClient, page_id: str, media_id: str, kind: MediaKind,
) -> VideoPerformance:
    """Validate Page ownership and read lifetime counts for the supplied media kind."""
    if kind not in METRICS or any(not re.fullmatch(r"[0-9]{1,30}", value) for value in (page_id, media_id)):
        raise InvalidFacebookVideo("Provide numeric Facebook Page and video IDs and a valid media kind.")
    page = client.for_page(page_id)
    media = page.get(media_id, {"fields": "id,from"})
    if media.get("id") != media_id:
        raise MetaError("Facebook returned a different video ID.")
    owner = media.get("from")
    if not isinstance(owner, dict) or owner.get("id") != page_id:
        raise InvalidFacebookVideo("The Facebook video must belong to the selected Page.")
    fields = METRICS[kind]
    payload = page.get(f"{media_id}/video_insights", {"metric": ",".join(fields), "period": "lifetime"})
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise MetaError("Facebook returned invalid insights.")
    counts = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise MetaError("Facebook returned an invalid insight.")
        name = row["name"]
        if name not in fields:
            continue
        if name in seen or row.get("period") != "lifetime":
            raise MetaError("Facebook returned duplicate insights or an unexpected period.")
        seen.add(name)
        if "id" in row and row["id"] != f"{media_id}/video_insights/{name}/lifetime":
            raise MetaError("Facebook returned insights for a different video or period.")
        values = row.get("values")
        if values is None or values == []:
            continue
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise MetaError("Facebook returned invalid metric values.")
        value = values[0].get("value")
        if value is None:
            continue
        for key, field in fields[name].items():
            if key is not None and not isinstance(value, dict):
                raise MetaError("Facebook returned an invalid metric breakdown.")
            counts[field] = value if key is None else value.get(key)
    if not any(value is not None for value in counts.values()):
        raise FacebookMetricsUnavailable("Facebook has no available performance counts for this video.")
    try:
        return performance_snapshot("facebook", counts)
    except ValueError:
        raise MetaError("Facebook returned invalid performance counts.") from None
