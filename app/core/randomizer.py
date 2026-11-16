"""
Randomizer and Timeline Planning Module for ClipForge.
Generates unique, multi-round de-duplicated video assembly plans
matching novel audio duration with minimum sequence repetition across batches.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import random
from typing import Optional

from app.core.media_scanner import ClipInfo


@dataclass
class TimelineSegment:
    clip_path: str
    clip_sha256: str
    display_name: str
    start_time: float      # Start time within the source clip (seconds)
    duration: float        # Duration to be used (seconds)


@dataclass
class TimelinePlan:
    plan_id: int
    segments: list[TimelineSegment] = field(default_factory=list)
    total_duration: float = 0.0
    clip_sequence: list[str] = field(default_factory=list)  # Sequence of SHA-256 or display names
    uniqueness_score: float = 1.0  # 1.0 = completely distinct, 0.0 = completely identical
    notes: list[str] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def calculate_sequence_similarity(seq1: list[str], seq2: list[str]) -> float:
    """
    Computes sequence similarity score between 0.0 and 1.0.
    Combines:
    1. Prefix matching (starting clips give the primary visual impression) - weight 0.4
    2. Positional exact matches - weight 0.3
    3. Bi-gram sequence overlap (Jaccard on adjacent pairs) - weight 0.3
    """
    if not seq1 or not seq2:
        return 0.0

    min_len = min(len(seq1), len(seq2))
    max_len = max(len(seq1), len(seq2))

    # 1. Prefix match (up to 3 items)
    prefix_len = min(3, min_len)
    prefix_matches = sum(1 for i in range(prefix_len) if seq1[i] == seq2[i])
    prefix_score = prefix_matches / prefix_len if prefix_len > 0 else 0.0

    # 2. Positional match
    pos_matches = sum(1 for i in range(min_len) if seq1[i] == seq2[i])
    pos_score = pos_matches / max_len

    # 3. Bigram overlap
    def get_bigrams(seq: list[str]) -> set[tuple[str, str]]:
        return {(seq[i], seq[i + 1]) for i in range(len(seq) - 1)}

    bg1 = get_bigrams(seq1)
    bg2 = get_bigrams(seq2)
    if not bg1 and not bg2:
        bigram_score = 1.0 if seq1 == seq2 else 0.0
    elif not bg1 or not bg2:
        bigram_score = 0.0
    else:
        intersection = len(bg1.intersection(bg2))
        union = len(bg1.union(bg2))
        bigram_score = intersection / union if union > 0 else 0.0

    return round(0.4 * prefix_score + 0.3 * pos_score + 0.3 * bigram_score, 4)


class Randomizer:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def generate_single_candidate(
        self,
        clips: list[ClipInfo],
        target_duration: float,
        opening_clip: Optional[ClipInfo] = None,
        global_usage: Optional[dict[str, int]] = None,
        min_segment_duration: Optional[float] = None,
        max_segment_duration: Optional[float] = None,
        randomize_start: bool = False
    ) -> tuple[list[TimelineSegment], list[str], list[str]]:
        """
        Builds a single assembly candidate:
        - Pins opening_clip as the first segment if provided (guaranteeing unique openers across batches).
        - Prioritizes globally least-used clips across the batch to minimize scene overlap across videos.
        - Avoids repeating last item of round K as first item of round K+1.
        - Truncates last segment to exactly fit remaining duration.
        - Optionally slices clips into micro-segments with varied start times.
        """
        segments: list[TimelineSegment] = []
        clip_sequence: list[str] = []
        notes: list[str] = []

        accumulated = 0.0
        round_num = 1
        last_clip_sha: Optional[str] = None

        # 1. Handle specified opening clip
        if opening_clip is not None:
            remaining = round(target_duration - accumulated, 3)
            if min_segment_duration is not None and max_segment_duration is not None:
                high_dur = min(max_segment_duration, opening_clip.duration, remaining)
                low_dur = min(min_segment_duration, high_dur)
                use_dur = round(self.rng.uniform(low_dur, high_dur), 3)
                max_start = max(0.0, opening_clip.duration - use_dur)
                start_time = round(self.rng.uniform(0.0, max_start), 3) if (randomize_start and max_start > 0) else 0.0
            else:
                use_dur = min(opening_clip.duration, remaining)
                start_time = 0.0

            segments.append(
                TimelineSegment(
                    clip_path=opening_clip.path,
                    clip_sha256=opening_clip.sha256,
                    display_name=opening_clip.display_name,
                    start_time=start_time,
                    duration=round(use_dur, 3)
                )
            )
            clip_sequence.append(opening_clip.display_name)
            accumulated = round(accumulated + use_dur, 3)
            last_clip_sha = opening_clip.sha256

        # Helper to sort clips by global usage tiers, randomizing within each tier
        def get_tiered_pool(candidate_list: list[ClipInfo]) -> list[ClipInfo]:
            if not global_usage:
                pool = candidate_list.copy()
                self.rng.shuffle(pool)
                return pool
            by_usage: dict[int, list[ClipInfo]] = defaultdict(list)
            for c in candidate_list:
                by_usage[global_usage.get(c.sha256, 0)].append(c)
            pool: list[ClipInfo] = []
            for u in sorted(by_usage.keys()):
                tier = by_usage[u].copy()
                self.rng.shuffle(tier)
                pool.extend(tier)
            return pool

        # 2. Fill the remainder of target_duration
        # For round 1: exclude the opening_clip if there are other clips available
        first_round_candidates = [
            c for c in clips if c.sha256 != (opening_clip.sha256 if opening_clip else None)
        ]
        if not first_round_candidates:
            first_round_candidates = clips.copy()

        current_pool = get_tiered_pool(first_round_candidates)

        while accumulated < target_duration - 1e-4:
            if round_num > 1:
                current_pool = get_tiered_pool(clips)
                # Prevent adjacent round boundary repetition (round K end == round K+1 start)
                if len(current_pool) >= 2 and current_pool[0].sha256 == last_clip_sha:
                    swap_idx = self.rng.randint(1, len(current_pool) - 1)
                    current_pool[0], current_pool[swap_idx] = current_pool[swap_idx], current_pool[0]

            for clip in current_pool:
                remaining = round(target_duration - accumulated, 3)
                if remaining <= 1e-4:
                    break

                if min_segment_duration is not None and max_segment_duration is not None:
                    if remaining < min_segment_duration:
                        if segments:
                            # Merge remaining into previous segment
                            segments[-1].duration = round(segments[-1].duration + remaining, 3)
                            accumulated = round(accumulated + remaining, 3)
                            break
                        else:
                            use_dur = remaining
                    else:
                        high_dur = min(max_segment_duration, clip.duration, remaining)
                        low_dur = min(min_segment_duration, high_dur)
                        use_dur = round(self.rng.uniform(low_dur, high_dur), 3)

                    max_start = max(0.0, clip.duration - use_dur)
                    start_time = round(self.rng.uniform(0.0, max_start), 3) if (randomize_start and max_start > 0) else 0.0
                else:
                    if clip.duration <= remaining:
                        use_dur = clip.duration
                    else:
                        use_dur = remaining
                    start_time = 0.0

                segments.append(
                    TimelineSegment(
                        clip_path=clip.path,
                        clip_sha256=clip.sha256,
                        display_name=clip.display_name,
                        start_time=start_time,
                        duration=round(use_dur, 3)
                    )
                )
                clip_sequence.append(clip.display_name)
                accumulated = round(accumulated + use_dur, 3)
                last_clip_sha = clip.sha256

            if round_num > 1:
                notes.append(f"素材总时长不足以覆盖音频，已进入第 {round_num} 轮循环使用")
            round_num += 1

        if segments:
            diff = round(target_duration - sum(s.duration for s in segments), 3)
            if abs(diff) > 1e-4:
                segments[-1].duration = round(segments[-1].duration + diff, 3)

        return segments, clip_sequence, notes

    def generate_batch_plans(
        self,
        clips: list[ClipInfo],
        target_duration: float,
        count: int,
        previous_plans: Optional[list[TimelinePlan]] = None,
        max_candidate_attempts: int = 35,
        min_segment_duration: Optional[float] = None,
        max_segment_duration: Optional[float] = None,
        randomize_start: bool = False
    ) -> list[TimelinePlan]:
        """
        Generates 'count' distinct assembly plans:
        1. Guarantees 100% unique opening clips across all videos when len(clips) >= count.
        2. Applies global clip dispersion across the entire batch to minimize footage overlap between videos.
        3. Minimizes sequence similarity against previous_plans and earlier batch plans.
        """
        if not clips:
            raise ValueError("可用素材列表为空，无法生成组合计划。")
        if target_duration <= 0:
            raise ValueError(f"目标时长无效: {target_duration}")
        if count <= 0:
            return []

        all_plans: list[TimelinePlan] = list(previous_plans or [])
        new_plans: list[TimelinePlan] = []

        n = len(clips)
        is_severely_constrained = (n <= 2 and count > n)

        # 1. Allocate opening clips across the batch
        # When len(clips) >= count, strictly sample distinct openers (zero opener duplicate)
        if n >= count:
            opening_clips = self.rng.sample(clips, count)
        else:
            # If clips < count, cycle shuffled batches so maximum distinct openers are used before reuse
            openers_pool: list[ClipInfo] = []
            while len(openers_pool) < count:
                shuffled_batch = clips.copy()
                self.rng.shuffle(shuffled_batch)
                openers_pool.extend(shuffled_batch)
            opening_clips = openers_pool[:count]

        # 2. Track global clip usage across the batch (seed with previous_plans if any)
        global_usage: dict[str, int] = defaultdict(int)
        for p in all_plans:
            for s in p.segments:
                global_usage[s.clip_sha256] += 1

        # 3. Generate each plan
        for i in range(count):
            opener = opening_clips[i]
            plan_id = len(all_plans) + 1
            best_candidate: Optional[tuple[list[TimelineSegment], list[str], list[str]]] = None
            lowest_max_similarity = 2.0  # similarity in [0.0, 1.0]

            attempts = 1 if is_severely_constrained and n == 1 else max_candidate_attempts

            for _ in range(attempts):
                segments, seq, notes = self.generate_single_candidate(
                    clips=clips,
                    target_duration=target_duration,
                    opening_clip=opener,
                    global_usage=global_usage,
                    min_segment_duration=min_segment_duration,
                    max_segment_duration=max_segment_duration,
                    randomize_start=randomize_start
                )
                
                # Check maximum similarity against all existing plans
                if not all_plans:
                    max_sim = 0.0
                else:
                    max_sim = max(
                        calculate_sequence_similarity(seq, p.clip_sequence)
                        for p in all_plans
                    )

                if max_sim < lowest_max_similarity:
                    lowest_max_similarity = max_sim
                    best_candidate = (segments, seq, notes)

                if lowest_max_similarity == 0.0:
                    break

            assert best_candidate is not None
            final_segments, final_seq, final_notes = best_candidate
            uniqueness_score = round(1.0 - min(lowest_max_similarity, 1.0), 4)

            # Record human-readable note about opening clip and dispersion
            opener_name = final_segments[0].display_name if final_segments else ""
            final_notes.insert(0, f"首镜头专属分配: {opener_name} (批次内首发互斥不重复)")

            # Record overlap statistics against earlier plans in the batch
            if all_plans:
                current_clip_set = set(final_seq)
                max_overlap = max(
                    len(current_clip_set.intersection(set(p.clip_sequence)))
                    for p in all_plans
                )
                if max_overlap == 0:
                    final_notes.append("跨视频素材完全独立 (与此前成片零重合)")
                else:
                    final_notes.append(f"跨视频最大重合镜头数: {max_overlap}/{len(current_clip_set)} (全局均衡分散)")

            if is_severely_constrained:
                final_notes.append(
                    f"可用素材数量极少 (N={n})，已达到独立组合数学上限，允许部分顺序复用"
                )

            # Update global usage with chosen candidate's segments
            for seg in final_segments:
                global_usage[seg.clip_sha256] += 1

            plan = TimelinePlan(
                plan_id=plan_id,
                segments=final_segments,
                total_duration=round(sum(s.duration for s in final_segments), 3),
                clip_sequence=final_seq,
                uniqueness_score=uniqueness_score,
                notes=final_notes
            )

            new_plans.append(plan)
            all_plans.append(plan)

        return new_plans
