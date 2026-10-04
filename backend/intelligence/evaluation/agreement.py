"""Pairwise descriptive agreement without collapsing timing into a single score."""

from itertools import combinations

from intelligence.ontology import AREAS, techniques
from intelligence.schemas.annotation import Annotation


def interval_iou(left, right):
    """Intersection/union for half-open interval collections, including gaps."""
    def merged(spans):
        result = []
        for start, end in sorted(spans):
            if result and start <= result[-1][1]:
                result[-1] = (result[-1][0], max(end, result[-1][1]))
            else:
                result.append((start, end))
        return result

    def length(spans):
        return sum(end - start for start, end in merged(spans))

    a, b = merged(left), merged(right)
    union = length(a + b)
    if not union:
        return None
    return round((length(a) + length(b) - union) / union, 4)


def point_distances(left, right):
    """Minimum-total-distance one-to-one pairing; unmatched events stay explicit."""
    # Exhaustive matching is unsuitable for edit-heavy videos. Ordered dynamic
    # programming yields minimum distance among monotone pairings of equal count.
    a, b = sorted(left), sorted(right)
    if len(a) > len(b):
        a, b = b, a
    if not a:
        return {"distances_seconds": [], "unmatched": len(b)}
    n, m = len(a), len(b)
    dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
    path = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        dp[0][j] = 0
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = dp[i][j - 1]
            match = dp[i - 1][j - 1] + abs(a[i - 1] - b[j - 1])
            dp[i][j] = min(skip, match)
            path[i][j] = "match" if match <= skip else "skip"
    distances = []
    i, j = n, m
    while i:
        if path[i][j] == "match":
            distances.append(round(abs(a[i - 1] - b[j - 1]), 4))
            i -= 1
        j -= 1
    return {"distances_seconds": list(reversed(distances)), "unmatched": m - n}


def compare(left: Annotation, right: Annotation) -> dict:
    if left.source != right.source:
        raise ValueError("Agreement requires the same source identity")
    if left.annotator_ref == right.annotator_ref:
        raise ValueError("Agreement requires distinct annotators")
    common = set(left.coverage.complete_technique_categories) & set(
        right.coverage.complete_technique_categories)
    rows = {}
    for identifier, definition in techniques().items():
        if definition.category not in common:
            continue
        a = [span for span in left.techniques if span.technique_id == identifier]
        b = [span for span in right.techniques if span.technique_id == identifier]
        row = {"left_present": bool(a), "right_present": bool(b),
               "presence_agrees": bool(a) == bool(b)}
        if definition.observation_kind == "interval":
            row["interval_iou"] = interval_iou(
                [(x.start_seconds, x.end_seconds) for x in a],
                [(x.start_seconds, x.end_seconds) for x in b])
        elif definition.observation_kind == "point":
            row["point_timing"] = point_distances(
                [x.start_seconds for x in a], [x.start_seconds for x in b])
        rows[identifier] = row
    roles = None
    if left.coverage.structure_complete and right.coverage.structure_complete:
        names = ("hook", "setup", "problem", "explanation", "demonstration",
                 "proof", "payoff", "cta", "other")
        roles = {role: interval_iou(
            [(x.start_seconds, x.end_seconds) for x in left.structure if x.role == role],
            [(x.start_seconds, x.end_seconds) for x in right.structure if x.role == role])
            for role in names}
    return {"source_ref": left.source.reference_id,
            "annotators": [left.annotator_ref, right.annotator_ref],
            "complete_categories_compared": sorted(common),
            "label_presence": rows, "structure_role_iou": roles}


def compare_all(annotations):
    by_source = {}
    for annotation in annotations:
        by_source.setdefault(annotation.source.reference_id, []).append(annotation)
    return [compare(a, b) for records in by_source.values()
            for a, b in combinations(records, 2)]
