"""
Randomizer and Timeline Planning Module for ClipForge.
Generates unique, multi-round de-duplicated video assembly plans
matching novel audio duration with minimum sequence repetition across batches.
"""

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
        min_segment_duration: Optional[float] = None,
        max_segment_duration: Optional[float] = None,
        randomize_start: bool = False
    ) -> tuple[list[TimelineSegment], list[str], list[str]]:
        """
        Builds a single assembly candidate:
        - Shuffles clips per round.
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

        while accumulated < target_duration - 1e-4:
            current_pool = clips.copy()
            self.rng.shuffle(current_pool)

            # Prevent adjacent round boundary repetition (round K end == round K+1 start)
            if round_num > 1 and len(current_pool) >= 2 and current_pool[0].sha256 == last_clip_sha:
                # Swap first item with another one
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
        Generates 'count' distinct assembly plans, using previous_plans to minimize similarity.
        Gracefully handles small clip pools without infinite loops.
        """
        if not clips:
            raise ValueError("可用素材列表为空，无法生成组合计划。")
        if target_duration <= 0:
            raise ValueError(f"目标时长无效: {target_duration}")
        if count <= 0:
            return []

        all_plans: list[TimelinePlan] = list(previous_plans or [])
        new_plans: list[TimelinePlan] = []

        # Theoretical distinct permutations estimation
        n = len(clips)
        is_severely_constrained = (n <= 2 and count > n)

        for i in range(count):
            plan_id = len(all_plans) + 1
            best_candidate: Optional[tuple[list[TimelineSegment], list[str], list[str]]] = None
            lowest_max_similarity = 2.0  # similarity in [0.0, 1.0]

            # Generate multiple candidates and select the one most dissimilar to all existing plans
            attempts = 1 if is_severely_constrained and n == 1 else max_candidate_attempts

            for _ in range(attempts):
                segments, seq, notes = self.generate_single_candidate(
                    clips,
                    target_duration,
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

                # If candidate is completely distinct (0.0 similarity), stop search early
                if lowest_max_similarity == 0.0:
                    break

            assert best_candidate is not None
            final_segments, final_seq, final_notes = best_candidate
            uniqueness_score = round(1.0 - min(lowest_max_similarity, 1.0), 4)

            if is_severely_constrained:
                final_notes.append(
                    f"可用素材数量极少 (N={n})，已达到独立组合数学上限，允许部分顺序复用"
                )

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
